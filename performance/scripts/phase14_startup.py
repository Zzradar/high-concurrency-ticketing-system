"""Read-only, separately evidenced page initialization before the L comparison clock."""
import gzip
import json
import shutil
import subprocess
import time
from pathlib import Path

from phase14_evidence import aggregate, sha256, StopGuard
from phase14_sampling import Sampler


def background_initialization(spec):
    rows=[]
    for name,m in spec['mapping'].items():
        if not name.startswith('background_'):continue
        count=min(m['users'],m['count']) if name=='background_refresh' else m['count']
        rows.append({'name':name,'count':count,'slice':m['slice'],
                     'seatSlice':'main' if name=='background_refresh' else m['slice']})
    return rows


def warm_background(env,spec):
    from run_phase14 import write, check_startup, ROOT, COMPOSE
    root=env.root/'background-startup';root.mkdir()
    rows=background_initialization(spec);t=env.t
    warm={'targets':t,'case':spec['case'],'runId':env.root.name+'/background-startup','idempotencyNamespace':env.root.name,
          'releaseAtMs':0,'scenarios':{},'mapping':{},'plan':{}}
    for r in rows:
        # All actual timed identities are initialized once, in disjoint slices.
        n=r['count'];warm['mapping'][r['name']]=r;warm['plan'][r['name']]=n
        warm['scenarios'][r['name']]={'executor':'shared-iterations','exec':'warmPage',
            'vus':1,'iterations':n,'maxDuration':'3600s'}
    n=sum(r['count'] for r in rows)
    plan={'users':n,'steps':{k:v*n for k,v in t['pageStartup']['stepCounts'].items()}}
    write(root/'spec.json',warm);write(root/'plan.json',{'identities':rows,**plan,'timedLoadStarted':False})
    shutil.copytree(ROOT/'performance/k6',root/'k6-source')
    overlay=root/'compose-source.json'
    write(overlay,{'services':{'k6':{'volumes':[{'type':'bind','source':str((root/'k6-source').resolve()),'target':'/scripts','read_only':True}]}}})
    folder=root/'shards'/'0';folder.mkdir(parents=True)
    name=env.project+'-startup-'+env.root.name
    argv=['docker','compose','-p',env.project,'-f',str(COMPOSE),'-f',str(overlay),'run','--no-deps','--name',name,
          '-e','SHARD=0','-e','PHASE14_ROLE=main','-e',f'PHASE14_SPEC=/results/{env.root.name}/background-startup/spec.json',
          'k6','run','--out',f'json=/results/{env.root.name}/background-startup/shards/0/raw.json','workloads/phase14-startup.js']
    write(root/'command.json',argv);sampler=Sampler(env);guard=StopGuard(t);errors=[];begin=time.time()
    with (folder/'console.log').open('wb') as log:
        proc=env.start_generator(argv,log) if getattr(env,'dual',False) is True else subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT,env=env.env,cwd=ROOT)
        try:
            while proc.poll() is None:
                sample,_,_,_=sampler.sample()
                with (root/'samples.jsonl').open('a') as stream:stream.write(json.dumps(sample)+'\n')
                errors+=guard.sample(sample)
                if time.time()-begin>3600:errors.append('startup deadline')
                if errors:break
        finally:
            if getattr(env,'dual',False) is True:env.stop_generators([name])
            if proc.poll() is None:
                inspected=json.loads(env.command(['docker','inspect',name]).stdout)[0]
                if inspected['Config']['Labels'].get('com.docker.compose.project')!=env.project:raise ValueError('startup ownership mismatch')
                env.command(['docker','stop','--time','2',inspected['Id']])
            code=proc.wait(timeout=30)
    if code:errors.append('startup k6 exit '+str(code))
    raw=folder/'raw.json'
    if raw.exists():
        with raw.open('rb') as source,gzip.open(folder/'raw.json.gz','wb') as out:shutil.copyfileobj(source,out)
        (folder/'raw.json.gz.sha256').write_text(sha256(folder/'raw.json.gz'))
        summary=aggregate(root,[{'shard':'0'}],warm['plan']);check_startup(summary,plan)
        errors+=summary['errors']
        if any(r['metric']=='phase14_results' and r['tags'][2]!='business_success' and r['count'] for r in summary['counts']):errors.append('startup request failure')
        write(root/'global-summary.json',summary)
    else:errors.append('missing startup raw evidence')
    write(root/'check.json',{'passed':not errors,'errors':errors,'warnings':guard.warnings,'seconds':time.time()-begin,
                            'finishedAtMs':time.time()*1000,'capacity':'not_applicable'})
    if errors:raise RuntimeError('background startup failed; preserved before timed load: '+str(errors))
