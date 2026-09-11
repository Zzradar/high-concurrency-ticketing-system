#!/usr/bin/env python3
"""Guarded Phase14 campaign. Default is a read-only plan; --yes authorizes execution."""
from __future__ import annotations
import argparse
from copy import deepcopy
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from fractions import Fraction
import gzip
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
from urllib.request import build_opener, ProxyHandler, Request

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'performance/data'),str(ROOT/'performance/verification')]
import generate_dataset as dataset
from verify_database import parse_verifier_output, DEFAULT_SQL_FILE
from run_k6 import K6_IMAGE, utc_now
from performance_evidence import parse_redis_info
from phase14_model import load_targets, online_plan, segments, background, seat
from phase14_evidence import aggregate, sha256, verdict, StopGuard, recovery, percentile, timestamp, swap_policy, smoke_policy
from phase14_sampling import Sampler, LightPostgresSampler, pg_snapshot, pg_delta
from phase14_verify import verify_run, expiry_fixture, capture_temporary_owners

COMPOSE=ROOT/'performance/docker-compose.phase14.yml'
RESULTS=ROOT/'performance/results'
GENERATED=ROOT/'performance/generated/phase14'
PROJECT_RE=re.compile(r'^phase14-[a-z0-9]+(?:-[a-z0-9]+)*$')


