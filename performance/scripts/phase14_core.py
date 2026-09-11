"""User-authorized core campaign: unchanged business input, bounded generators."""
from copy import deepcopy
import math,time
from phase14_model import segments

POLICY_VERSION='phase14-core-method-1'
ABORT_GUARD_SECONDS=30

def probe_budget(t):
    deadline=t['probes']['paymentDeadlineSeconds']
    return {name:{'rate':t['probes']['paymentRate' if name=='payment' else 'controlRate'],
        'hardDeadlineSeconds':deadline,'marginFraction':.5,
        'preAllocatedVUs':math.ceil(t['probes']['paymentRate' if name=='payment' else 'controlRate']*deadline*1.5/32)*32}
        for name in ('control_health','control_auth','control_availability','payment')}

def core_spec(t,case,run_id,**kwargs):
    from run_phase14 import build_spec
    spec=build_spec(t,case,run_id,**kwargs);budget=probe_budget(t)
    for name,scenario in spec['scenarios'].items():
        if name in budget:
            scenario['preAllocatedVUs']=budget[name]['preAllocatedVUs']
            scenario['maxVUs']=scenario['preAllocatedVUs']
            spec['deliverySchedule'][name]['businessExecutor']['preAllocatedVUs']=scenario['preAllocatedVUs']
            spec['deliverySchedule'][name]['businessExecutor']['maxVUs']=scenario['maxVUs']
    spec['generatorPolicy']={'version':POLICY_VERSION,'globalProbe':True,'probeBudget':budget,
        'readinessSeconds':t['generator']['releaseLeadSeconds'],'abortGuardSeconds':ABORT_GUARD_SECONDS}
    return spec

def units(count,t,case):
    if count+1>t['generator']['maxShards']:raise ValueError('unit label budget exceeded')
    result=[{**x,'role':'main'} for x in segments(count,t)]
    if case!='G0':result.append({'shard':str(count),'role':'probe','segment':'0:1','sequence':'0,1'})
    return result

def arm(spec,now=None):
    now=time.time() if now is None else now
    spec['initializationDeadlineAtMs']=int((now+spec['targets']['generator']['releaseLeadSeconds'])*1000)
    spec['releaseAtMs']=spec['initializationDeadlineAtMs']+ABORT_GUARD_SECONDS*1000
    return now

def core_jobs():
    return [('U1',{'round':0}),('U2',{'round':0})]+[('O1',{'window':i}) for i in range(3)]+[
        ('H1',{'path':'temporary','repeat':0}),('H1',{'path':'formal','repeat':0}),('H3',{'path':'formal'}),
        ('L2',{'control_only':True}),('L2',{'control_only':False})]

def core_plan(t):
    from phase14_campaign import plan
    old=plan(t);rows=[]
    for case,args in core_jobs():
        row=next(deepcopy(x) for x in old['jobs'] if x['case']==case and x['arguments']==args)
        spec=core_spec(t,case,'planned',round_index=args.get('round',0),window_index=args.get('window',0),
            path=args.get('path','formal'),control_only=args.get('control_only',False),
            passed_u1=[t['burst']['users']],passed_u2=[t['burst']['users']])
        row['index']=len(rows);row['scenarios']=spec['scenarios'];row['generatorPolicy']=spec['generatorPolicy'];rows.append(row)
    overhead=t['generator']['releaseLeadSeconds']+ABORT_GUARD_SECONDS+t['recovery']['observeSeconds']+t['probes']['paymentDeadlineSeconds']+max(t['behavior']['refreshSeconds'])+t['generator']['scheduler_delivery_guard_seconds']
    business=sum(x['businessSecondsUpperBound'] for x in rows)
    return {'version':1,'scope':'Phase14 core formal matrix','targetsSha256':t['sourceSha256'],'jobs':rows,
        'businessSecondsUpperBound':business,'scheduledSecondsUpperBound':business+len(rows)*overhead,
        'additionalTime':'reset, calibration, warmup, aggregation; four-hour external wall deadline still applies'}


