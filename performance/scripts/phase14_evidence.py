"""Streaming raw-sample aggregation and fail-closed Phase14 safety rules."""
from __future__ import annotations
from collections import defaultdict
from contextlib import closing
import gzip
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import re
from datetime import datetime

RESULTS=('business_success','business_conflict','capacity_rejection','system_error','unexpected_contract')
ALLOWED_TAGS={'scenario','step','result','shard','status','method','name','expected_response','error_code','group','check'}
VERSION='phase14-raw-sqlite-linear-v1'


def timestamp(value):
    """k6 RFC3339Nano permits any 1..9 fractional digits; Python 3.10 does not."""
    normalized=re.sub(r'\.(\d+)(?=Z|[+-]\d\d:\d\d$)',lambda m:'.'+m[1][:6].ljust(6,'0'),value)
    return datetime.fromisoformat(normalized.replace('Z','+00:00')).timestamp()


def sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024),b''):digest.update(block)
    return digest.hexdigest()


def percentile(values,p):
    if not values:return None
    values=sorted(values); position=(len(values)-1)*p; low=math.floor(position);high=math.ceil(position)
    return values[low]+(values[high]-values[low])*(position-low)


def aggregate(root, shards, plan, *, start=None, end=None):
    """Recompute percentiles from every raw observation; never read shard p95.

    External SQLite sort bounds Python memory. Summary emits no token or IDs.
    `plan` maps actual k6 scenario names to logical iteration counts (None for closed).
    """
    root=Path(root); ids=[str(x['shard']) for x in shards]
    if not ids or len(ids)!=len(set(ids)):raise ValueError('missing or duplicate shard')
    counters=defaultdict(float);types={};inputs=[]; groups=set(); windows=defaultdict(lambda:defaultdict(float))
    with tempfile.TemporaryDirectory(dir=root) as temporary, closing(sqlite3.connect(str(Path(temporary)/'points.sqlite'))) as db:
        db.execute('CREATE TABLE points (metric TEXT, tags TEXT, value REAL)')
        for shard in shards:
            folder=root/'shards'/str(shard['shard']);path=folder/'raw.json.gz'
            expected=(folder/'raw.json.gz.sha256').read_text().strip()
            if sha256(path)!=expected:raise ValueError('shard checksum mismatch')
            inputs.append({'shard':str(shard['shard']),'sha256':expected,'bytes':path.stat().st_size})
            saw=False
            with gzip.open(path,'rt',encoding='utf-8') as source:
                for line in source:
                    item=json.loads(line)
                    if item.get('type')=='Metric':
                        types[item['metric']]=item['data']['type'];continue
                    if item.get('type')!='Point':raise ValueError('unknown raw record')
                    data=item['data'];tags=data.get('tags') or {};metric=item['metric'];value=data['value']
                    if not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError('invalid point')
                    if tags.keys()-ALLOWED_TAGS:raise ValueError('unbounded metric labels')
                    if tags.get('shard',str(shard['shard']))!=str(shard['shard']):raise ValueError('wrong shard label')
                    if metric.startswith('phase14_') and 'shard' not in tags:raise ValueError('missing shard label')
                    if start and timestamp(data['time'])<timestamp(start) or end and timestamp(data['time'])>=timestamp(end):continue
                    saw=True
                    scenario=tags.get('scenario','');step=tags.get('step','');result=tags.get('result','')
                    if metric.startswith('phase14_') and scenario not in plan:raise ValueError('unbounded or missing scenario label')
                    if metric=='phase14_results' and result not in RESULTS:raise ValueError('invalid result classification')
                    key=json.dumps([scenario,step,result],separators=(',',':'))
                    if types.get(metric)=='counter':counters[(metric,key)]+=value
                    if types.get(metric) in ('trend','gauge') and metric.startswith('phase14_'):
                        db.execute('INSERT INTO points VALUES (?,?,?)',(metric,key,value));groups.add((metric,key))
                    if metric=='phase14_results':
                        bucket=data['time'][:19]
                        windows[bucket]['completed']+=value
                        if result in ('system_error','unexpected_contract'):windows[bucket]['errors']+=value
            if not saw:raise ValueError('empty shard evidence')
        db.commit();db.execute('CREATE INDEX quantile ON points(metric,tags,value)')
        trends=[]
        for metric,key in sorted(groups):
            n=db.execute('SELECT count(*) FROM points WHERE metric=? AND tags=?',(metric,key)).fetchone()[0]
            def value_at(offset):return db.execute('SELECT value FROM points WHERE metric=? AND tags=? ORDER BY value LIMIT 1 OFFSET ?',(metric,key,offset)).fetchone()[0]
            quantiles={}
            for label,p in [('p50',.5),('p95',.95),('p99',.99)]:
                pos=(n-1)*p;lo=math.floor(pos);hi=math.ceil(pos);a=value_at(lo);b=value_at(hi)
                quantiles[label]=a+(b-a)*(pos-lo)
            trends.append({'metric':metric,'tags':json.loads(key),'count':n,**quantiles,'max':value_at(n-1)})
        db.close()
    rows=[{'metric':m,'tags':json.loads(k),'count':v} for (m,k),v in sorted(counters.items())]
    def count(metric,scenario=None,step=None,result=None):
        return sum(r['count'] for r in rows if r['metric']==metric and
                   (scenario is None or r['tags'][0]==scenario) and (step is None or r['tags'][1]==step) and
                   (result is None or r['tags'][2]==result))
    errors=[]; delivered={}
    for scenario,planned in plan.items():
        a=count('phase14_iterations_started',scenario);b=count('phase14_iterations_completed',scenario)
        delivered[scenario]={'planned':planned,'started':a,'completed':b,'interrupted':a-b}
        if planned is not None and a!=planned:errors.append(f'{scenario}: planned != started')
        if not a or a!=b:errors.append(f'{scenario}: missing/interrupted iterations')
    steps={(r['tags'][0],r['tags'][1]) for r in rows if r['metric']=='phase14_started'}
    for scenario,step in steps:
        if count('phase14_started',scenario,step)!=count('phase14_results',scenario,step):errors.append(f'{scenario}/{step}: classification not conserved')
    dropped=count('dropped_iterations')
    if dropped:errors.append('dropped iterations')
    return {'version':VERSION,'inputs':inputs,'start':start,'end':end,'counts':rows,'trends':trends,
            'delivery':delivered,'dropped':dropped,'errors':errors,'seconds':dict(windows)}


