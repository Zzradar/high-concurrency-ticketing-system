"""One traceable load point. Retain failed points; never silently lower a requested rate."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import subprocess
import threading
import time

from harness import Stack, HERE, run, save, sha, request
from calibrate import sample
from resource_gate import stop_reason
from propagation import collect as collect_propagation


def distribution(values):
    values = sorted(values)
    if not values:
        return {'samples':0,'p50':None,'p95':None,'p99':None,'max':None}
    return {'samples':len(values), **{name:values[max(0,math.ceil(len(values)*q)-1)] for name,q in [('p50',.5),('p95',.95),('p99',.99)]},'max':values[-1]}


def aggregate(path):
    durations, counts = defaultdict(list), defaultdict(float)
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            point = json.loads(line)
            if point.get('type')!='Point':
                continue
            metric, data = point['metric'], point['data']
            tags = data.get('tags') or {}
            if metric=='http_req_duration':
                key = '|'.join([tags.get('name',''),tags.get('phase',''),tags.get('status','')])
                durations[key].append(data['value'])
            if metric in ['http_reqs','phase19_http_started','phase19_started','phase19_completed','phase19_flows','phase19_write_requests','phase19_sync','phase19_cursor_advances','phase19_errors','phase19_hot_outcomes','phase19_hot_winners']:
                key = metric+'|'+json.dumps(tags,sort_keys=True,separators=(',',':'))
                counts[key] += data['value']
    return {'httpDurationMs':{key:distribution(values) for key,values in durations.items()},'counts':dict(counts)}


def inventory_delta(before,after):
    formal=after['formalVersionSum']-before['formalVersionSum']
    projected=after['projectedFormalVersionSum']-before['projectedFormalVersionSum']
    entries=sum(v['entries-added'] for v in after['streams'].values())-sum(v['entries-added'] for v in before['streams'].values())
    return {'formalGenerated':formal,'formalProjected':projected,'allStreamEntriesAdded':entries,
        'temporaryVisibleEntriesAdded':entries-projected,
        'streamEntriesBySessionZone':{key:value['entries-added']-before['streams'][key]['entries-added'] for key,value in after['streams'].items()},
        'generationsUnchanged':bool(before['generations'] and all(before['generations'].values()) and after['generations']==before['generations']),
        'scope':'entire point including drain and separately logged cleanup; not just observe window'}


def accounting(aggregate,mode,duration,read_rate,transition_rate,journey_rate,warmup=0,bootstrap_vus=0):
    started,completed,scenarios=defaultdict(int),defaultdict(int),defaultdict(int)
    for key,value in aggregate['counts'].items():
        metric,raw=key.split('|',1)
        tags=json.loads(raw)
        if metric=='phase19_started':
            started[tags['kind']]+=int(value)
            scenarios[tags.get('scenario','')]+=int(value)
        elif metric=='phase19_completed':completed[tags['kind']]+=int(value)
    errors=[]
    if dict(started)!=dict(completed):errors.append('business kinds did not conserve started/completed')
    planned={}
    if mode=='open':
        planned={'readerIterationsNominal':(duration-warmup)*read_rate,'writerFlowsNominal':(duration-warmup)*transition_rate*5/14,'bootstrapSnapshots':bootstrap_vus if warmup else 0}
        if started.get('bootstrap',0)!=planned['bootstrapSnapshots']:errors.append('per-VU bootstrap count differs from plan')
        for i in range(10):
            n=scenarios.get('readers'+str(i),0)
            if not planned['readerIterationsNominal']/10<=n<=planned['readerIterationsNominal']/10+1:errors.append('reader arrival stream '+str(i)+' differs from plan')
        n=scenarios.get('writers',0)
        if not math.ceil(planned['writerFlowsNominal'])<=n<=math.floor(planned['writerFlowsNominal'])+1:errors.append('writer arrival differs from plan')
        expected=defaultdict(int)
        for i in range(n):expected['abandon' if i%10<5 else 'adjust' if i%10<7 else 'cancel' if i%10<9 else 'expiry']+=1
        if any(started.get(kind,0)!=number for kind,number in expected.items()):errors.append('writer mix differs from deterministic schedule')
    if mode=='journeys':
        n=sum(started.values());planned={'journeysNominal':duration*journey_rate}
        expected=defaultdict(int)
        for i in range(n):expected['journey_'+('browse' if i%100<75 else 'hold' if i%100<90 else 'order_cancel' if i%100<98 else 'hotspot')]+=1
        if dict(expected)!=dict(started):errors.append('journey classes differ from deterministic schedule')
    return {'planned':planned,'startedByKind':dict(started),'completedByKind':dict(completed),'startedByScenario':dict(scenarios),'errors':errors,
        'boundaryRule':'retain nominal plan; constant arrival can schedule one additional boundary iteration per stream'}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--private',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--mode',choices=['closed','open','hotspot','journeys'],required=True)
    parser.add_argument('--vus',type=int,default=100)
    parser.add_argument('--seconds',type=int,default=120)
    parser.add_argument('--warmup',type=int,default=30)
    parser.add_argument('--read-rate',type=int,default=50)
    parser.add_argument('--transitions-rate',type=int,default=5)
    parser.add_argument('--reader-vus',type=int,default=100)
    parser.add_argument('--writer-vus',type=int,default=100)
    parser.add_argument('--journey-rate',type=int,default=20)
    parser.add_argument('--propagation-cycles',type=int,default=0)
    parser.add_argument('--generator-memory-gib',type=int,choices=[2,4],default=2)
    parser.add_argument('--diagnostic',action='store_true')
    args=parser.parse_args()
    stack=Stack(args.private)
    out=args.out.resolve()
    if out.exists():raise ValueError('Refuse overwriting a run')
    out.mkdir(parents=True)
    if not args.diagnostic:
        frozen=json.loads((HERE.parent/'protocol-sha256.json').read_text())
        current={p.name:sha(p) for p in HERE.iterdir() if p.is_file()}
        if frozen['files']!=current:raise ValueError('Formal protocol drift')
        requested=args.reader_vus+args.writer_vus if args.mode=='open' else args.vus
        if args.generator_memory_gib!=frozen['generatorMemoryGiB'] or requested>max(map(int,frozen['qualification'])):
            raise ValueError('Formal generator resource/VU identity is not qualified')
    before=stack.verify();save(out/'verifier-before.json',before)
    if not before['passed']:raise RuntimeError('Pre-run invariants')
    inventory_before=stack.inventory_counters();save(out/'inventory-before.json',inventory_before)
    name=stack.prefix+'-load-'+out.name
    if len(name)>100:raise ValueError('Run name too long')
    duration=args.seconds+args.warmup
    save(out/'identity.json',{'startedUtc':datetime.now(timezone.utc).isoformat(),'diagnostic':args.diagnostic,
        'stack':stack.config,'runtimeConfigSha256':sha(stack.private/'api-config.json'),
        'protocolSha256':{p.name:sha(p) for p in HERE.iterdir() if p.is_file()},
        'model':args.mode,'actualVUsRequested':args.vus if args.mode!='open' else args.reader_vus+args.writer_vus,
        'warmupSeconds':args.warmup,'observeSeconds':args.seconds,'targetDeltaIterationsPerSecond':args.read_rate if args.mode=='open' else None,
        'targetStateTransitionsPerSecond':args.transitions_rate if args.mode=='open' else None,
        'plannedReadIterationsTotal':args.seconds*args.read_rate if args.mode=='open' else None,
        'bootstrapSnapshotsPlanned':args.reader_vus+args.writer_vus if args.mode=='open' and args.warmup else 0,
        'bootstrapSnapshotRate':50 if args.mode=='open' and args.warmup else None,
        'plannedWriteFlowsTotal':args.seconds*args.transitions_rate*5/14 if args.mode=='open' else None,
        'generatorLimits':{'cpus':2,'memoryBytes':args.generator_memory_gib*1024**3,'nofile':16384,'pids':256},
        'rawPoints':'private point output/k6-points.jsonl; no auth headers, bodies or high-cardinality identifiers in metric tags'})
    run('docker','run','-d','--name',name,'--label','phase19.owner='+stack.prefix,'--network',stack.prefix+'-data',
        '--cpus','2','--memory',str(args.generator_memory_gib)+'g','--pids-limit','256','--ulimit','nofile=16384:16384',
        '--mount',f'type=bind,source={HERE},target=/protocol,readonly','--mount',f'type=bind,source={stack.private / "fixture"},target=/fixture,readonly',
        '--mount',f'type=bind,source={out},target=/output','-e','BASE_URL=http://api:8080','-e','MODE='+args.mode,'-e','VUS='+str(args.vus),
        '-e','SECONDS='+str(duration),'-e','WARMUP_SECONDS='+str(args.warmup),'-e','INIT_SPREAD_SECONDS='+str(args.warmup),
        '-e','READ_RATE='+str(args.read_rate),'-e','TRANSITIONS_RATE='+str(args.transitions_rate),'-e','READER_VUS='+str(args.reader_vus),'-e','WRITER_VUS='+str(args.writer_vus),
        '-e','JOURNEY_RATE='+str(args.journey_rate),
        stack.config['images']['k6']['id'],'run','--quiet','--out','json=/output/k6-points.jsonl','/protocol/workload.js')
    resources,observations,observer_errors,probes=[],[],[],[]
    propagation_result={}
    propagation_stop=threading.Event()
    def propagate():
        try:propagation_result.update(collect_propagation(stack,out/'propagation',args.propagation_cycles,propagation_stop))
        except Exception as error:propagation_result.update(passed=False,error=str(error))
    propagation_thread=threading.Thread(target=propagate,daemon=True) if args.propagation_cycles else None
    if propagation_thread:propagation_thread.start()
    stop_event=threading.Event()
    def observe():
        while not stop_event.is_set():
            try:
                observations.append(stack.observation());save(out/'system-observations.json',observations)
                if args.mode == 'hotspot':
                    for label,path,user in [('public','/events',None),('auth','/auth/me',stack.users[3501]),
                        ('sentinel','/sessions/'+stack.fixture['sentinelSession']+'/seat-availability?zone=Zone-0',stack.users[3501])]:
                        code,_,timing=request(stack.base,path,user)
                        probes.append({'utc':datetime.now(timezone.utc).isoformat(),'kind':label,'status':code,**timing})
                    save(out/'control-probes.json',probes)
            except Exception as error:
                observer_errors.append(str(error))
            stop_event.wait(3)
    thread=threading.Thread(target=observe,daemon=True);thread.start()
    reason=None;exit_code=None;began=time.monotonic()
    try:
        previous={}
        while True:
            state=json.loads(run('docker','inspect',name))[0]['State']
            generator_running=state['Running']
            if not generator_running:
                exit_code=state['ExitCode']
                if state['OOMKilled']:reason='generator OOM'
                if reason or not propagation_thread or not propagation_thread.is_alive():break
            row={'utc':datetime.now(timezone.utc).isoformat()}
            for role,container in [('generator',name),('backend',stack.prefix+'-api'),('postgres',stack.prefix+'-postgres'),('redis',stack.prefix+'-redis')]:
                if role=='generator' and not generator_running:continue
                try:point=sample(container,previous.get(role))
                except RuntimeError:
                    if role=='generator' and not json.loads(run('docker','inspect',name))[0]['State']['Running']:break
                    raise
                previous[role]=point;row[role]=point
            if generator_running and 'generator' not in row:continue
            resources.append(row);save(out/'resources.json',resources)
            reason=stop_reason([r['generator'] for r in resources if 'generator' in r]) if generator_running else None
            backend_reason=stop_reason([{**r['backend'],'cpuFraction':0} for r in resources])
            reason=reason or backend_reason
            for role in ('postgres','redis'):
                reason=reason or stop_reason([{**r[role],'cpuFraction':0} for r in resources])
            if time.monotonic()-began>duration+90:reason='wall-clock deadline'
            if reason:
                run('docker','stop','--timeout','5',name);break
            time.sleep(1)
    except Exception as error:
        reason=str(error)
    finally:
        if propagation_thread:
            if reason:propagation_stop.set()
            propagation_thread.join(timeout=60)
            if propagation_thread.is_alive():reason=reason or 'propagation did not drain'
        stop_event.set();thread.join(timeout=20)
        logs=subprocess.run(['docker','logs',name],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8').stdout
        (out/'k6.log').write_text(logs,encoding='utf-8')
        run('docker','rm','-f',name)
    summary=json.loads((out/'k6-summary.json').read_text()) if (out/'k6-summary.json').exists() else None
    metrics=summary['data']['metrics'] if summary else {}
    count=lambda key:metrics.get(key,{}).get('values',{}).get('count',0)
    cleanup=[]
    if args.mode in ('hotspot','journeys'):
        # Fresh hotspot point starts with no live holder. Only this fixture's
        # SELECTING hotspot Checkouts are closed, after outcomes are captured.
        rows=stack.sql("SELECT id,user_id FROM checkout_sessions WHERE session_id='"+stack.fixture['hotspotSession']+"' AND status='SELECTING' ORDER BY id")
        by_id={u['userId']:u for u in stack.users}
        for ordinal,line in enumerate(rows.splitlines()):
            checkout_id,user_id=line.split('\t')
            code,body,_=request(stack.base,'/checkout-sessions/'+checkout_id+'/abandon',by_id[user_id],method='POST')
            cleanup.append({'ordinal':ordinal,'status':code,'terminal':body.get('status')})
        save(out/'cleanup.json',cleanup)
    after=stack.verify();save(out/'verifier-after.json',after)
    inventory_after=stack.inventory_counters();save(out/'inventory-after.json',inventory_after)
    points=out/'k6-points.jsonl'
    aggregated=aggregate(points) if points.exists() else None
    if aggregated:save(out/'aggregate.json',aggregated)
    result={'valid':bool(summary and resources and exit_code==0 and not reason and not observer_errors and after['passed'] and count('phase19_errors')==0 and count('dropped_iterations')==0 and count('phase19_started')==count('phase19_completed')),
        'diagnostic':args.diagnostic,'reason':reason,'exitCode':exit_code,'observerErrors':observer_errors,
        'startedIterations':count('phase19_started'),'completedBusinessIterations':count('phase19_completed'),
        'k6CompletedIterations':count('iterations'),'interruptedIterations':count('phase19_started')-count('iterations'),
        'droppedIterations':count('dropped_iterations'),'httpRequestCount':count('http_reqs'),'cursorAdvances':count('phase19_cursor_advances'),
        'initializedActiveVUs':count('phase19_initialized_vus'),'endedUtc':datetime.now(timezone.utc).isoformat(),
        'rawPointsSha256':sha(points) if points.exists() else None,'rawPointsBytes':points.stat().st_size if points.exists() else None}
    result['inventoryChanges']=inventory_delta(inventory_before,inventory_after)
    delta=result['inventoryChanges']
    result['valid']=bool(result['valid'] and delta['formalGenerated']==delta['formalProjected'] and delta['allStreamEntriesAdded']>=delta['formalProjected']>=0 and delta['generationsUnchanged'])
    if propagation_thread:
        result['propagationPassed']=propagation_result.get('passed',False)
        result['valid']=bool(result['valid'] and result['propagationPassed'])
    if aggregated:
        result['accounting']=accounting(aggregated,args.mode,duration,args.read_rate,args.transitions_rate,args.journey_rate,args.warmup,args.reader_vus+args.writer_vus)
        result['valid']=bool(result['valid'] and not result['accounting']['errors'] and count('phase19_http_started')==count('http_reqs'))
    if args.mode == 'hotspot':
        result['hotspotWinners']=count('phase19_hot_winners')
        result['controlProbeFailures']=sum(p['status']!=200 for p in probes)
        result['valid']=bool(result['valid'] and count('phase19_hot_winners')==1 and count('phase19_started')==args.vus
            and probes and not result['controlProbeFailures'] and all(c['status']==200 and c['terminal']=='ABANDONED' for c in cleanup))
    if args.mode=='journeys':
        winners=defaultdict(int)
        contenders=defaultdict(int)
        for key,value in (aggregated or {}).get('counts',{}).items():
            if not key.startswith('phase19_hot_outcomes|'):continue
            tags=json.loads(key.split('|',1)[1]);group=tags['group']
            contenders[group]+=value
            if tags['outcome']=='winner':winners[group]+=value
        result['journeyHotspotGroups']={group:{'contenders':n,'winners':winners[group]} for group,n in contenders.items()}
        result['plannedJourneysNominal']=duration*args.journey_rate
        result['valid']=bool(result['valid'] and duration*args.journey_rate<=count('phase19_started')<=duration*args.journey_rate+1
            and all(winners[group]==1 for group in contenders) and all(c['status']==200 and c['terminal']=='ABANDONED' for c in cleanup))
    save(out/'result.json',result);print(json.dumps(result,indent=2))
    return 0 if result['valid'] else 1


if __name__=='__main__':raise SystemExit(main())