def init_once(args,t,env):
    """Fresh containers; same U1 executors/input/quota, stopped before release."""
    import json,re,gzip
    from pathlib import Path
    from phase14_initialization import Initialization
    from phase14_dual_sampling import DualSampler
    from phase14_evidence import StopGuard,sha256
    from phase14_campaign import write,current_fingerprint,sample_errors
    from run_phase14 import COMPOSE,save_sample
    env.validate();fingerprint=current_fingerprint(env);before=env.fingerprint()
    spec=core_spec(t,'U1',env.root.name);spec['shards']=units(args.shards,t,'U1');spec['initOnly']=not bool(args.init_delay_last)
    # Fault injection is a small fixture, never a formal qualification attempt.
    if args.init_delay_last:
        if t['mode']!='smoke':raise ValueError('fault fixture must be smoke')
        spec['initializationDelayShard']=str(args.shards);spec['initializationDelaySeconds']=args.init_delay_last
    sampler=DualSampler(env);guard=StopGuard(t);samples=[];errors=[];processes=[];logs=[]
    def observe():
        if getattr(args,'deadline_at',None) and time.time()>=args.deadline_at:raise RuntimeError('core wall-clock deadline')
        x,pg,rd,_=sampler.sample();samples.append(x);save_sample(env.root,x,pg,rd)
        errors.extend(guard.sample(x))
        if errors:raise RuntimeError('init-only resource stop')
    arm(spec)
    if args.init_delay_last:
        spec['initializationDeadlineAtMs']=int(time.time()*1000)+30000
        spec['releaseAtMs']=spec['initializationDeadlineAtMs']+ABORT_GUARD_SECONDS*1000
    write(env.root/'spec.json',spec)
    try:
        with Initialization(env.root,env.root.name,[s['shard'] for s in spec['shards']],spec['releaseAtMs'],observe,
                deadline_at_ms=spec['initializationDeadlineAtMs'],abort=env.stop_generators) as initialization:
            for unit in spec['shards']:
                number=unit['shard'];folder=env.root/'shards'/number;folder.mkdir(parents=True);log=(folder/'console.log').open('wb');logs.append(log)
                argv=['docker','compose','-p',env.project,'-f',str(COMPOSE),'run','--no-deps','--name',env.load_project+'-k6-'+env.root.name+'-'+number,
                    '-e','SHARD='+number,'-e','PHASE14_ROLE='+unit['role'],'-e','PHASE14_SPEC=/results/'+env.root.name+'/spec.json',
                    '-e','BASE_URL='+env.base,'k6','run','--execution-segment',unit['segment'],'--execution-segment-sequence',unit['sequence'],
                    '--out','json=/results/'+env.root.name+'/shards/'+number+'/raw.json','workloads/phase14-online.js']
                processes.append(env.start_generator(argv,log));initialization.register(processes[-1],log,number)
            initialization.finish()
    except Exception as error:errors.append(type(error).__name__+': '+str(error))
    finally:
        env.stop_generators()
        for process in processes:process.wait(timeout=30)
        for log in logs:log.close()
    stopped_at=time.time()*1000;after=env.fingerprint();http=main=payment=0;actual=[]
    for unit in spec['shards']:
        folder=env.root/'shards'/unit['shard'];raw=folder/'raw.json'
        if raw.exists():
            for line in raw.read_text().splitlines():
                x=json.loads(line)
                if x.get('type')!='Point':continue
                if x['metric']=='http_reqs':http+=x['data']['value']
                if x['metric']=='phase14_iterations_started':
                    if x['data'].get('tags',{}).get('scenario')=='payment':payment+=x['data']['value']
                    else:main+=x['data']['value']
            with raw.open('rb') as source,gzip.open(folder/'raw.json.gz','wb') as dest:
                import shutil
                shutil.copyfileobj(source,dest)
            (folder/'raw.json.gz.sha256').write_text(sha256(folder/'raw.json.gz'))
        log=(folder/'console.log').read_text(errors='replace') if (folder/'console.log').exists() else ''
        match=re.search(r'(\d+) max VUs',log)
        actual.append({'shard':unit['shard'],'role':unit['role'],'maxVUs':int(match.group(1)) if match else None})
    zero=http==main==payment==0 and before==after
    errors.extend(sample_errors(samples,t))
    init=json.loads((env.root/'initialization.json').read_text())
    expected=t['online']['rounds'][0][-1]['users']+sum(x['preAllocatedVUs'] for x in probe_budget(t).values())
    configured=sum(x['maxVUs'] or 0 for x in actual)
    if not zero:errors.append('initialization emitted business or database writes')
    if configured!=expected:errors.append('initialized VU count differs from plan')
    if stopped_at>=spec['releaseAtMs']:errors.append('stop missed business release protection')
    passed=not errors and init['status']=='pass'
    if args.init_delay_last:
        passed=zero and init['status']=='fail' and stopped_at<spec['releaseAtMs'] and any('initialization missed' in e for e in errors)
    record={'status':'pass' if passed else 'fail','kind':'fault_fixture' if args.init_delay_last else 'cold_initialization',
        'method':1,'gitHead':fingerprint['controlHead'],'fingerprint':fingerprint,'shards':args.shards,
        'policy':spec['generatorPolicy'],'initialization':init,'actualUnits':actual,'expectedMaxVUs':expected,
        'httpRequests':http,'mainStarted':main,'paymentStarted':payment,'databaseUnchanged':before==after,
        'before':before,'after':after,'stoppedAtMs':stopped_at,'errors':errors,
        'maxLoadHostCpu':max((x['loadHost']['cpuFraction'] for x in samples),default=None),
        'maxLoadHostMemory':max((x['loadHost']['memoryFraction'] for x in samples),default=None),
        'swap':any(x['swapping'] for x in samples)}
    write(env.root/'init-only.json',record);return passed