def smoke_policy(t):
    populations=[t['burst']['users'],t['hotspot']['users'],t['login']['users']]
    populations += [s['users'] for stages in t['online']['rounds'] for s in stages]
    return t.get('mode')=='smoke' and max(populations)<t['formalActiveUserTarget']


def swap_policy(x,t):
    if not x['swapping']:return None,None
    # Only isolated swap-in is exempted. Swap-out and incomplete direction
    # evidence retain the original fail-closed stop, including rising memory.
    if smoke_policy(t) and x.get('swapInDelta',0)>0 and x.get('swapOutDelta')==0:
        return None,{'code':'host_swap_activity','time':x['time'],'swapInDelta':x['swapInDelta'],'swapOutDelta':0}
    return 'invalid generator/host: swapping',None


class StopGuard:
    """Monotonic timestamp samples. A missing field is invalid evidence, never zero."""
    def __init__(self,t,*,login_protection=False):
        self.t=t;self.login_protection=login_protection;self.since={};self.error_windows=[];self.warnings=[]
    def sustained(self,name,condition,now,seconds):
        if not condition:self.since.pop(name,None);return False
        self.since.setdefault(name,now)
        return now-self.since[name]>=seconds
    def error_window(self,completed,errors):
        s=self.t['stop']
        bad=completed>=s['minErrorSamples'] and errors/completed>s['errorFraction']
        self.error_windows.append(bad)
        return (completed<s['minErrorSamples'] and errors>=s['smallWindowErrors'] or
                len(self.error_windows)>=s['consecutiveErrorWindows'] and all(self.error_windows[-s['consecutiveErrorWindows']:]))
    def sample(self,x):
        s=self.t['stop'];g=self.t['generator'];now=x['time'];reasons=[]
        for key in ('correctnessFailure','restarted','oom','unhealthy','wrongEnvironment'):
            if x[key]:reasons.append(key)
        swap_error,warning=swap_policy(x,self.t)
        if swap_error:reasons.append(swap_error)
        if warning:self.warnings.append(warning)
        for key in ('networkExhausted','fdExhausted'):
            if x[key]:reasons.append('invalid generator/host: '+key)
        if x['generatorMemoryFraction']>=g['memoryFraction']:reasons.append('invalid generator memory')
        if self.sustained('generatorCpu',x['generatorCpuFraction']>=g['cpuFraction'],now,g['cpuContinuousSeconds']):reasons.append('invalid generator cpu')
        if abs(x['clockSkewMs'])>g['maxClockSkewMs'] or x['dropped']>g['dropped']:reasons.append('invalid scheduling')
        if x['memoryFraction']>s['memoryFraction']:reasons.append('SUT memory')
        if x['transactionOldestSeconds']>s['oldestTransactionSeconds']:reasons.append('transaction oldest')
        if self.sustained('tx',x['transactionWaiters']>s['transactionWaiters'],now,s['transactionWaitSeconds']):reasons.append('transaction waiters')
        if self.sustained('stalled',x['httpInflight']>s['stalledInflight'] and x['completionsSinceLast']==0,now,s['stallSeconds']):reasons.append('stalled HTTP')
        for key in ('hashQueueFraction','seatQueueFraction'):
            exempt=self.login_protection and key=='hashQueueFraction'
            if self.sustained(key,not exempt and x[key]>=s['queueFraction'],now,s['queueSeconds']):reasons.append(key)
        return reasons