def write(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def guard_model(model,project,data_root,t):
    if not PROJECT_RE.fullmatch(project) or model.get('name')!=project:raise ValueError('not a dedicated Phase14 project')
    allowed={project+'_postgres',project+'_prometheus'}
    volumes=model.get('volumes',{})
    if {v.get('name') for v in volumes.values()}!=allowed:raise ValueError('unsafe volume names')
    if any(v.get('external') for v in volumes.values()):raise ValueError('external volume rejected')
    if data_root.resolve().parent!=GENERATED.resolve():raise ValueError('data mount outside Phase14')
    services=model['services']
    if any(v.get('external') for v in model.get('networks',{}).values()):raise ValueError('external network rejected')
    if services['backend']['environment'].get('TICKETING_PAYMENT_PROVIDER')!='simulation':raise ValueError('simulation required')
    if services['backend']['command']!=['./ticketing_backend','config/config.phase14.json']:raise ValueError('wrong backend config')
    if services['postgres']['environment']['POSTGRES_DB']!=t['environment']['database']:raise ValueError('wrong database')
    for service in services.values():
        if service.get('external_links') or service.get('network_mode') or service.get('container_name'):raise ValueError('external service sharing rejected')
        for mount in service.get('volumes',[]):
            if mount['type']=='volume' and mount['source'] not in volumes:raise ValueError('unrecognized data volume')
            if mount['type']=='bind':
                source=Path(mount['source']).resolve()
                safe_sources={data_root.resolve(),(ROOT/'performance/results').resolve(),
                    (ROOT/'performance/k6').resolve(),(ROOT/'performance/phase14/queries.yml').resolve(),
                    (ROOT/'performance/phase14/noop.conf').resolve(),
                    (ROOT/'performance/phase14/prometheus.yml').resolve(),(ROOT/'performance/phase14/init.sh').resolve(),
                    (ROOT/'performance/postgres/000_observability.sql').resolve(),(ROOT/'backend/db/migrations').resolve()}
                if source not in safe_sources:raise ValueError('unrecognized bind mount')
                if source!=(ROOT/'performance/results').resolve() and not mount.get('read_only'):raise ValueError('input mount must be read-only')
    return sorted(allowed)


def guard_delivery(scenarios,t):
    """Preserve the business curve; only keep the executor alive beyond its endpoint."""
    schedule={};seconds=t['generator']['scheduler_delivery_guard_seconds']
    for name,scenario in scenarios.items():
        kind=scenario['executor']
        if kind not in ('constant-arrival-rate','ramping-arrival-rate'):continue
        original=deepcopy(scenario)
        if kind=='constant-arrival-rate':
            duration=float(scenario['duration'][:-1]);scenario['duration']=f'{duration+seconds:g}s'
        else:
            duration=sum(float(x['duration'][:-1]) for x in scenario['stages'])
            scenario['stages'].append({'target':scenario['stages'][-1]['target'],'duration':f'{seconds:g}s'})
        schedule[name]={'businessExecutor':original,'businessWindowSeconds':duration,
                        'schedulerGuardSeconds':seconds,'executorWindowSeconds':duration+seconds}
    return schedule


def build_spec(t,case,run_id,*,round_index=0,window_index=0,path='formal',session_count=1,control_only=False,passed_u1=None,passed_u2=None):
    if case not in ('G0','U1','U2','J1','O1','H1','H2','H3','L1','L2','S1'):raise ValueError('unknown case')
    if not 0<=round_index<len(t['online']['rounds']) or not 0<=window_index<len(t['burst']['windowsSeconds']):raise ValueError('invalid round/window')
    if path not in ('formal','temporary') or session_count not in [1,*t['hotspot']['h2SessionCounts']]:raise ValueError('invalid hotspot path/scope')
    scenarios={};mapping={};plan={};grace=t['probes']['paymentDeadlineSeconds']+max(t['behavior']['refreshSeconds'])
    def arrival(name,fn,count,seconds,start=0,**meta):
        if count<=0 or seconds<=0:raise ValueError('invalid arrival schedule')
        rate=Fraction(count,1)/Fraction(seconds)
        # k6 may schedule a boundary tick before the capped function can return.
        # Reserve one idle VU per maximum shard; this changes no HTTP input count.
        vus=min(math.ceil(count),t['burst']['users'])+t['generator']['maxShards']
        scenarios[name]={'executor':'constant-arrival-rate','exec':fn,'rate':rate.numerator,'timeUnit':f'{rate.denominator}s','duration':f'{seconds}s','startTime':f'{start}s','preAllocatedVUs':vus,'gracefulStop':f'{grace}s'}
        mapping[name]={'count':math.ceil(count),**meta};plan[name]=math.ceil(count)
    if case=='G0':
        total=t['burst']['windowsSeconds'][-1]
        arrival('main','control',t['burst']['users'],total,step='health')
        workload='phase14-online'
    elif case in ('U1','U2'):
        p=online_plan(t,round_index);total=p[-1]['startSeconds']+p[-1]['durationSeconds']
        if case=='U1':
            scenarios['main']={'executor':'ramping-vus','exec':'online','startVUs':0,'stages':[{'target':x['users'],'duration':f"{x['durationSeconds']}s"} for x in p], 'gracefulRampDown':f'{grace}s','gracefulStop':f'{grace}s'}
            mapping['main']={'users':p[-1]['users']};plan['main']=None
        else:
            for i,x in enumerate(p):
                if x['enterCount']:
                    arrival(f'enter_{i}','enter',x['enterCount'],x['durationSeconds'],x['startSeconds'],offset=x['previousUsers'])
                name=f'refresh_{i}';integral=Fraction(x['refreshIntegral'])
                scenarios[name]={'executor':'ramping-arrival-rate','exec':'refresh','startRate':x['previousUsers'],'timeUnit':f"{x['refreshTimeUnitSeconds']}s",'preAllocatedVUs':min(t['burst']['users'],max(20,x['users']//5)), 'stages':[{'target':x['users'],'duration':f"{x['durationSeconds']}s"}],'startTime':f"{x['startSeconds']}s",'gracefulStop':f'{grace}s'}
                mapping[name]={'users':x['users'],'count':math.ceil(integral)};plan[name]=math.ceil(integral)
        workload='phase14-online'
    elif case in ('J1','O1'):
        total=t['burst']['windowsSeconds'][window_index];arrival('main','burst',t['burst']['users'],total);workload='phase14-burst'
    elif case in ('H1','H2','H3'):
        total=t['hotspot']['windowSeconds'];n=t['hotspot']['users'];workload='phase14-hotspot'
        if case=='H3':
            scenarios['main']={'executor':'per-vu-iterations','exec':'hotspot','vus':n,'iterations':1,'maxDuration':f'{grace}s','gracefulStop':f'{grace}s'}
            mapping['main']={'count':n,'path':path,'sessionCount':1};plan['main']=n
        else:arrival('main','hotspot',n,total,path=path,sessionCount=session_count)
    elif case in ('L1','L2'):
        b=background(t,passed_u1 or [],passed_u2 or []);window=t['login']['windowsSeconds'][0 if case=='L1' else 1];warm=t['login']['backgroundWarmSeconds']
        total=warm+window+t['login']['backgroundRecoverySeconds'];workload='phase14-login-isolation'
        for name,fn,slice_name in [('refresh','refresh','background'),('hold','backgroundHold','backgroundHold'),('order','backgroundOrder','backgroundOrder')]:
            rate=Fraction(b[name]);arrival('background_'+name,fn,rate*total,total,users=b['users'],slice=slice_name)
        if not control_only:arrival('login','login',t['login']['users'],window,warm)
    else:
        b=background(t,passed_u1 or [],passed_u2 or []);total=t['soak']['seconds'];workload='phase14-online'
        scenarios['main']={'executor':'constant-vus','exec':'online','vus':b['users'],'duration':f'{total}s','gracefulStop':f'{grace}s'}
        mapping['main']={'users':b['users']};plan['main']=None
    for step in (() if case=='G0' else ('health','auth','availability')):
        arrival('control_'+step,'control',t['probes']['controlRate']*(total+t['recovery']['observeSeconds']),total+t['recovery']['observeSeconds'],step=step)
    if case in t['probes']['paymentScenarios']:
        arrival('payment','payment',t['probes']['paymentRate']*total,total)
    for name,m in mapping.items():
        if name=='payment' and m['count']>t['slices']['payment'][1]-t['slices']['payment'][0]:raise ValueError('payment pool exhausted before run')
    delivery_schedule=guard_delivery(scenarios,t)
    return {'version':3,'startupPlan':startup_plan(t,case,mapping),'deliverySchedule':delivery_schedule,'case':case,'mode':t['mode'],'targets':t,'runId':run_id,'idempotencyNamespace':run_id,
            'roundIndex':round_index,'windowIndex':window_index,'path':path,'sessionCount':session_count,
            'controlOnly':control_only,'scenarios':scenarios,'mapping':mapping,'plan':plan,'loadSeconds':total,'workload':workload}


def startup_plan(t,case,mapping):
    if case in ('U1','S1'):users=mapping['main']['users']
    elif case=='U2':users=sum(m['count'] for k,m in mapping.items() if k.startswith('enter_'))
    elif case=='J1':users=mapping['main']['count']
    else:users=0
    return {'users':users,'requests':users*t['pageStartup']['requestsPerUser'],
            'steps':{k:v*users for k,v in t['pageStartup']['stepCounts'].items()}}


def check_startup(summary,plan):
    """Same exact delivery contract in smoke and formal; never infer from latency."""
    rows=summary['counts'];observed={}
    for step,planned in {'startup':plan['users'],**plan['steps']}.items():
        a=sum(x['count'] for x in rows if x['metric']=='phase14_started' and x['tags'][1]==step)
        b=sum(x['count'] for x in rows if x['metric']=='phase14_results' and x['tags'][1]==step)
        observed[step]={'planned':planned,'started':a,'completed':b}
        if a!=planned or b!=planned:summary['errors'].append('startup delivery mismatch: '+step)
    summary['startupDelivery']=observed
    return observed


class Environment:
    def __init__(self,t,root,*,project='phase14-capacity'):
        self.t=t;self.root=Path(root);self.project=project;self.data=GENERATED/(t['mode']+'-v'+str(t['version']))
        if not PROJECT_RE.fullmatch(project):raise ValueError('invalid Phase14 project')
        self.env={k:os.environ[k] for k in ('PATH','SystemRoot','WINDIR','TEMP','TMP','USERPROFILE','HOME','DOCKER_HOST','DOCKER_CONTEXT','ProgramFiles','LOCALAPPDATA') if k in os.environ}
        self.env.update(PHASE14_PROJECT=project,PHASE14_PORT=str(t['environment']['localPort']),PHASE14_PROMETHEUS_PORT=str(t['environment']['prometheusPort']),PHASE14_DATA_ROOT=str(self.data.resolve()))
        self.base=f"http://127.0.0.1:{t['environment']['localPort']}"
        self.root.mkdir(parents=True,exist_ok=True)
    def command(self,args,*,input_file=None,output_file=None,check=True):
        with (self.root/'commands.jsonl').open('a',encoding='utf-8') as log:log.write(json.dumps({'at':utc_now(),'argv':args})+'\n')
        with open(input_file,'rb') if input_file else open(os.devnull,'rb') as source:
            result=subprocess.run(args,stdin=source,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=self.env,cwd=ROOT)
        if output_file:Path(output_file).write_bytes(result.stdout)
        if check and result.returncode:raise RuntimeError(f'command failed ({result.returncode}): {args[:3]}: '+result.stderr.decode('utf-8','replace')[:1000])
        return result
    def compose(self,*args,**kwargs):return self.command(['docker','compose','-p',self.project,'-f',str(COMPOSE),*args],**kwargs)
    def psql_popen(self):
        return subprocess.Popen(['docker','compose','-p',self.project,'-f',str(COMPOSE),
            'exec','-T','-e','PGAPPNAME=phase14_sampler','postgres','psql','-U','ticketing','-d','ticketing','-qAt',
            '--set=ON_ERROR_STOP=1'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            text=True,encoding='utf-8',env=self.env)
    def sql(self,query):
        # Pipe sensitive SQL through stdin; commands and query samples omit it.
        args=['docker','compose','-p',self.project,'-f',str(COMPOSE),'exec','-T','-e','PGAPPNAME=phase14_sampler','postgres','psql','-U','ticketing','-d','ticketing','--set=ON_ERROR_STOP=1','-At','-F','\t']
        result=subprocess.run(args,input=query.encode(),capture_output=True,env=self.env,cwd=ROOT,timeout=10)
        if result.returncode:raise RuntimeError('Phase14 database command failed: '+result.stderr.decode('utf-8','replace')[:800])
        return result.stdout.decode('utf-8').strip()
    def http(self,path,identity=None,*,method='GET',body=None):
        headers={'Content-Type':'application/json','Origin':'http://performance.local'}
        if identity:headers.update(Cookie=f"ticketing_session={identity['sessionToken']}; ticketing_csrf={identity['csrfToken']}",**{'X-CSRF-Token':identity['csrfToken']})
        request=Request(self.base+path,data=None if body is None else json.dumps(body).encode(),headers=headers,method=method)
        with build_opener(ProxyHandler({})).open(request,timeout=self.t['probes']['paymentDeadlineSeconds']) as response:return json.load(response)
    def validate(self):
        model=json.loads(self.compose('config','--format','json').stdout)
        volumes=guard_model(model,self.project,self.data,self.t)
        for name in volumes:
            result=self.command(['docker','volume','inspect',name],check=False)
            if result.returncode==0:
                labels=json.loads(result.stdout)[0].get('Labels') or {}
                if labels.get('com.docker.compose.project')!=self.project or labels.get('ticketing.phase14')!='capacity':raise ValueError('existing volume ownership mismatch')
        print(json.dumps({'project':self.project,'resolvedVolumes':volumes,'target':self.base}))
        return model
    def reset(self,*,yes=False,snapshot=None):
        self.validate()
        if not yes:return
        if snapshot:
            if snapshot.resolve()!= (self.data/'base.dump').resolve():raise ValueError('snapshot outside selected Phase14 dataset')
            if not snapshot.is_file() or sha256(snapshot)!=snapshot.with_suffix('.sha256').read_text().strip():raise ValueError('snapshot hash mismatch')
            manifest=json.loads((self.data/'dataset-manifest.json').read_text(encoding='utf-8'))
            if manifest['targetsSha256']!=self.t['sourceSha256']:raise ValueError('dataset targets mismatch before reset')
            for name,info in manifest['files'].items():
                if Path(name).name!=name or sha256(self.data/name)!=info['sha256']:raise ValueError('dataset source corruption before reset')
        # Preserve containers and volumes under the 2026-09-10 user constraint.
        # Stop only this already-validated Phase14 project's application clients.
        self.compose('stop','backend','postgres-exporter','redis-exporter','prometheus','noop')
        self.compose('up','-d','--wait','postgres','redis')
        if snapshot:
            self.compose('exec','-T','postgres','pg_restore','-U','ticketing','-d','ticketing','--clean','--if-exists','--exit-on-error',input_file=snapshot)
        else:
            self.compose('exec','-T','postgres','psql','-U','ticketing','-d','ticketing','--set=ON_ERROR_STOP=1',input_file=self.data/'dataset.sql')
        # Redis is dedicated to this validated project; retain the container and clear its state.
        self.compose('exec','-T','redis','redis-cli','FLUSHALL','SYNC')
        size=self.compose('exec','-T','redis','redis-cli','DBSIZE').stdout.strip()
        if size!=b'0':raise ValueError('Redis is not empty after reset')
        self.compose('up','-d','--wait','backend','postgres-exporter','redis-exporter','prometheus')
        self.http('/health')
    def invariants(self):
        result=parse_verifier_output(self.sql(DEFAULT_SQL_FILE.read_text(encoding='utf-8')))
        return {'passed':not any(result.values()),'global':result}
    def prepare(self):
        if not self.data.exists() or not (self.data/'dataset-manifest.json').exists():dataset.export_phase14(self.data,self.t,ROOT/'backend/config/config.phase14.json')
        manifest=json.loads((self.data/'dataset-manifest.json').read_text())
        if manifest['targetsSha256']!=self.t['sourceSha256']:raise ValueError('dataset target hash mismatch; use a new output directory')
        for name,info in manifest['files'].items():
            if sha256(self.data/name)!=info['sha256']:raise ValueError('dataset source corruption')
        self.reset(yes=True)
        checks=self.invariants();write(self.root/'correctness.json',checks)
        if not checks['passed']:raise RuntimeError('initial invariants failed')
        snapshot=self.data/'base.dump'
        self.compose('exec','-T','postgres','pg_dump','-U','ticketing','-d','ticketing','-Fc',output_file=snapshot)
        snapshot.with_suffix('.sha256').write_text(sha256(snapshot))
        return snapshot
    def warm(self,spec):
        sessions=json.loads((self.data/'sessions.json').read_text())
        n=self.t['burst']['users'];period=self.t['online']['rounds'][spec['roundIndex']][0]['rampSeconds']
        start=time.monotonic()
        for i in range(n):
            delay=start+i*period/n-time.monotonic()
            if delay>0:time.sleep(delay)
            if self.http('/auth/me',sessions[i])['id']!=sessions[i]['userId']:raise RuntimeError('warm auth mismatch')
        return sessions


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['plan','prepare','calibrate','run','campaign','qualify','preflight'])
    parser.add_argument('--topology-config',type=Path)
    parser.add_argument('--qualification',type=Path)
    parser.add_argument('--formal-approved',action='store_true')
    parser.add_argument('--g0-evidence',type=Path)
    parser.add_argument('--smoke-evidence',type=Path)
    parser.add_argument('--smoke',action='store_true');parser.add_argument('--yes',action='store_true')
    parser.add_argument('--resume-from',type=Path,help='Read-only smoke campaign checkpoint; retry first incomplete job in a new evidence directory')
    parser.add_argument('--case',default='U1');parser.add_argument('--round',type=int,default=0)
    parser.add_argument('--window',type=int,default=0);parser.add_argument('--path',choices=['formal','temporary'],default='formal')
    parser.add_argument('--session-count',type=int,default=1);parser.add_argument('--shards',type=int,default=1)
    args=parser.parse_args();t=load_targets(smoke=args.smoke)
    if args.topology_config:
        from phase14_campaign import dual_main
        return dual_main(args,t)
    if args.action in ('qualify','preflight'):raise ValueError('dual topology required')
    run_id='phase14-'+t['mode']+'-'+args.case.lower()+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(3)
    if args.action=='plan' or not args.yes:
        print(json.dumps({'mode':t['mode'],'targetsSha256':t['sourceSha256'],'segments':segments(args.shards,t),'onlinePlan':online_plan(t),'action':args.action,'dryRun':True},indent=2));return 0
    root=RESULTS/run_id;root.mkdir(parents=True);env=Environment(t,root)
    if args.action=='prepare':
        env.prepare();print('Prepared snapshot and data: '+str(env.data));return 0
    if args.action=='calibrate':
        env.reset(yes=True,snapshot=env.data/'base.dump')
        calibration(env);env.warm(build_spec(t,'U1',run_id))
        config=json.loads((ROOT/'backend/config/config.phase14.json').read_text(encoding='utf-8'))
        interval=config['custom_config']['authentication']['last_seen_write_interval_seconds']
        query=f"SELECT json_build_object('sessions',sum(n),'buckets',count(*),'minimumBucket',min(n),'maximumBucket',max(n)) FROM (SELECT floor(mod(extract(epoch from last_seen_at+make_interval(secs=>{interval})),{interval})) AS bucket,count(*) AS n FROM user_sessions WHERE user_id LIKE 'perf-user-%' GROUP BY 1) x;"
        write(root/'auth-writeback-dispersion.json',{'intervalSeconds':interval,'query':query,'afterWarm':json.loads(env.sql(query))})
        print('Cold/hot identity calibration and paced warmup complete: '+str(root));return 0
    return run_action(args,t,env)


def run_action(args,t,env):
    if args.action=='campaign':return campaign(args,t,env)
    return execute_case(args,t,env)


def calibration(env):
    sessions=json.loads((env.data/'sessions.json').read_text())
    a,b=env.t['slices']['calibration'];n=env.t['calibration']['authSamples']
    if n>b-a:raise ValueError('calibration slice too small')
    rows=[]
    for mode in ('cold','hot'):
        start=time.monotonic();durations=[]
        for index,item in enumerate(sessions[a:a+n]):
            begin=time.monotonic();identity=env.http('/auth/me',item)
            if identity.get('id')!=item['userId']:raise RuntimeError('cold/hot authentication mismatch')
            durations.append((time.monotonic()-begin)*1000)
            if (index+1)%100==0 or index+1==n:
                write(env.root/'auth-calibration-progress.json',{'mode':mode,'matched':index+1,'planned':n,'elapsedSeconds':time.monotonic()-start})
                print(f'Calibration {mode}: {index+1}/{n}',flush=True)
        rows.append({'mode':mode,'planned':n,'matched':len(durations),'seconds':time.monotonic()-start,'durationsMs':durations})
    interval=env.t['calibration']['baselineSeconds']
    sampler=Sampler(env);before=time.monotonic();samples=[]
    while time.monotonic()-before<interval:
        sample,pg,redis,raw=sampler.sample();samples.append(sample)
        (env.root/'metrics-calibration.prom').write_text(raw,encoding='utf-8')
    control_durations={key:[] for key in ('health','auth','availability')}
    chosen=seat(env.t['seatSlices']['control'][0],env.t)
    for i in range(int(interval*env.t['probes']['controlRate'])):
        cycle=time.monotonic()
        for step,path in [('health','/health'),('auth','/auth/me'),('availability','/sessions/'+chosen['sessionId']+'/seat-availability')]:
            begin=time.monotonic();env.http(path,sessions[a]);control_durations[step].append((time.monotonic()-begin)*1000)
        delay=1/env.t['probes']['controlRate']-(time.monotonic()-cycle)
        if delay>0:time.sleep(delay)
    baseline={'httpIdleMax':max(x['httpInflight'] for x in samples),'redisIdleMax':max(x['redisInflight'] for x in samples),
              'controlP95':{step:percentile(values,.95) for step,values in control_durations.items()}}
    result={'auth':rows,'idleSamples':samples,'baseline':baseline,'controlDurationsMs':control_durations,'formalReady':False,
            'limitations':['single shared Docker Desktop host; CPU isolation and physical network capacity not established']}
    if getattr(env,'dual',False) is True:
        result.update(formalReady=True,limitations=[])
    write(env.root/'calibration.json',result)
    return result


def save_sample(root,sample,pg,redis):
    folder=root/'samples';folder.mkdir(exist_ok=True)
    for filename,value in [('host-and-container',sample),('postgres',pg),('redis',{'time':sample['time'],'info':redis})]:
        with (folder/(filename+'.jsonl')).open('a',encoding='utf-8') as f:f.write(json.dumps(value)+'\n')


def resource_preflight(cal,t):
    samples=cal.get('idleSamples',[]);errors=[];warnings=[]
    if len(samples)<2:errors.append('insufficient fresh idle samples')
    for x in samples:
        reason,warning=swap_policy(x,t)
        if reason:errors.append(reason)
        if warning:warnings.append(warning)
        for key in ('oom','restarted','unhealthy','networkExhausted','fdExhausted'):
            if x[key]:errors.append(key)
        if x['memoryFraction']>=t['stop']['memoryFraction']:errors.append('SUT memory limit')
        if abs(x['clockSkewMs'])>t['generator']['maxClockSkewMs']:errors.append('clock skew')
    return {'passed':not errors,'errors':sorted(set(errors)),'warnings':warnings,'samples':len(samples),'formalIsolationEstablished':cal.get('formalReady',False)}


class RawProgress:
    """Tail each shard once; bounded window totals avoid rescanning large raw files."""
    def __init__(self,t):
        self.t=t;self.offsets={};self.counts={};self.dropped=0;self.guard=StopGuard(t);self.last=None;self.bad=False
    def read(self,root,now=None):
        now=time.time() if now is None else now
        for path in (Path(root)/'shards').glob('*/raw.json'):
            with path.open(encoding='utf-8') as stream:
                stream.seek(self.offsets.get(path,0))
                while True:
                    position=stream.tell();line=stream.readline()
                    if not line or not line.endswith('\n'):
                        self.offsets[path]=position;break
                    item=json.loads(line)
                    if item.get('type')!='Point':continue
                    if item['metric']=='dropped_iterations':self.dropped+=item['data']['value']
                    if item['metric']!='phase14_results':continue
                    data=item['data'];bucket=int(timestamp(data['time'])//self.t['stop']['windowSeconds'])
                    pair=self.counts.setdefault(bucket,[0,0]);pair[0]+=data['value']
                    if data['tags']['result'] in ('system_error','unexpected_contract'):
                        pair[1]+=data['value']
                        if smoke_policy(self.t) and data['value']>0:self.bad=True
        end=int(now//self.t['stop']['windowSeconds'])-1
        begin=self.last+1 if self.last is not None else min(self.counts,default=end+1)
        for bucket in range(begin,end+1):
            self.bad=self.guard.error_window(*self.counts.pop(bucket,[0,0])) or self.bad
            self.last=bucket
        return self.bad,self.dropped


def execute_case(args,t,env,*,spec_factory=build_spec):
    if getattr(env,'dual',False) is True and args.case=='G0':
        from phase14_campaign import run_g0
        return run_g0(args,t,env)
    if args.case=='E1':return execute_expiry(t,env)
    root=env.root;run_id=root.name;snapshot=env.data/'base.dump'
    if not snapshot.is_file():raise ValueError('prepare the matching dataset snapshot first')
    spec=spec_factory(t,args.case,run_id,round_index=args.round,window_index=args.window,path=args.path,session_count=args.session_count,
                    control_only=getattr(args,'control_only',False),passed_u1=getattr(args,'passed_u1',[]),passed_u2=getattr(args,'passed_u2',[]))
    if args.shards*2>t['generator']['maxShards']:raise ValueError('main and probe shards exceed fixed label budget')
    base_segments=segments(args.shards,t)
    env.reset(yes=True,snapshot=snapshot)
    slices=[{**s,'role':'main'} for s in base_segments]
    if args.case!='G0':slices += [{**s,'shard':str(int(s['shard'])+args.shards),'role':'probe'} for s in base_segments]
    spec['shards']=slices
    cal=calibration(env)
    preflight=resource_preflight(cal,t);write(root/'resource-preflight.json',preflight)
    if not preflight['passed']:raise RuntimeError('resource preflight failed: '+', '.join(preflight['errors']))
    sessions=env.warm(spec)
    if args.case in ('L1','L2'):
        from phase14_startup import warm_background
        warm_background(env,spec)
    if args.case=='G0':env.compose('up','-d','noop')
    # Isolated sentinel hold for mixed-load display correctness.
    sentinel=seat(t['seatSlices']['control'][0],t)
    owner=sessions[t['slices']['control'][0]]
    hold=env.http('/checkout-sessions',owner,method='POST',body={'sessionId':sentinel['sessionId'],'seatIds':[sentinel['sessionSeatId']]})
    spec['sentinel']={**sentinel,'checkoutId':hold['id']}
    ttl=json.loads((ROOT/'backend/config/config.phase14.json').read_text(encoding='utf-8'))['custom_config']['checkout_seat_hold']['ttl_seconds']
    sentinel_refresh=time.time()+ttl/2;owners_captured=False
    if args.case=='O1':
        for i in range(t['dataset']['events']*t['dataset']['sessionsPerEvent']):
            chosen=seat(i,t);s=env.http('/sessions/'+chosen['sessionId']);env.http('/events/'+s['eventId'])
            for endpoint in ('seat-layout','seat-availability'):
                page=env.http('/sessions/'+chosen['sessionId']+'/'+endpoint)
                if len(page['seats'])!=t['dataset']['seatsPerSession']:raise ValueError('O1 page fixture mismatch')
    before=pg_snapshot(env);write(root/'postgres-before.json',before)
    shutil.copytree(ROOT/'performance/k6',root/'k6-source')
    source_compose=root/'compose-k6-source.json'
    write(source_compose,{'services':{'k6':{'volumes':[{'type':'bind','source':str((root/'k6-source').resolve()),'target':'/scripts','read_only':True}]}}})
    for folder in ('scripts','verification'):
        shutil.copytree(ROOT/'performance'/folder,root/'source'/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    original=(ROOT/'performance/baseline/phase14-targets.json').read_bytes();(root/'phase14-targets.json').write_bytes(original)
    (root/'phase14-targets.json.sha256').write_text(sha256(root/'phase14-targets.json'))
    shutil.copyfile(env.data/'dataset-manifest.json',root/'dataset-manifest.json')
    git_head=env.command(['git','rev-parse','HEAD']).stdout.decode().strip();dirty=env.command(['git','status','--short']).stdout.decode()
    env.command(['git','diff','HEAD','--binary'],output_file=root/'worktree.patch')
    write(root/'environment.json',{'target':'SUT-private' if getattr(env,'dual',False) is True else env.base,'project':env.project,'k6Image':K6_IMAGE,'isolation':'dual' if getattr(env,'dual',False) is True else 'local_characterization_only','calibrationLimitations':cal['limitations']})
    env.env['LOGIN_PASSWORD']='Ticketing123!' # Existing synthetic fixture hash, never exported into evidence.
    processes=[];logs=[];stop_reasons=[];samples=[];sampler=Sampler(env);guard=StopGuard(t,login_protection=args.case in ('L1','L2'))
    started=time.time();progress=RawProgress(t)
    light=LightPostgresSampler(env,t['generator']['hotspotSampleSeconds'] if args.case=='H3' else t['generator']['sampleSeconds']).start()
    started=time.time()
    spec['releaseAtMs']=int((started+t['generator']['releaseLeadSeconds'])*1000)
    write(root/'spec.json',spec)
    write(root/'manifest.json',{'version':1,'runId':run_id,'gitHead':git_head,'worktree':dirty,'mode':t['mode'],'shards':slices,'targetsSha256':t['sourceSha256'],'snapshotSha256':sha256(snapshot),'start':utc_now(),'releaseAtMs':spec['releaseAtMs'],'idempotencyNamespace':spec['idempotencyNamespace']})
    def observe_initialization():
        x,pg,rd,_=sampler.sample();samples.append(x);save_sample(root,x,pg,rd)
        bad,dropped=progress.read(root);x['dropped']=dropped;stop_reasons.extend(guard.sample(x))
        if bad:stop_reasons.append('error stop window')
        if stop_reasons:raise RuntimeError('initialization safety stop')
    try:
        from phase14_initialization import Initialization
        initialize=(Initialization(root,run_id,[s['shard'] for s in slices],spec['releaseAtMs'],observe_initialization,serial=t['mode']=='formal')
                    if getattr(env,'dual',False) is True else nullcontext())
        with initialize as initialization:
            for shard_info in slices:
                number=shard_info['shard'];folder=root/'shards'/number;folder.mkdir(parents=True)
                log=(folder/'console.log').open('wb');logs.append(log)
                args_k6=['docker','compose','-p',env.project,'-f',str(COMPOSE),'-f',str(source_compose.resolve()),'run','--no-deps','--name',f'{env.project}-k6-{run_id}-{number}',
                         '-e',f'SHARD={number}','-e',f'PHASE14_ROLE={shard_info["role"]}','-e',f'PHASE14_SPEC=/results/{run_id}/spec.json',
                         '-e',f'BASE_URL={"http://noop:8080" if args.case=="G0" else "http://backend:8080"}','-e','LOGIN_PASSWORD','k6','run',
                         '--execution-segment',shard_info['segment'],'--execution-segment-sequence',shard_info['sequence'],
                         '--out',f'json=/results/{run_id}/shards/{number}/raw.json',f'workloads/{spec["workload"]}.js']
                if getattr(env,'dual',False) is True:
                    processes.append(env.start_generator(args_k6,log))
                    initialization.register(processes[-1],log,number)
                else:
                    with (root/'commands.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'at':utc_now(),'argv':args_k6})+'\n')
                    processes.append(subprocess.Popen(args_k6,stdout=log,stderr=subprocess.STDOUT,env=env.env,cwd=ROOT))
            if initialization is not None:initialization.finish()
        deadline=started+t['generator']['releaseLeadSeconds']+spec['loadSeconds']+t['recovery']['observeSeconds']+t['probes']['paymentDeadlineSeconds']+max(t['behavior']['refreshSeconds'])+t['generator']['scheduler_delivery_guard_seconds']+30
        while any(p.poll() is None for p in processes):
            x,pg,rd,raw=sampler.sample();samples.append(x);save_sample(root,x,pg,rd)
            if time.time()>=sentinel_refresh:
                hold=env.http('/checkout-sessions/'+hold['id']+'/seats',owner,method='PUT',body={'seatIds':[sentinel['sessionSeatId']],'expectedRevision':hold['revision']})
                sentinel_refresh=time.time()+ttl/2
            if not owners_captured and args.case in ('H1','H3') and args.path=='temporary' and all(p.poll() is not None for s,p in zip(slices,processes) if s['role']=='main'):
                write(root/'temporary-owners.json',capture_temporary_owners(env,spec));owners_captured=True
            bad,dropped=progress.read(root);x['dropped']=dropped
            stop_reasons+=guard.sample(x)
            if bad:stop_reasons.append('error stop window')
            if time.time()>deadline:stop_reasons.append('run deadline exceeded')
            if stop_reasons:break
        if stop_reasons and getattr(env,'dual',False) is True:
            env.stop_generators()
        elif stop_reasons:
            names=[f'{env.project}-k6-{run_id}-{s["shard"]}' for s in slices]
            for name in names:
                inspected=json.loads(env.command(['docker','inspect',name]).stdout)[0]
                if inspected['Config']['Labels'].get('com.docker.compose.project')!=env.project:raise ValueError('stop target ownership mismatch')
            env.command(['docker','stop','--time','2',*names])
        for process in processes:
            code=process.wait(timeout=30)
            if code:stop_reasons.append('k6 exit '+str(code))
    except Exception as error:
        stop_reasons.append(type(error).__name__+': '+str(error))
    finally:
        if getattr(env,'dual',False) is True:
            env.stop_generators()
        for info,process in zip(slices,processes):
            if getattr(env,'dual',False) is True:
                process.wait(timeout=30)
                continue
            if process.poll() is None:
                name=f'{env.project}-k6-{run_id}-{info["shard"]}'
                inspected=env.command(['docker','inspect',name],check=False)
                if inspected.returncode==0 and json.loads(inspected.stdout)[0]['Config']['Labels'].get('com.docker.compose.project')==env.project:
                    env.command(['docker','stop','--time','2',name],check=False)
                    process.wait(timeout=30)
        for log in logs:log.close()
        light_summary=light.stop();write(root/'postgres-light-summary.json',light_summary)
        stop_reasons += light_summary['errors']
    if not owners_captured and args.case in ('H1','H3') and args.path=='temporary':
        write(root/'temporary-owners.json',capture_temporary_owners(env,spec))
    return finish_case(env,spec,slices,stop_reasons,samples,cal,before,started,preflight['warnings']+guard.warnings)


def finish_case(env,spec,slices,stop_reasons,samples,cal,before,started,warnings=None):
    root=env.root;run_id=root.name;t=env.t
    warnings=warnings or [];write(root/'warnings.json',warnings)
    for info in slices:
        folder=root/'shards'/info['shard'];raw=folder/'raw.json'
        if not raw.exists():raise RuntimeError('missing raw shard; see console.log')
        with raw.open('rb') as source,gzip.open(folder/'raw.json.gz','wb') as destination:shutil.copyfileobj(source,destination)
        (folder/'raw.json.gz.sha256').write_text(sha256(folder/'raw.json.gz'))
    summary=aggregate(root,slices,spec['plan']);summary['stopReasons']=stop_reasons
    check_startup(summary,spec.get('startupPlan',{'users':0,'steps':{}}))
    summary['businessWindows']={name:{'seconds':spec['deliverySchedule'].get(name,{}).get('businessWindowSeconds',spec['loadSeconds']),
        'completedIterationsPerSecond':row['completed']/spec['deliverySchedule'].get(name,{}).get('businessWindowSeconds',spec['loadSeconds'])}
        for name,row in summary['delivery'].items()}
    write(root/'global-summary.json',summary)
    correctness=verify_run(env,spec,summary);write(root/'correctness.json',correctness)
    after=pg_snapshot(env);write(root/'postgres-after.json',after);write(root/'postgres-delta.json',pg_delta(before,after))
    controls=[]
    for info in slices:
        with gzip.open(root/'shards'/info['shard']/'raw.json.gz','rt',encoding='utf-8') as stream:
            for line in stream:
                item=json.loads(line)
                if item.get('type')=='Point' and item['metric']=='phase14_duration_ms':
                    point=item['data'];tags=point['tags']
                    if tags.get('scenario','').startswith('control_'):
                        controls.append({'time':timestamp(point['time']),'ms':point['value'],'step':tags['step'],'result':tags['result']})
    recovered=recovery(samples,controls,cal['baseline'],t,spec['releaseAtMs']/1000+spec['loadSeconds'])
    recovered['mode']=t['mode']
    write(root/'recovery.json',{'status':'not_applicable','diagnostic':recovered} if t['mode']=='smoke' else recovered)
    validity={'isolated':getattr(env,'dual',False) is True,'errors':stop_reasons,'warnings':warnings}
    if getattr(env,'dual',False) is True:
        from phase14_campaign import sample_errors
        validity['errors'] += sample_errors(samples,t)
        if not pg_delta(before,after)['valid']:validity['errors'] += ['PostgreSQL delta invalid']
    if spec['case']=='H3':
        offsets=[x for x in summary['trends'] if x['metric']=='phase14_start_offset_ms']
        concentrated=bool(offsets) and sum(x['count'] for x in offsets)==t['hotspot']['users'] and all(x['p95']<=t['hotspot']['h3P95OffsetSeconds']*1000 and x['max']<=t['hotspot']['h3MaxOffsetSeconds']*1000 for x in offsets)
        write(root/'start-concentration.json',{'passed':concentrated,'offsets':offsets})
        if not concentrated:validity['errors']=stop_reasons+['H3 start offsets exceed frozen concentration limits']
    result=verdict(summary,correctness,recovered,validity,t,overload=spec['case'].startswith(('H','L')),smoke=t['mode']=='smoke')
    write(root/'verdict.json',result)
    collect_prometheus(env,started,time.time())
    functional=not validity['errors'] and not summary['errors'] and correctness['passed'] and not any(x['metric']=='phase14_results' and x['tags'][2] in ('system_error','unexpected_contract') and x['count'] for x in summary['counts'])
    write(root/'smoke-check.json',{'passed':functional,'notCapacityEvidence':True})
    statement='双机测量；容量结论仅以本轮有效性和业务判定为准。' if getattr(env,'dual',False) is True and t['mode']=='formal' else '本次仅为功能预演，不构成万人正式容量证明。'
    (root/'report.md').write_text(f'# Phase14 {spec["case"]} {t["mode"]}\n\n{statement}\n\nFunctional smoke: {functional}\n\n```json\n'+json.dumps({'businessWindowSeconds':spec['loadSeconds'],'nonBusinessDeliverySchedule':spec['deliverySchedule'],'delivery':summary['delivery'],'dropped':summary['dropped'],'verdict':result,'correctness':correctness['passed']},ensure_ascii=False,indent=2)+'\n```\n',encoding='utf-8')
    print(json.dumps({'runId':run_id,'functionalSmoke':functional,'correctness':correctness['passed'],'stopReasons':stop_reasons,'deliveryErrors':summary['errors']},ensure_ascii=False))
    return 0 if functional else 1


def collect_prometheus(env,start,end):
    from urllib.parse import urlencode
    query={'start':start,'end':end,'step':str(env.t['generator']['sampleSeconds'])}
    records=[]
    for expression in ('ticketing_db_transaction_acquire_in_flight','ticketing_flow_requests_in_flight','ticketing_redis_operations_in_flight','ticketing_main_event_loop_lag_seconds','pg_order_expiry_pending'):
        url=f'http://127.0.0.1:{env.t["environment"]["prometheusPort"]}/api/v1/query_range?'+urlencode({**query,'query':expression})
        try:
            if getattr(env,'dual',False) is True:payload=env.prometheus('/api/v1/query_range?'+urlencode({**query,'query':expression}))
            else:
                with build_opener(ProxyHandler({})).open(url,timeout=20) as response:payload=json.load(response)
        except OSError as error:payload={'status':'not_available','reason':str(error)}
        records.append({**query,'expression':expression,'response':payload})
    write(env.root/'prometheus-queries.json',records)


def campaign(args,t,env):
    if t['mode']!='smoke':
        write(env.root/'campaign.json',{'status':'not_run','reason':'Dedicated local containers share CPU cores with generators; formal isolation is not established.'})
        raise ValueError('formal capacity campaign requires proven isolation; use --smoke for engineering validation')
    jobs=[('G0',{}),('U1',{'round':0}),('U1',{'round':1}),('U2',{'round':0}),('U2',{'round':1})]
    jobs += [(case,{'window':window}) for case in ('J1','O1') for window in range(len(t['burst']['windowsSeconds']))]
    jobs += [('E1',{})]
    jobs += [('H1',{'path':path}) for path in ('temporary','formal') for repeat in range(t['hotspot']['h1Repeats'])]
    jobs += [('H2',{'session_count':n}) for n in t['hotspot']['h2SessionCounts']]
    jobs += [('H3',{'path':path}) for path in ('temporary','formal')]
    jobs += [(case,{'control_only':control}) for case in ('L1','L2') for control in (True,False)]
    jobs += [('S1',{})]
    records=[];passed={'U1':[],'U2':[]};controls={}
    resume=getattr(args,'resume_from',None)
    if resume:
        prior=json.loads(resume.read_text(encoding='utf-8'))
        if prior.get('mode')!='smoke' or prior.get('formalCapacity') is not False:raise ValueError('not a smoke checkpoint')
        for record in prior['runs']:
            if not record['functionalSmoke']:break
            i=len(records)
            if record['index']!=i or (record['case'],record['arguments'])!=jobs[i]:raise ValueError('checkpoint job differs')
            old=RESULTS/record['runId']
            check=json.loads((old/'smoke-check.json').read_text(encoding='utf-8'))
            manifest=json.loads((old/'manifest.json').read_text(encoding='utf-8'))
            if not check['passed']:raise ValueError('checkpoint evidence invalid')
            if manifest['targetsSha256']!=t['sourceSha256']:
                previous=json.loads((old/'phase14-targets.json').read_text(encoding='utf-8'))
                current=json.loads((ROOT/'performance/baseline/phase14-targets.json').read_text(encoding='utf-8'))
                previous.pop('version');current.pop('version');current['generator'].pop('scheduler_delivery_guard_seconds')
                if previous!=current:raise ValueError('checkpoint business configuration differs')
            records.append(record)
            if record['case'] in passed:passed[record['case']]=[t['burst']['users']]
            if record['case'] in ('L1','L2') and record['arguments'].get('control_only'):controls[record['case']]=old
    for index,(case,overrides) in enumerate(jobs):
        if index<len(records):continue
        job=argparse.Namespace(**vars(args));job.case=case
        for key,value in overrides.items():setattr(job,key,value)
        job.passed_u1=passed['U1'];job.passed_u2=passed['U2']
        run_id=f'phase14-smoke-{case.lower()}-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(3)
        child=Environment(t,RESULTS/run_id,project=env.project)
        code=execute_case(job,t,child)
        if case in ('L1','L2'):
            if job.control_only:controls[case]=child.root
            elif code==0:
                write(child.root/'login-background-comparison.json',compare_background(controls[case],child.root,t))
        records.append({'index':index,'case':case,'arguments':overrides,'runId':run_id,'functionalSmoke':code==0})
        write(env.root/'campaign.json',{'mode':'smoke','formalCapacity':False,'runs':records})
        if code:return code  # Retain the first failure; never average or retry it away.
        if case in passed:passed[case]=[t['burst']['users']]
    return 0


def compare_background(control_root,load_root,t):
    """Compare identical background input during the same relative login window."""
    def window(root):
        spec=json.loads((root/'spec.json').read_text(encoding='utf-8'))
        begin=spec['releaseAtMs']/1000+t['login']['backgroundWarmSeconds']
        seconds=t['login']['windowsSeconds'][0 if spec['case']=='L1' else 1]
        stamp=lambda x:datetime.fromtimestamp(x,timezone.utc).isoformat().replace('+00:00','Z')
        data=aggregate(root,spec['shards'],{k:None for k in spec['plan']},start=stamp(begin),end=stamp(begin+seconds))
        write(root/'login-window-summary.json',data)
        return data,spec,seconds
    base,a,seconds=window(Path(control_root));loaded,b,_=window(Path(load_root))
    if any(a['mapping'][k]!=b['mapping'][k] for k in a['mapping'] if k.startswith('background_')):raise ValueError('background control input differs')
    comparisons=[]
    for scenario,step in [('background_refresh','availability'),('background_hold','journey'),('background_order','journey')]:
        def row(summary):
            return next((x for x in summary['trends'] if x['metric']=='phase14_duration_ms' and x['tags']==[scenario,step,'business_success']),None)
        left,right=row(base),row(loaded)
        passed=bool(left and right and right['count']>=left['count']*t['login']['backgroundGoodputFraction'] and right['p95']<=left['p95']*t['login']['backgroundLatencyRatio'])
        comparisons.append({'scenario':scenario,'passed':passed,'control':left,'login':right,'seconds':seconds,'p95Ratio':right['p95']/left['p95'] if left and right and left['p95'] else None})
    return {'status':'not_applicable' if t['mode']=='smoke' else 'pass' if all(x['passed'] for x in comparisons) else 'fail',
            'diagnostic':{'passed':all(x['passed'] for x in comparisons),'comparisons':comparisons},
            **({'passed':all(x['passed'] for x in comparisons)} if t['mode']!='smoke' else {}),'mode':t['mode'],'notFormalCapacityEvidence':t['mode']=='smoke',
            'controlRunId':Path(control_root).name,'loginRunId':Path(load_root).name,'comparisons':comparisons}


def execute_expiry(t,env):
    """A legal future-dated fixture, observed without changing worker parameters."""
    root=env.root;snapshot=env.data/'base.dump'
    env.reset(yes=True,snapshot=snapshot)
    before=pg_snapshot(env);write(root/'postgres-before.json',before)
    write(root/'fixture-correctness.json',expiry_fixture(env,t,root.name))
    scope="id LIKE '"+root.name+"-o-%'"
    expiry=float(env.sql(f'SELECT extract(epoch from min(expires_at)) FROM orders WHERE {scope};'))
    explain=env.sql("EXPLAIN (FORMAT JSON) SELECT count(*), min(expires_at) FROM orders WHERE status='PENDING_PAYMENT' AND expires_at<=clock_timestamp();")
    write(root/'expiry-query-plan.json',json.loads(explain))
    sampler=Sampler(env);samples=[];drained=None;guard=StopGuard(t);reasons=[]
    while time.time()<=expiry+t['expiry']['maxObserveSeconds']:
        sample,pg,rd,raw=sampler.sample();save_sample(root,sample,pg,rd)
        counts=json.loads(env.sql(f"""SELECT json_build_object('time',extract(epoch from clock_timestamp()),
          'pending',count(*) FILTER(WHERE status='PENDING_PAYMENT'),
          'expired',count(*) FILTER(WHERE status='EXPIRED'),
          'oldestSeconds',COALESCE(extract(epoch from clock_timestamp()-min(expires_at) FILTER(WHERE status='PENDING_PAYMENT' AND expires_at<=clock_timestamp())),0))
          FROM orders WHERE {scope};"""))
        samples.append(counts)
        reasons+=guard.sample(sample)
        if reasons:break
        if counts['time']>=expiry and counts['pending']==0 and drained is None:drained=counts['time']
        if drained is not None and counts['time']>=drained+t['expiry']['afterDrainSeconds']:break
    checks=env.invariants()
    bad=int(env.sql(f"""SELECT count(*) FROM orders o JOIN reservations r ON r.id=o.reservation_id WHERE o.{scope} AND
      ((o.status='EXPIRED' AND (r.status<>'EXPIRED' OR
        EXISTS(SELECT 1 FROM session_seats s WHERE s.current_reservation_id=r.id) OR
        (SELECT count(*) FROM user_notifications n WHERE n.order_id=o.id AND n.type='ORDER_EXPIRED')<>1)) OR
       (SELECT count(*) FROM user_notifications n WHERE n.order_id=o.id AND n.type='ORDER_CREATED')<>1);"""))
    checks['expiryStateMismatches']=bad;checks['passed']=checks['passed'] and bad==0
    write(root/'correctness.json',checks)
    after=pg_snapshot(env);write(root/'postgres-after.json',after);write(root/'postgres-delta.json',pg_delta(before,after))
    final=samples[-1];elapsed=max(final['time']-expiry,0)
    functional=checks['passed'] and not reasons and (final['pending']==0 or (getattr(env,'dual',False) is True and t['mode']=='formal'))
    result={'mode':t['mode'],'fixtureCount':t['expiry']['orders'],'samples':samples,'stopReasons':reasons,
            'drainSeconds':None if drained is None else drained-expiry,'remaining':final['pending'],
            'effectiveExpiryPerSecond':final['expired']/elapsed if elapsed else None,'functionalSmoke':functional,
            'warnings':guard.warnings,
            'measurement_validity':{'status':'fail','reasons':['local_characterization_only']+sorted({x['code'] for x in guard.warnings})},
            'capacity':{'status':'not_applicable'},'overload_protection':{'status':'not_applicable'}}
    write(root/'expiry.json',result);write(root/'verdict.json',{key:result[key] for key in ('measurement_validity','capacity','overload_protection')})
    if getattr(env,'dual',False) is True:
        result['measurement_validity']={'status':'pass' if not reasons else 'fail','reasons':reasons}
        result['characterization']={'status':'complete' if functional else 'fail','remaining':final['pending']}
        write(root/'expiry.json',result);write(root/'verdict.json',{key:result[key] for key in ('measurement_validity','capacity','overload_protection','characterization')})
        collect_prometheus(env,expiry-t['expiry']['futureSeconds'],time.time())
    write(root/'smoke-check.json',{'passed':functional,'notCapacityEvidence':True})
    write(root/'manifest.json',{'runId':root.name,'case':'E1','mode':t['mode'],'snapshotSha256':sha256(snapshot),'targetsSha256':t['sourceSha256'],'expiryUtcSeconds':expiry})
    print(json.dumps({'runId':root.name,'functionalSmoke':functional,'drainSeconds':result['drainSeconds'],'remaining':result['remaining'],'stopReasons':reasons}))
    return 0 if functional else 1


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,RuntimeError,OSError) as error:print('[FAIL] '+str(error),file=sys.stderr);raise SystemExit(1)
