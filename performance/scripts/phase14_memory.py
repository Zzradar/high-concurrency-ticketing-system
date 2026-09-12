"""One-shot real-response memory qualification; formal workload stays frozen."""
import json
from pathlib import Path

MAIN_BYTES=3221225472
PROBE_BYTES=2147483648
BUSINESS_SECONDS=120
OVERRIDE=json.loads((Path(__file__).resolve().parents[1]/'phase14/load-main-memory.json').read_text())


def main_shard(argv):
    return 'PHASE14_ROLE=main' in argv and '--execution-segment' in argv


def apply_main_override(env,argv):
    from phase14_campaign import write
    from phase14_evidence import sha256
    if not main_shard(argv):return argv
    path=env.root/'main-memory.override.json'
    write(path,OVERRIDE)
    model=json.loads(json.dumps(env.models['load']))
    original=int(model['services']['k6']['mem_limit'])
    if original!=PROBE_BYTES:raise ValueError('unexpected base generator memory')
    model=json.loads(env.docker('load','compose','-p',env.load_project,'-f',env.role_file('load'),'-f',str(path),'config','--format','json').stdout)
    if int(model['services']['k6']['mem_limit'])!=MAIN_BYTES:raise ValueError('main override rendering differs')
    write(env.root/'main-memory.rendered.json',model)
    write(env.root/'main-memory.manifest.json',{'oldBytes':original,'mainBytes':MAIN_BYTES,'probeBytes':PROBE_BYTES,
        'baseComposeSha256':sha256(Path(env.role_file('load'))),'overrideSha256':sha256(path),
        'renderedSha256':sha256(env.root/'main-memory.rendered.json')})
    argv=list(argv);index=argv.index('run');argv[index:index]=['-f',str(path)]
    return argv


def cgroup_memory(item):
    """Use the inspected live PID and cgroup v2 files, not a guessed limit."""
    pid=item['State']['Pid'];lines=(Path('/proc')/str(pid)/'cgroup').read_text().splitlines()
    group=next(x[3:] for x in lines if x.startswith('0::'))
    root=Path('/sys/fs/cgroup');path=(root/group.lstrip('/')).resolve()
    if not path.is_relative_to(root):raise ValueError('cgroup path escaped')
    limit=int((path/'memory.max').read_text());current=int((path/'memory.current').read_text())
    stats=dict(x.split() for x in (path/'memory.stat').read_text().splitlines())
    events={k:int(v) for k,v in (x.split() for x in (path/'memory.events').read_text().splitlines())}
    inactive=int(stats.get('inactive_file',0));work=max(0,current-inactive)
    return {'containerId':item['Id'],'name':item['Name'].lstrip('/'),'runId':item['Config']['Labels'].get('ticketing.phase14.run'),
        'inspectLimit':item['HostConfig']['Memory'],'cgroupLimit':limit,'rawBytes':current,'inactiveFileBytes':inactive,
        'workingBytes':work,'fraction':work/limit,'events':events}


def validate_units(records,run_id):
    rows=[x for x in records if x['runId']==run_id]
    by_shard={x['name'].rsplit('-',1)[1]:x for x in rows}
    if set(by_shard)!={'0','1','2','3','4'}:raise ValueError('five memory execution units required')
    for shard,x in by_shard.items():
        expected=PROBE_BYTES if shard=='4' else MAIN_BYTES
        if x['inspectLimit']!=expected or x['cgroupLimit']!=expected:raise ValueError('effective memory limit mismatch')
        if x['events'].get('oom',0) or x['events'].get('oom_kill',0):raise ValueError('cgroup OOM detected')
    return by_shard


def assess(samples,run_id,release,summary,invariants):
    errors=[];business=[x for x in samples if release<=x['time']<=release+BUSINESS_SECONDS+2]
    peaks={str(i):0 for i in range(4)};history={str(i):[] for i in range(4)}
    for x in business:
        try:units=validate_units(x['loadHost']['generatorCgroups'],run_id)
        except (KeyError,ValueError) as error:errors.append(str(error));continue
        for shard in peaks:
            value=units[shard]['fraction'];peaks[shard]=max(peaks[shard],value);history[shard].append((x['time']-release,value))
        if x['loadHost']['memoryFraction']>=.8:errors.append('Load host memory >=80%')
        if any(x[k] for k in ('oom','restarted','swapping','networkExhausted','fdExhausted')):errors.append('resource safety flag')
    if len(business)<118 or not business or business[-1]['time']<release+119:errors.append('120-second qualification observation incomplete')
    gaps=[b['time']-a['time'] for a,b in zip(business,business[1:])]
    if any(x>2 for x in gaps):errors.append('memory qualification sampling gap')
    trends={}
    for shard,values in history.items():
        if peaks[shard]>=.8:errors.append('main '+shard+' peak >=80%')
        first=[v for t,v in values if 90<=t<95];last=[v for t,v in values if 115<=t<=122]
        growth=(sum(last)/len(last)-sum(first)/len(first)) if first and last else None
        trends[shard]=growth
        if growth is None or growth>.05:errors.append('main '+shard+' final trend unavailable or >5 percentage points')
    if summary['dropped']:errors.append('dropped iterations')
    if any(x['metric']=='phase14_results' and x['tags'][2] in ('system_error','unexpected_contract') and x['count'] for x in summary['counts']):errors.append('HTTP/system or assertion errors')
    if not invariants['passed']:errors.append('database invariants')
    return {'kind':'memory_qualification','status':'fail' if errors else 'pass','formalCapacity':False,
            'errors':sorted(set(errors)),'peaks':peaks,'last30SecondsGrowthFraction':trends,
            'observedBusinessSamples':len(business),'businessWindowSeconds':BUSINESS_SECONDS}