def recovery(samples,controls,baseline,t,stop_time):
    r=t['recovery'];errors=[]
    if not samples:return {'passed':False,'errors':['missing recovery samples']}
    duration=r['continuousSeconds'];max_gap=t['generator']['sampleSeconds']*2
    def window(predicate,deadline=None):
        began=None;previous=None
        for x in samples:
            now=x['time']
            if now<stop_time:continue
            if previous is not None and now-previous>max_gap:began=None
            if predicate(x):
                if began is None:began=now
                if now-began>=duration and (deadline is None or began<=stop_time+deadline):return True
            else:began=None
            previous=now
        return False
    if not window(lambda x:all(x[k]==0 for k in ('transactionWaiters','transactionOldestSeconds','hashQueue','seatQueue')),r['queueZeroDeadlineSeconds']):errors.append('queues not drained continuously')
    if not window(lambda x:x['httpInflight']<=baseline['httpIdleMax']+r['inflightIdleAllowance'] and x['redisInflight']<=baseline['redisIdleMax']+r['inflightIdleAllowance']):errors.append('inflight not recovered')
    if not window(lambda x:all(x[k]==0 for k in ('pgLockWaits','pgBlocking','pgIdleTransaction','pgIdleAborted'))):errors.append('postgres not recovered')
    for step in ('health','auth','availability'):
        window_samples=[x for x in controls if x['step']==step and stop_time<=x['time']<stop_time+r['controlWindowSeconds']]
        if any(x['result']!='business_success' for x in window_samples):errors.append('control recovery errors: '+step)
        values=[x['ms'] for x in window_samples if x['result']=='business_success']
        p95=percentile(values,.95)
        if len(values)<r['controlMinSamples'] or p95>min(t['latencyMs'][step][0],baseline['controlP95'][step]*r['controlBaselineRatio']):errors.append('control recovery: '+step)
    memory=[x['memoryFraction'] for x in samples]
    if max(memory)>=r['memoryPeakFraction']:errors.append('memory peak')
    end=samples[-1]['time'];w=r['memoryWindowSeconds']
    a=[x['memoryFraction'] for x in samples if end-2*w<=x['time']<end-w];b=[x['memoryFraction'] for x in samples if end-w<=x['time']<=end]
    if not a or not b or sum(b)/len(b)-sum(a)/len(a)>r['memoryGrowthFraction']:errors.append('memory growth/window')
    if any(x['restarted'] or x['oom'] for x in samples):errors.append('restart/OOM')
    return {'passed':not errors,'errors':errors,'observedSeconds':end-stop_time}


def verdict(summary,correctness,recovered,validity,t,*,overload=False,smoke=False):
    reasons=list(summary['errors'])+list(validity.get('errors',[]))
    reasons += sorted({x['code'] for x in validity.get('warnings',[])})
    if not summary['counts'] or not summary['trends']:reasons.append('missing request evidence')
    if not validity.get('isolated'):reasons.append('local_characterization_only')
    if smoke:reasons.append('smoke input is not formal capacity')
    bad=[]
    for row in summary['counts']:
        if row['metric']=='phase14_results' and row['tags'][2] in ('capacity_rejection','system_error','unexpected_contract') and row['count']:
            bad.append(row['tags'])
    latency=[]
    for row in summary['trends']:
        scenario,step,result=row['tags']
        limit=t['latencyMs'].get(step.removeprefix('startup_'))
        if row['metric']=='phase14_duration_ms' and result=='business_success' and limit and (row['p95']>limit[0] or row['p99']>limit[1]):latency.append(row['tags'])
    valid=not reasons;correct=correctness.get('passed') is True;rest=recovered.get('passed') is True
    system_bad=any(x[2] in ('system_error','unexpected_contract') for x in bad)
    unexpected_rejection=any(x[2]=='capacity_rejection' and x[1]!='login' for x in bad)
    busy_latency=any(row['metric']=='phase14_duration_ms' and row['tags'][1:] == ['login','capacity_rejection'] and
                     (row['p95']>t['login']['busyLatencyMs'][0] or row['p99']>t['login']['busyLatencyMs'][1]) for row in summary['trends'])
    result={'measurement_validity':{'status':'pass' if valid else 'fail','reasons':reasons},
            'capacity':{'status':'pass' if valid and correct and rest and not bad and not latency else 'not_applicable' if not valid else 'fail','badResults':bad,'latencyFailures':latency},
            'overload_protection':{'status':'not_applicable' if not overload else 'pass' if valid and correct and rest and not system_bad and not unexpected_rejection and not busy_latency and not latency else 'fail',
                                   'reason':'not an overload experiment' if not overload else 'requires correctness, valid delivery, controls and recovery'}}

    if smoke:
        result['diagnostic']={'capacity':result['capacity'],'overload_protection':result['overload_protection'],
                              'formalRecovery':recovered,'latencyFailures':latency}
        for key in ('capacity','overload_protection','formal_recovery'):
            result[key]={'status':'not_applicable','reason':'smoke sample size and duration do not qualify for formal performance evaluation'}
        result['functional']={'status':'pass' if correct and bool(summary['counts'] and summary['trends']) and not summary['errors'] and not validity.get('errors') and not system_bad else 'fail'}
    return result