def init_pair(args,t,env):
    from pathlib import Path
    from phase14_campaign import run_id,write,evidence_hashes
    rows=[]
    for _ in range(1 if args.init_delay_last else 2):
        child=env.child(Path(env.topology.values['resultRoot'])/run_id('cold-init',t['mode']))
        passed=init_once(args,t,child)
        rows.append({'root':str(child.root),'passed':passed,'hashes':evidence_hashes(child.root)})
        if not passed:break
    good=len(rows)==(1 if args.init_delay_last else 2) and all(x['passed'] for x in rows)
    write(env.root/'init-qualification.json',{'status':'pass' if good else 'fail','method':1,'faultFixture':bool(args.init_delay_last),'runs':rows})
    return 0 if good else 1


def verify_init_evidence(path,env):
    import json
    from pathlib import Path
    from phase14_campaign import verify_hashes,current_fingerprint,evidence_hashes
    p=Path(path);q=json.loads((p/'init-qualification.json').read_text());fingerprint=current_fingerprint(env)
    if q['status']!='pass' or q['faultFixture'] or len(q['runs'])!=2:raise ValueError('two consecutive cold initialization passes required')
    for ref in q['runs']:
        verify_hashes(ref['root'],ref['hashes']);r=json.loads((Path(ref['root'])/'init-only.json').read_text())
        if not ref['passed'] or r['status']!='pass' or r['kind']!='cold_initialization' or r['fingerprint']!=fingerprint:raise ValueError('cold initialization baseline differs')
        init=r['initialization']
        if init['status']!='pass' or len(init['ready'])!=5 or any(x['readyAtMs']>=init['deadlineAtMs'] for x in init['ready']):raise ValueError('cold readiness deadline failed')
        if r['shards']!=4 or r['httpRequests'] or r['mainStarted'] or r['paymentStarted'] or not r['databaseUnchanged']:raise ValueError('initialization did not preserve zero business')
    return {'root':str(p),'hashes':evidence_hashes(p)}


def campaign(args,t,env):
    import argparse,json
    from pathlib import Path
    from phase14_campaign import qualification_guard,run_id,write,evidence_hashes
    from run_phase14 import execute_case,compare_background
    if not args.deadline_at:raise ValueError('core campaign requires wall-clock deadline')
    qualification_guard(args,env);p=core_plan(t);write(env.root/'plan.json',p);ledger=[];families=set();controls={};stable={'U1':[],'U2':[]};stop_all=None
    identity={'scope':p['scope'],'gitHead':env.load.run(['git','rev-parse','HEAD']).stdout.decode().strip(),'targetsSha256':t['sourceSha256'],'deadlineAt':args.deadline_at}
    for index,(case,changes) in enumerate(core_jobs()):
        estimate=p['jobs'][index]['businessSecondsUpperBound']+1080
        if case=='L2' and changes.get('control_only'):estimate*=2
        if time.time()+estimate>=args.deadline_at:stop_all=stop_all or 'four-hour work budget; reserve cleanup time'
        reason=stop_all or ('family stopped after valid failure' if case in families else None)
        if case=='L2' and not (stable['U1'] and stable['U2']):reason=reason or 'frozen 10000-user background prerequisite not established'
        if reason:ledger.append({'index':index,'case':case,'arguments':changes,'status':'not_run','reason':reason})
        else:
            child=env.child(Path(env.topology.values['resultRoot'])/run_id(case,'formal'));job=argparse.Namespace(**vars(args));job.case=case
            for key,value in changes.items():setattr(job,key,value)
            job.passed_u1=stable['U1'];job.passed_u2=stable['U2']
            try:
                qualification_guard(job,child);code=execute_case(job,t,child)
                v=json.loads((child.root/'verdict.json').read_text());correct=json.loads((child.root/'correctness.json').read_text())
                valid=v['measurement_validity']['status']=='pass';key='overload_protection' if case=='L2' else 'capacity'
                good=code==0 and valid and v[key]['status']=='pass'
                if case=='L2':
                    if changes['control_only']:controls[case]=child.root
                    elif valid:
                        comparison=compare_background(controls[case],child.root,t);write(child.root/'login-background-comparison.json',comparison);good=good and comparison['status']=='pass'
                status='pass' if good else 'valid_failure' if valid else 'invalid_measurement'
                if not correct['passed']:stop_all='data reconciliation failed; stop all tests'
                elif not valid:stop_all='invalid measurement; preserve evidence before any new method'
                elif not good:families.add(case)
                if good and case in stable:stable[case]=[t['burst']['users']]
            except Exception as error:
                child.stop_generators();status='invalid_measurement';stop_all=type(error).__name__+': '+str(error);write(child.root/'core-error.json',{'error':stop_all})
            ledger.append({'index':index,'case':case,'arguments':changes,'status':status,'runId':child.root.name,'root':str(child.root),'hashes':evidence_hashes(child.root)})
        write(env.root/'campaign.json',{**identity,'runId':env.root.name,'status':'running','runs':ledger})
    write(env.root/'campaign.json',{**identity,'runId':env.root.name,'status':'pass' if all(x['status']=='pass' for x in ledger) else 'completed_with_stops','runs':ledger})
    return 0 if all(x['status']=='pass' for x in ledger) else 1
