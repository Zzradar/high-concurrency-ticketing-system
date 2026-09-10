"""Exact-label stop authorized on 2026-09-10; never removes containers or volumes."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

PROJECTS={'phase12-2b-gate','phase12-approved','phase12-gate'}
ROOT=Path(__file__).resolve().parents[2]

def select(containers):
    return [x for x in containers if (x.get('Config',{}).get('Labels') or {}).get('com.docker.compose.project') in PROJECTS]

def safe(x):
    labels=x['Config'].get('Labels') or {}
    return {'id':x['Id'],'name':x['Name'],'image':x['Config']['Image'],'imageId':x['Image'],
        'project':labels.get('com.docker.compose.project'),
        'composeFiles':labels.get('com.docker.compose.project.config_files'),
        'composeWorkingDirectory':labels.get('com.docker.compose.project.working_dir'),
        'state':{k:x['State'].get(k) for k in ('Status','Running','Paused','Restarting','Dead','ExitCode','StartedAt','FinishedAt')},
        'health':x['State'].get('Health',{}).get('Status'), 'restartCount':x['RestartCount'],
        'ports':x['NetworkSettings'].get('Ports'), 'portBindings':x['HostConfig'].get('PortBindings'),
        'mounts':sorted([dict(m) for m in x['Mounts']],key=lambda m:(m['Destination'],m['Source']))}

def swap_stable(samples):
    return bool(samples) and all(x[k]==samples[0][k] for x in samples for k in ('pswpin','pswpout'))

class Audit:
    def __init__(self,root,*,resume=False):self.root=root;root.mkdir(parents=True,exist_ok=resume)
    def save(self,name,value):
        (self.root/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    def docker(self,*args):
        if any(x in ('down','rm','prune','-v','--volumes') for x in args):raise ValueError('prohibited Docker operation')
        with (self.root/'commands.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps({'at':datetime.now(timezone.utc).isoformat(),'argv':['docker',*args]})+'\n')
        result=subprocess.run(['docker',*args],capture_output=True,text=True,encoding='utf-8',timeout=90)
        if result.returncode:raise RuntimeError(result.stderr[:1000])
        return result.stdout
    def inventory(self):
        ids=self.docker('ps','-aq','--no-trunc').split()
        return json.loads(self.docker('inspect',*ids)) if ids else []
    def host(self,sampler):
        raw=self.docker('exec',sampler,'cat','/proc/meminfo','/proc/vmstat','/proc/stat')
        result={'utc':datetime.now(timezone.utc).isoformat(),'monotonic':time.monotonic()}
        for line in raw.splitlines():
            fields=line.split()
            if not fields:continue
            if fields[0] in ('MemTotal:','MemAvailable:','MemFree:','SwapTotal:','SwapFree:','SwapCached:'):
                result[fields[0][:-1]+'Bytes']=int(fields[1])*1024
            elif fields[0] in ('pswpin','pswpout'):result[fields[0]]=int(fields[1])
            elif fields[0]=='cpu':result['cpuTicks']=list(map(int,fields[1:]))
        if any(k not in result for k in ('cpuTicks','pswpin','pswpout','MemAvailableBytes','SwapFreeBytes')):raise RuntimeError('incomplete host resource evidence')
        return result

def run(root):
    audit=Audit(root);before=audit.inventory();chosen=select(before)
    if {x['Config']['Labels']['com.docker.compose.project'] for x in chosen}!=PROJECTS:raise RuntimeError('one or more authorized projects absent')
    sampler=[x for x in before if (x['Config'].get('Labels') or {}).get('com.docker.compose.project')=='phase14-capacity' and (x['Config'].get('Labels') or {}).get('com.docker.compose.service')=='postgres' and x['State']['Running']]
    if len(sampler)!=1:raise RuntimeError('dedicated read-only host sampler missing')
    sampler=sampler[0]['Id']
    audit.save('containers-before.json',[safe(x) for x in before]);audit.save('selected-before.json',[safe(x) for x in chosen])
    volumes=sorted({m['Name'] for x in chosen for m in x['Mounts'] if m['Type']=='volume'})
    audit.save('volumes-before.json',json.loads(audit.docker('volume','inspect',*volumes)) if volumes else [])
    audit.save('host-before.json',audit.host(sampler))
    # Re-read every exact ID immediately before stopping; no names or prefix filters authorize a stop.
    checked=json.loads(audit.docker('inspect',*[x['Id'] for x in chosen]))
    if len(select(checked))!=len(chosen) or {x['Id'] for x in checked}!={x['Id'] for x in chosen}:raise RuntimeError('container identity/label changed')
    audit.save('selected-revalidated.json',[safe(x) for x in checked])
    running=[x['Id'] for x in checked if x['State']['Running']]
    if running:audit.docker('stop',*running)
    after=audit.inventory();audit.save('containers-after.json',[safe(x) for x in after]);audit.save('host-after.json',audit.host(sampler))
    retained=json.loads(audit.docker('volume','inspect',*volumes)) if volumes else []
    audit.save('volumes-after.json',retained)
    selected_ids={x['Id'] for x in chosen};after_by_id={x['Id']:safe(x) for x in after};differences=[]
    for x in before:
        if x['Id'] in selected_ids:continue
        previous=safe(x);current=after_by_id.get(x['Id'])
        if current!=previous:differences.append({'before':previous,'after':current})
    new_ids=set(after_by_id)-{x['Id'] for x in before}
    checks={'selectedStopped':all(x['Id'] in after_by_id and not after_by_id[x['Id']]['state']['Running'] for x in chosen),
        'volumesRetained':{x['Name'] for x in retained}==set(volumes),
        'otherContainersUnchanged':not differences and not new_ids,'otherDifferences':differences,'newContainerIds':sorted(new_ids)}
    audit.save('stop-checks.json',checks)
    print(json.dumps({'stopped':len(running),'volumes':len(volumes),**{k:checks[k] for k in ('selectedStopped','volumesRetained','otherContainersUnchanged')}}),flush=True)
    if not all(checks[k] for k in ('selectedStopped','volumesRetained','otherContainersUnchanged')):raise RuntimeError('post-stop audit mismatch; no load permitted')
    return observe(audit,sampler)


def observe(audit,sampler):
    # Let stop-related paging settle. Require 30 seconds of >=90% measured CPU idle.
    idle=[];since=None;deadline=time.monotonic()+120;previous=audit.host(sampler)
    while time.monotonic()<deadline:
        time.sleep(5);current=audit.host(sampler);delta=[b-a for a,b in zip(previous['cpuTicks'],current['cpuTicks'])]
        total=sum(delta[:8]);idle_fraction=(delta[3]+delta[4])/total if total>0 else 0
        current['idleFraction']=idle_fraction;idle.append(current)
        if idle_fraction>=.9:
            if since is None:since=current['monotonic']
        else:since=None
        previous=current
        if since is not None and current['monotonic']-since>=30:break
    audit.save('settling.json',idle)
    if since is None or previous['monotonic']-since<30:raise RuntimeError('host not idle within settling deadline; no load permitted')
    print('Host idle; starting two fresh 60-second swap windows.',flush=True)
    windows=[]
    for index in range(2):
        samples=[audit.host(sampler)];start=samples[0]['monotonic']
        while time.monotonic()-start<60:
            time.sleep(min(5,max(.01,60-(time.monotonic()-start))));samples.append(audit.host(sampler))
        record={'window':index+1,'seconds':samples[-1]['monotonic']-start,'stable':swap_stable(samples),'samples':samples}
        windows.append(record);audit.save(f'window-{index+1}.json',record)
        print(json.dumps({k:record[k] for k in ('window','seconds','stable')}),flush=True)
    stable=all(x['stable'] for x in windows) and swap_stable([sample for window in windows for sample in window['samples']])
    audit.save('gate.json',{'passed':stable,'windows':[{'window':x['window'],'stable':x['stable'],'seconds':x['seconds']} for x in windows],
        'next':'resource preflight then G0; local characterization only' if stable else 'STOP: no G0/U1; retain evidence and report'})
    return 0 if stable else 2

def resume_observation(root):
    if root.resolve().parent!=(ROOT/'performance/results').resolve() or not root.name.startswith('phase14-resource-release-'):
        raise ValueError('invalid evidence directory')
    audit=Audit(root,resume=True)
    before=json.loads((root/'containers-before.json').read_text(encoding='utf-8'))
    selected=json.loads((root/'selected-before.json').read_text(encoding='utf-8'))
    selected_ids={x['id'] for x in selected}
    current=[safe(x) for x in audit.inventory()];by_id={x['id']:x for x in current}
    for row in before:row['mounts']=sorted(row['mounts'],key=lambda m:(m['Destination'],m['Source']))
    unchanged=all(x['id'] in selected_ids or by_id.get(x['id'])==x for x in before) and set(by_id)=={x['id'] for x in before}
    stopped=all(x['id'] in by_id and by_id[x['id']]['project']==x['project'] and x['project'] in PROJECTS and not by_id[x['id']]['state']['Running'] for x in selected)
    oldvol=json.loads((root/'volumes-before.json').read_text(encoding='utf-8'));names=[x['Name'] for x in oldvol]
    newvol=json.loads(audit.docker('volume','inspect',*names)) if names else []
    retained={x['Name'] for x in newvol}==set(names)
    checks={'selectedStopped':stopped,'volumesRetained':retained,'otherContainersUnchanged':unchanged,'comparison':'mount lists normalized by destination/source; all contents still compared'}
    audit.save('stop-checks-revalidated.json',checks);audit.save('containers-revalidated.json',current);audit.save('volumes-revalidated.json',newvol)
    if not stopped or not retained or not unchanged:raise RuntimeError('revalidation failed; no load permitted')
    sampler=[x for x in current if x['project']=='phase14-capacity' and x['name']=='/phase14-capacity-postgres-1' and x['state']['Running']]
    if len(sampler)!=1:raise RuntimeError('dedicated sampler unavailable')
    audit.save('host-revalidated.json',audit.host(sampler[0]['id']))
    print(json.dumps(checks),flush=True)
    return observe(audit,sampler[0]['id'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--yes',action='store_true');parser.add_argument('--observe',type=Path);args=parser.parse_args()
    if not args.yes:print('Read-only plan: exact authorized project labels, stop exact IDs, audit, idle, two fresh 60-second windows.');raise SystemExit(0)
    destination=args.observe or ROOT/'performance/results'/('phase14-resource-release-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    try:raise SystemExit(resume_observation(destination) if args.observe else run(destination))
    except Exception as error:
        destination.mkdir(parents=True,exist_ok=True)
        (destination/'failure.json').write_text(json.dumps({'error':str(error),'loadPermitted':False}),encoding='utf-8')
        print('[FAIL] '+str(error),flush=True);raise SystemExit(1)
