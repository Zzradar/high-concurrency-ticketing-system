"""Frozen dual campaign, Load-only G0, and fail-closed qualification ledger."""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import secrets
import shutil
import subprocess
import time

from phase14_topology import Topology, digest
from phase14_model import load_targets, segments
from phase14_evidence import sha256, aggregate, StopGuard, percentile


def write(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def run_id(case, mode):
    return 'phase14-'+mode+'-'+case.lower()+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(3)


def jobs(t, *, smoke=False):
    result=[('G0',{})] if smoke else []
    result += [(case,{'round':r}) for case in ('U1','U2') for r in range(len(t['online']['rounds']))]
    result += [(case,{'window':w}) for case in ('J1','O1') for w in range(len(t['burst']['windowsSeconds']))]
    result += [('E1',{})]
    result += [('H1',{'path':p,'repeat':r}) for p in ('temporary','formal') for r in range(t['hotspot']['h1Repeats'])]
    result += [('H2',{'session_count':n}) for n in t['hotspot']['h2SessionCounts']]
    result += [('H3',{'path':p}) for p in ('temporary','formal')]
    result += [(case,{'control_only':control}) for case in ('L1','L2') for control in (True,False)]
    result += [('S1',{})]
    return result


def plan(t, *, smoke=False):
    from run_phase14 import build_spec
    rows=[];n=t['burst']['users']
    for index,(case,args) in enumerate(jobs(t,smoke=smoke)):
        if case=='E1':
            rows.append({'index':index,'case':case,'arguments':args,'businessSecondsUpperBound':t['expiry']['futureSeconds']+t['expiry']['maxObserveSeconds'],
                         'orders':t['expiry']['orders'],'reset':True});continue
        spec=build_spec(t,case,'planned',round_index=args.get('round',0),window_index=args.get('window',0),path=args.get('path','formal'),
                        session_count=args.get('session_count',1),control_only=args.get('control_only',False),passed_u1=[n],passed_u2=[n])
        rows.append({'index':index,'case':case,'arguments':args,'businessSecondsUpperBound':spec['loadSeconds'],'reset':case!='G0',
                     'scenarios':spec['scenarios'],'logicalPlan':spec['plan'],'startupPlan':spec['startupPlan'],
                     'slices':t['slices'],'seatSlices':t['seatSlices']})
    business=sum(x['businessSecondsUpperBound'] for x in rows)
    # SQL restore, initial data generation, and sequential L page initialization
    # depend on observed speed; this is explicitly a schedule bound, not a price.
    overhead=sum(t['generator']['releaseLeadSeconds']+t['recovery']['observeSeconds']+t['probes']['paymentDeadlineSeconds']+
                 max(t['behavior']['refreshSeconds'])+t['generator']['scheduler_delivery_guard_seconds'] for x in rows if x['case']!='E1')
    return {'version':1,'mode':t['mode'],'targetsSha256':t['sourceSha256'],'jobs':rows,
            'businessSecondsUpperBound':business,'scheduledSecondsUpperBound':business+overhead,
            'additionalTime':'dataset generation, reset, auth calibration/warmup, L startup, aggregation measured separately',
            'hourlyPrice':None,'costFormula':'elapsed billable hours * (SUT hourly rate + Load hourly rate); prepaid sunk cost separate'}


def sample_errors(samples,t, *, load_only=False):
    errors=[]
    if len(samples)<2:return ['insufficient role samples']
    for x in samples:
        if not x.get('loadHost') or (not load_only and (not x.get('sutHost') or not x.get('sutContainers'))):errors.append('missing role samples')
        if x.get('swapping'):errors.append('host swap activity')
    # Actual gaps are evidence. Two consecutive missed periods invalidate a run.
    gaps=[b['time']-a['time'] for a,b in zip(samples,samples[1:])]
    missing=[g>2*t['generator']['sampleSeconds'] for g in gaps]
    if any(a and b for a,b in zip(missing,missing[1:])):errors.append('consecutive sampling gaps')
    return sorted(set(errors))


def evidence_hashes(root):
    root=Path(root)
    return {str(p.relative_to(root)):sha256(p) for p in sorted(root.rglob('*')) if p.is_file() and p.name not in ('commands.jsonl','evidence-hashes.json')}


def verify_hashes(root, hashes):
    root=Path(root).resolve()
    if not hashes:raise ValueError('missing evidence hashes')
    for name,value in hashes.items():
        path=(root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or sha256(path)!=value:raise ValueError('evidence changed or missing')


def verify_referenced_runs(root, kind):
    data=json.loads((Path(root)/('g0.json' if kind=='g0' else 'campaign.json')).read_text())
    references=data.get('legs',[]) if kind=='g0' else data.get('runs',[])
    if not references:raise ValueError('missing referenced calibration or smoke runs')
    for ref in references:verify_hashes(ref['root'],ref['hashes'])


def git_state(executor):
    def get(*args):return executor.run(['git',*args]).stdout.decode().strip()
    result={'head':get('rev-parse','HEAD'),'tree':get('rev-parse','HEAD^{tree}'),'branch':get('branch','--show-current'),
            'worktree':get('status','--porcelain'),'diffCheck':executor.run(['git','diff','--check'],check=False).returncode}
    if result['branch']!='main' or result['worktree'] or result['diffCheck']:raise ValueError('Git worktree is not clean main')
    return result


def clock_check(env):
    from phase14_sampling import postgres_clock_sample
    info={}
    for role in ('sut','load'):
        text=getattr(env,role).run(['timedatectl','show','-p','Timezone','-p','NTPSynchronized','-p','TimeUSec']).stdout.decode()
        info[role]=dict(line.split('=',1) for line in text.splitlines() if '=' in line)
        info[role]['syncServices']={service:getattr(env,role).run(['systemctl','is-active',service],check=False).stdout.decode().strip() for service in ('systemd-timesyncd','chrony')}
    from phase14_topology import HostClock
    clock=HostClock(env.sut)
    try:host=[clock.sample() for _ in range(5)]
    finally:clock.close()
    pg=[postgres_clock_sample(env) for _ in range(5)]
    limit=env.t['generator']['maxClockSkewMs']
    passed=all(v['NTPSynchronized']=='yes' and 'active' in v['syncServices'].values() for v in info.values()) and all(abs(x['offsetMs'])<=limit for x in host) and all(abs(x['clockSkewMs'])<=limit for x in pg)
    return {'passed':passed,'maxClockSkewMs':limit,'hosts':info,'hostMidpointSamples':host,'establishedDatabaseSamples':pg}


def current_fingerprint(env):
    states={r:git_state(getattr(env,r)) for r in ('load','sut')}
    attestation_path=env.runtime/'control-baseline.json'
    if attestation_path.stat().st_mode & 0o777 != 0o600:raise ValueError('control attestation permission invalid')
    control=json.loads(attestation_path.read_text())
    if control.get('officialOrigin')!='https://github.com/Zzradar/high-concurrency-ticketing-system.git' or not control.get('freshFetch') or control.get('worktree'):
        raise ValueError('trusted control fetch evidence missing')
    if time.time()-control['verifiedAt']>env.t['environment']['retentionDays']*86400:raise ValueError('control baseline expired')
    if any(x['head']!=control['head'] or x['tree']!=control['tree'] for x in states.values()):raise ValueError('four-place Git mismatch')
    remote=env.load.run(['git','ls-remote','origin','refs/heads/main'],env={'GIT_TERMINAL_PROMPT':'0'},timeout=30).stdout.decode().split()
    if not remote or remote[0]!=control['head']:raise ValueError('official origin advanced or unavailable')
    image=json.loads(env.docker('sut','image','inspect','phase14-backend:local').stdout)[0]
    image_record={'id':image['Id'],'platform':image['Os']+'/'+image['Architecture'],'configurationSha256':digest(image['Config'])}
    if image_record['id']!='sha256:c099a97fea4f60a7e3d26139770a552cb2a91304526978d5c65daab7df01b00c' or image_record['platform']!='linux/amd64':raise ValueError('backend image identity changed')
    data=env.data;manifest=json.loads((data/'dataset-manifest.json').read_text())
    if manifest['targetsSha256']!=env.t['sourceSha256']:raise ValueError('data targets mismatch')
    inputs={}
    for name,row in manifest['files'].items():
        if Path(name).name!=name or sha256(data/name)!=row['sha256']:raise ValueError('input changed')
        inputs[name]=row['sha256']
    snap=sha256(data/'base.dump')
    if snap!=(data/'base.sha256').read_text().strip():raise ValueError('snapshot changed')
    return {'git':states,'controlHead':control['head'],'controlTree':control['tree'],'officialOriginHead':remote[0],
            'targetsSha256':env.t['sourceSha256'],'image':image_record,'datasetManifestSha256':sha256(data/'dataset-manifest.json'),
            'inputs':inputs,'snapshotSha256':snap,'databaseBaselineSha256':sha256(data/'database-fingerprint.json'),
            'topology':env.topology.public()}


def preflight(env):
    from phase14_dual_sampling import DualSampler
    from run_phase14 import save_sample
    env.validate();fingerprint=current_fingerprint(env);clocks=clock_check(env)
    sampler=DualSampler(env);samples=[];guard=StopGuard(env.t);errors=[]
    for _ in range(3):
        x,pg,rd,_=sampler.sample();samples.append(x);save_sample(env.root,x,pg,rd);errors+=guard.sample(x)
    errors+=sample_errors(samples,env.t)
    if samples[-1]['loadHost']['identity']==samples[-1]['sutHost']['identity']:errors.append('same host')
    if not clocks['passed']:errors.append('clock qualification failed')
    disk_floor=(env.data/'base.dump').stat().st_size*env.t['generator']['diskSafetyFactor']
    if any(samples[-1][r+'Host']['diskFreeBytes']<disk_floor or samples[-1][r+'Host']['inodesFree']==0 for r in ('sut','load')):errors.append('insufficient snapshot disk reserve')
    targets=env.prometheus('/api/v1/targets')
    active=targets.get('data',{}).get('activeTargets',[])
    if len(active)!=3 or any(x.get('health')!='up' for x in active):errors.append('Prometheus targets incomplete')
    result={'passed':not errors,'errors':sorted(set(errors)),'fingerprint':fingerprint,'clock':clocks,
            'hostIdentities':{r:samples[-1][r+'Host']['identity'] for r in ('sut','load')},
            'diskFreeBytes':{r:samples[-1][r+'Host']['diskFreeBytes'] for r in ('sut','load')},
            'topology':env.topology.public(),'prometheusJobs':[{'job':x.get('labels',{}).get('job'),'health':x.get('health')} for x in active]}
    write(env.root/'preflight.json',result)
    return result


def qualification_guard(args, env, *, immediate=True):
    if not getattr(env,'dual',False) or not args.yes or not args.formal_approved or not args.qualification:
        raise ValueError('formal requires dual, --yes, --qualification and --formal-approved')
    q=json.loads(args.qualification.read_text())
    if q.get('status')!='pass' or q.get('topologyMode')!='dual':raise ValueError('qualification did not pass')
    if q.get('shards')!=args.shards:raise ValueError('generator shard topology changed')
    if time.time()-q['createdAt']>env.t['environment']['retentionDays']*86400:raise ValueError('qualification expired')
    if q['fingerprint']!=current_fingerprint(env):raise ValueError('qualification fingerprint mismatch')
    for name in ('g0','smoke'):
        ref=q[name];verify_hashes(ref['root'],ref['hashes'])
        verify_referenced_runs(ref['root'],name)
    if immediate:
        fresh=preflight(env)
        if not fresh['passed']:raise ValueError('immediate preflight failed')
        if fresh['diskFreeBytes']['load']<q['longestScenarioDiskBudgetBytes']:raise ValueError('formal result disk budget insufficient')
    return q


def g0_leg(args,t,env, *, detailed=True):
    """No SUT method is called here, including validation/reset/SQL/clock probes."""
    from run_phase14 import build_spec, COMPOSE, RawProgress, save_sample
    from phase14_dual_sampling import DualSampler
    env.resolve('load');env.inspect_role('load')
    env.compose_role('load','up','-d','noop')
    spec=build_spec(t,'G0',env.root.name);spec['shards']=segments(args.shards,t)
    spec['releaseAtMs']=int((time.time()+t['generator']['releaseLeadSeconds'])*1000)
    write(env.root/'spec.json',spec)
    # Shared frozen G0 workload consumes only the Load-side synthetic input files.
    processes=[];logs=[];errors=[];samples=[];guard=StopGuard(t);sampler=DualSampler(env,load_only=True,detailed=detailed)
    progress=RawProgress(t);start=time.time();disk_before=shutil.disk_usage(env.root).free
    try:
        for shard in spec['shards']:
            number=shard['shard'];folder=env.root/'shards'/number;folder.mkdir(parents=True)
            log=(folder/'console.log').open('wb');logs.append(log)
            argv=['docker','compose','-p',env.project,'-f',str(COMPOSE),'run','--no-deps','--name',env.load_project+'-k6-'+env.root.name+'-'+number,
                  '-e','SHARD='+number,'-e','PHASE14_ROLE=main','-e','PHASE14_SPEC=/results/'+env.root.name+'/spec.json',
                  '-e','BASE_URL=http://noop:8080','k6','run','--execution-segment',shard['segment'],'--execution-segment-sequence',shard['sequence'],
                  '--out','json=/results/'+env.root.name+'/shards/'+number+'/raw.json','workloads/phase14-online.js']
            processes.append(env.start_generator(argv,log))
        while any(p.poll() is None for p in processes):
            x,pg,rd,_=sampler.sample();samples.append(x);save_sample(env.root,x,pg,rd)
            bad,dropped=progress.read(env.root);x['dropped']=dropped;errors+=guard.sample(x)
            if bad:errors.append('G0 system error')
            if time.time()-start>t['generator']['releaseLeadSeconds']+spec['loadSeconds']+t['probes']['paymentDeadlineSeconds']+max(t['behavior']['refreshSeconds'])+60:errors.append('G0 deadline')
            if errors:break
            time.sleep(max(0,t['generator']['sampleSeconds']-x['collectionSeconds']))
    except Exception as error:
        errors.append(type(error).__name__+': '+str(error))
    finally:
        env.stop_generators()
        for p in processes:
            if p.wait(timeout=30):errors.append('G0 generator exit failed')
        for log in logs:log.close()
        env.compose_role('load','stop','noop')
    summary=None
    for shard in spec['shards']:
        folder=env.root/'shards'/shard['shard'];raw=folder/'raw.json'
        if not raw.exists():errors.append('missing G0 raw');continue
        with raw.open('rb') as src,gzip.open(folder/'raw.json.gz','wb') as dst:shutil.copyfileobj(src,dst)
        (folder/'raw.json.gz.sha256').write_text(sha256(folder/'raw.json.gz'))
    try:
        summary=aggregate(env.root,spec['shards'],spec['plan']);write(env.root/'global-summary.json',summary);errors+=summary['errors']
        if any(r['metric']=='phase14_results' and r['tags'][2]!='business_success' and r['count'] for r in summary['counts']):errors.append('noop request failure')
    except (OSError,ValueError) as error:errors.append('G0 evidence aggregation failed: '+type(error).__name__)
    errors+=sample_errors(samples,t,load_only=True)
    raw_bytes=sum(p.stat().st_size for p in env.root.glob('shards/*/raw.json'))
    projected=raw_bytes/max(spec['loadSeconds'],1)*max(t['soak']['extendedSeconds'],t['soak']['seconds'])*t['generator']['diskSafetyFactor']
    if shutil.disk_usage(env.root).free<projected:errors.append('longest scenario disk budget insufficient')
    result={'status':'pass' if not errors else 'fail','case':'G0','mode':t['mode'],'topologyMode':'dual','runId':env.root.name,
            'errors':sorted(set(errors)),'sutTouched':False,'planned':spec['plan'],'rawBytes':raw_bytes,'diskGrowthBytes':max(0,disk_before-shutil.disk_usage(env.root).free),
            'longestScenarioDiskBudgetBytes':projected,'samplingOverhead':'requires independent paired calibration',
            'gitHead':env.load.run(['git','rev-parse','HEAD']).stdout.decode().strip(),'targetsSha256':t['sourceSha256']}
    write(env.root/'g0.json',result)
    print(json.dumps({'runId':env.root.name,'g0':result['status'],'errors':result['errors']}),flush=True)
    return 0 if not errors else 1


def overhead_comparison(rows, limit):
    if len(rows)!=4 or [r['sampling'] for r in rows]!=[False,True,True,False]:
        return {'passed':False,'limit':limit,'errors':['incomplete ABBA calibration']}
    ratios={}
    for metric in ('p95','p99'):
        off=percentile([r[metric] for r in rows if not r['sampling']],.5)
        on=percentile([r[metric] for r in rows if r['sampling']],.5)
        ratios[metric]=on/off-1 if off>0 else None
    return {'passed':all(v is not None and v<=limit for v in ratios.values()),'limit':limit,'latencyGrowthFractions':ratios,
            'constantWatchdog':'host /proc and container identity/state remain enabled in both legs', 'legs':rows}


def run_g0(args,t,env):
    # ABBA is a predeclared paired calibration, not selective performance retries.
    # Any failed leg stops this calibration; all legs retain separate Run IDs.
    if t['mode']=='smoke':return g0_leg(args,t,env)
    rows=[];children=[];errors=[];disk_budget=0
    for detailed in (False,True,True,False):
        child=env.child(Path(env.topology.values['resultRoot'])/run_id('g0','formal'))
        code=g0_leg(args,t,child,detailed=detailed)
        result=json.loads((child.root/'g0.json').read_text());children.append({'root':str(child.root),'hashes':evidence_hashes(child.root)})
        disk_budget=max(disk_budget,result['longestScenarioDiskBudgetBytes'])
        if code:errors+=result['errors'];break
        summary=json.loads((child.root/'global-summary.json').read_text())
        row=next(x for x in summary['trends'] if x['metric']=='phase14_duration_ms' and x['tags']==['main','health','business_success'])
        rows.append({'sampling':detailed,'runId':child.root.name,'p95':row['p95'],'p99':row['p99']})
    overhead=overhead_comparison(rows,t['generator']['maxSamplingOverheadFraction'])
    write(env.root/'sampling-overhead.json',overhead)
    if not overhead['passed']:errors.append('sampling overhead qualification failed or incomplete')
    result={'status':'fail' if errors else 'pass','case':'G0','mode':'formal','topologyMode':'dual','runId':env.root.name,
            'errors':sorted(set(errors)),'sutTouched':False,'legs':children,'targetsSha256':t['sourceSha256'],
            'shards':args.shards,
            'longestScenarioDiskBudgetBytes':disk_budget,
            'gitHead':env.load.run(['git','rev-parse','HEAD']).stdout.decode().strip()}
    write(env.root/'g0.json',result)
    return 1 if errors else 0


def qualify(args,env):
    checks=preflight(env);errors=list(checks['errors']);g0={};smoke={}
    try:
        g0=json.loads((args.g0_evidence/'g0.json').read_text())
        smoke=json.loads((args.smoke_evidence/'campaign.json').read_text())
        if g0.get('status')!='pass' or g0.get('mode')!='formal' or g0.get('sutTouched') is not False:errors.append('formal Load G0 missing')
        if g0.get('shards')!=args.shards or smoke.get('shards')!=args.shards:errors.append('qualification shard count mismatch')
        overhead=json.loads((args.g0_evidence/'sampling-overhead.json').read_text())
        if overhead.get('passed') is not True or overhead.get('limit')!=env.t['generator']['maxSamplingOverheadFraction']:errors.append('sampling overhead failed')
        if smoke.get('mode')!='smoke' or smoke.get('status')!='pass' or len(smoke.get('runs',[]))!=len(jobs(load_targets(smoke=True),smoke=True)):errors.append('complete smoke missing')
        verify_referenced_runs(args.g0_evidence,'g0')
        for index,record in enumerate(smoke.get('runs',[])):
            verify_hashes(record['root'],record['hashes'])
            if record.get('passed') is not True:errors.append('smoke child failed')
            if (record['case'],record['arguments'])!=jobs(load_targets(smoke=True),smoke=True)[index]:errors.append('smoke matrix differs')
            if record['case']!='G0':
                reset=json.loads((Path(record['root'])/'reset.json').read_text())
                if reset.get('passed') is not True or reset['after']!=reset['baseline'] or reset['redisDbsize']!=0:errors.append('smoke reset mismatch')
        if g0.get('gitHead')!=checks['fingerprint']['controlHead'] or smoke.get('gitHead')!=checks['fingerprint']['controlHead']:errors.append('G0/smoke Git mismatch')
        if g0.get('targetsSha256')!=env.t['sourceSha256'] or smoke.get('targetsSha256')!=env.t['sourceSha256']:errors.append('G0/smoke targets mismatch')
    except (OSError,ValueError,TypeError,AttributeError,KeyError):errors.append('required qualification evidence absent')
    result={'status':'pass' if not errors else 'fail','errors':errors,'createdAt':time.time(),'topologyMode':'dual',
            'shards':args.shards,
            'longestScenarioDiskBudgetBytes':g0.get('longestScenarioDiskBudgetBytes'),
            'fingerprint':checks['fingerprint'],'preflight':checks,'plan':plan(env.t),
            'g0':{'root':str(args.g0_evidence),'runId':g0.get('runId'),'hashes':evidence_hashes(args.g0_evidence) if args.g0_evidence else {}},
            'smoke':{'root':str(args.smoke_evidence),'runId':smoke.get('runId'),'hashes':evidence_hashes(args.smoke_evidence) if args.smoke_evidence else {}}}
    write(env.root/'qualification.json',result)
    return 0 if not errors else 1


def campaign(args,t,env):
    from run_phase14 import execute_case, compare_background
    smoke=t['mode']=='smoke';q=None
    if not smoke:q=qualification_guard(args,env)
    ledger=[];controls={};passed={'U1':[],'U2':[]}
    identity={'mode':t['mode'],'gitHead':env.load.run(['git','rev-parse','HEAD']).stdout.decode().strip(),
              'shards':args.shards,
              'targetsSha256':t['sourceSha256'],'qualificationSha256':sha256(args.qualification) if q else None}
    if args.resume_from:
        old=json.loads(args.resume_from.read_text())
        if any(old.get(k)!=v for k,v in identity.items()):raise ValueError('checkpoint identity mismatch')
        for r in old['runs']:
            if not r['passed']:break
            i=len(ledger)
            if (r['case'],r['arguments'])!=jobs(t,smoke=smoke)[i]:raise ValueError('checkpoint job mismatch')
            verify_hashes(r['root'],r['hashes']);ledger.append(r)
            if r['case'] in passed:passed[r['case']].append(t['burst']['users'])
            if r['case'] in ('L1','L2') and r['arguments'].get('control_only'):controls[r['case']]=Path(r['root'])
    write(env.root/'plan.json',plan(t,smoke=smoke))
    for index,(case,changes) in enumerate(jobs(t,smoke=smoke)):
        if index<len(ledger):continue
        child=env.child(Path(env.topology.values['resultRoot'])/run_id(case,t['mode']))
        job=argparse.Namespace(**vars(args));job.case=case
        for key,value in changes.items():setattr(job,key,value)
        job.passed_u1=passed['U1'];job.passed_u2=passed['U2']
        if not smoke:qualification_guard(job,child)
        code=execute_case(job,t,child)
        ok=code==0
        if case in ('L1','L2'):
            if getattr(job,'control_only',False):controls[case]=child.root
            elif ok:
                comparison=compare_background(controls[case],child.root,t);write(child.root/'login-background-comparison.json',comparison)
                if not smoke:ok=comparison['status']=='pass'
        if not smoke and case!='E1':
            result=json.loads((child.root/'verdict.json').read_text())
            key='overload_protection' if case in ('L1','L2') else 'capacity'
            ok=ok and result['measurement_validity']['status']=='pass' and result[key]['status']=='pass'
        record={'index':index,'case':case,'arguments':changes,'runId':child.root.name,'root':str(child.root),'passed':ok,'hashes':evidence_hashes(child.root)}
        ledger.append(record)
        with (env.root/'checkpoint.jsonl').open('a') as f:f.write(json.dumps(record)+'\n')
        write(env.root/'campaign.json',{**identity,'runId':env.root.name,'status':'running' if ok else 'stopped','runs':ledger})
        if not ok:return 1
        if case in passed:passed[case].append(t['burst']['users'])
    write(env.root/'campaign.json',{**identity,'runId':env.root.name,'status':'pass','runs':ledger})
    return 0


def dual_main(args,t):
    from phase14_dual import DualEnvironment
    from run_phase14 import calibration,execute_case
    topology=Topology.read(args.topology_config,t)
    if args.action=='plan' or not args.yes:
        print(json.dumps(plan(t,smoke=t['mode']=='smoke'),ensure_ascii=False,indent=2));return 0
    env=DualEnvironment(t,Path(topology.values['resultRoot'])/run_id(args.action,t['mode']),topology)
    if args.action=='prepare':env.prepare();return 0
    if args.action=='preflight':return 0 if preflight(env)['passed'] else 1
    if args.action=='qualify':return qualify(args,env)
    if args.action=='calibrate':env.reset(yes=True,snapshot=env.data/'base.dump');calibration(env);return 0
    if args.action=='campaign':return campaign(args,t,env)
    if t['mode']=='formal' and args.case!='G0':qualification_guard(args,env)
    return execute_case(args,t,env)