def qualification(args,t,env):
    """Run the unchanged U1 script once; stop after its original first ramp."""
    from run_phase14 import execute_case
    from phase14_campaign import write,current_fingerprint
    claim=env.runtime/'memory-qualification-once.json'
    with claim.open('x') as f:json.dump({'runId':env.root.name,'root':str(env.root)},f)
    write(env.root/'memory-qualification-plan.json',{'formalU1Unchanged':True,'mainVUs':10000,'mainShards':4,
          'globalProbeVUs':384,'businessSeconds':BUSINESS_SECONDS,'admission':'original U1 first ramp 0 to 2500 over 120 seconds',
          'notAStable2500Plateau':True,'formalCapacity':False,'mainMemoryBytes':MAIN_BYTES,'probeMemoryBytes':PROBE_BYTES})
    fingerprint=current_fingerprint(env)
    execute_case(args,t,env)
    spec=json.loads((env.root/'spec.json').read_text());summary=json.loads((env.root/'global-summary.json').read_text())
    samples=[json.loads(x) for x in (env.root/'samples/host-and-container.jsonl').read_text().splitlines()]
    inv=env.invariants();write(env.root/'memory-final-invariants.json',inv)
    result=assess(samples,env.root.name,spec['releaseAtMs']/1000,summary,inv)
    result.update(fingerprint=fingerprint,runId=env.root.name,stopReasons=summary['stopReasons'])
    write(env.root/'memory-qualification.json',result)
    # Always verify and restore known DB/Redis baseline after diagnostic business.
    restored=env.child(env.root/'baseline-restoration');restored.reset(yes=True,snapshot=restored.data/'base.dump')
    write(env.root/'memory-restoration.json',json.loads((restored.root/'reset.json').read_text()))
    return 0 if result['status']=='pass' else 1


def guard(args,env,immediate=True):
    import time
    from phase14_campaign import current_fingerprint,verify_hashes,verify_referenced_runs,preflight
    from phase14_fd import equivalent_fingerprint
    if not (args.yes and args.formal_approved and args.core and args.shards==4 and env.memory_resume):raise ValueError('memory resume authorization missing')
    path=Path(args.memory_evidence);m=json.loads((path/'memory-qualification.json').read_text())
    if m['status']!='pass' or m['formalCapacity']:raise ValueError('memory qualification did not pass')
    restore=json.loads((path/'memory-restoration.json').read_text())
    if not restore['passed']:raise ValueError('memory baseline restoration failed')
    current=current_fingerprint(env)
    if current!=m['fingerprint']:raise ValueError('memory-qualified source or input changed')
    baseline=json.loads((env.runtime/'memory-baseline.json').read_text())
    if time.time()>=baseline['hardDeadlineAt']:raise ValueError('memory round time budget exhausted')
    for ref in baseline['originalEvidence']:verify_hashes(ref['root'],ref['hashes'])
    q=json.loads(Path(baseline['qualification']).read_text())
    equivalent_fingerprint(q['fingerprint'],current)
    for kind in ('g0','smoke'):verify_referenced_runs(q[kind]['root'],kind)
    allowed={'performance/scripts/phase14_memory.py','performance/scripts/phase14_dual.py','performance/scripts/phase14_dual_sampling.py','performance/scripts/run_phase14.py','performance/scripts/phase14_campaign.py'}
    changed=env.load.run(['git','diff','--name-only',baseline['sourceBefore'],'HEAD']).stdout.decode().splitlines()
    if any(p not in allowed and not p.startswith(('performance/tests/','docs/')) for p in changed):raise ValueError('unqualified memory source change')
    if immediate:
        fresh=preflight(env)
        if not fresh['passed'] or fresh['diskFreeBytes']['load']<q['longestScenarioDiskBudgetBytes']:raise ValueError('memory immediate preflight failed')
    return q
