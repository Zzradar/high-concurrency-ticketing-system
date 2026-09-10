"""ABBA no-op comparison; sampling disabled only for bounded no-op control legs."""
import gzip
import json
import subprocess
import sys
import time
from datetime import datetime,timezone
from pathlib import Path
from run_phase14 import Environment,ROOT,RESULTS,COMPOSE,load_targets,write,save_sample
from phase14_sampling import Sampler,LightPostgresSampler
from phase14_evidence import StopGuard,percentile,sha256

SCRIPT="""import http from 'k6/http';
import exec from 'k6/execution';
import {Counter} from 'k6/metrics';
const failures=new Counter('noop_failures');
const n=Number(__ENV.PLAN),seconds=Number(__ENV.SECONDS);
export const options={scenarios:{noop:{executor:'constant-arrival-rate',rate:n,timeUnit:seconds+'s',duration:seconds+'s',preAllocatedVUs:Number(__ENV.VUS)}},systemTags:['status','method','name','scenario'],summaryTrendStats:['p(50)','p(95)','p(99)','max']};
export default function(){if(exec.scenario.iterationInTest>=n)return;const r=http.get('http://noop:8080/health',{timeout:'5s',tags:{name:'GET /health'}});failures.add(r.status===200?0:1);}
"""

def compare(rows,limit):
    groups={enabled:[r for r in rows if r['sampling']==enabled] for enabled in (False,True)}
    def median(key,enabled):return percentile([r[key] for r in groups[enabled]],.5)
    ratios={k:median(k,True)/median(k,False)-1 for k in ('p95Ms','p99Ms')}
    return {'relativeIncrease':ratios,'limit':limit,'passed':all(v<=limit for v in ratios.values()),
        'sampleSizeLimited':True,'measurement_validity':'fail','capacity':'not_applicable',
        'reason':'local no-op characterization; co-located control does not establish a formal overhead bound'}

def stop_owned(env,name):
    item=json.loads(env.command(['docker','inspect',name]).stdout)[0]
    if item['Config']['Labels'].get('com.docker.compose.project')!=env.project:raise ValueError('ownership mismatch')
    env.command(['docker','stop',item['Id']])


def baseline_seconds(t,full=False):
    return load_targets()['calibration']['baselineSeconds'] if full else t['calibration']['baselineSeconds']


def main():
    t=load_targets(smoke=True);root=RESULTS/('phase14-sampling-overhead-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    env=Environment(t,root);env.validate();env.compose('up','-d','noop')
    source=root/'k6-source';source.mkdir();(source/'overhead.js').write_text(SCRIPT)
    override=root/'source-compose.json';write(override,{'services':{'k6':{'volumes':[{'type':'bind','source':str(source.resolve()),'target':'/scripts','read_only':True}]}}})
    seconds=baseline_seconds(t,'--formal-baseline-duration' in sys.argv);write(root/'input.json',{'mode':'smoke','baselineSeconds':seconds,'durationSource':'formal calibration baseline' if '--formal-baseline-duration' in sys.argv else 'smoke baseline','arrivalRate':t['burst']['users']/min(t['burst']['windowsSeconds']),'order':['off','on','on','off']});plan=int(t['burst']['users']/min(t['burst']['windowsSeconds'])*seconds);rows=[]
    for i,enabled in enumerate((False,True,True,False)):
        folder=root/str(i);folder.mkdir();env.root=folder
        sampler=Sampler(env);guard=StopGuard(t);before,pg,rd,_=sampler.sample();save_sample(folder,before,pg,rd)
        name=env.project+'-overhead-'+root.name+'-'+str(i)
        args=['docker','compose','-p',env.project,'-f',str(COMPOSE),'-f',str(override.resolve()),'run','--no-deps','--name',name,
            '-e','PLAN='+str(plan),'-e','SECONDS='+str(seconds),'-e','VUS='+str(t['burst']['users']+t['generator']['maxShards']),
            'k6','run','--out','json=/results/'+root.name+'/'+str(i)+'/raw.json','/scripts/overhead.js']
        write(folder/'command.json',args);stops=[];light=LightPostgresSampler(env,t['generator']['hotspotSampleSeconds']).start() if enabled else None
        with (folder/'console.log').open('wb') as log:
            process=subprocess.Popen(args,env=env.env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+seconds+30
                while process.poll() is None:
                    if enabled:
                        x,pg,rd,_=sampler.sample();save_sample(folder,x,pg,rd);stops+=guard.sample(x)
                    else:time.sleep(.1)
                    if stops or time.monotonic()>deadline:
                        stop_owned(env,name);stops.append('bounded no-op stopped');break
                code=process.wait(timeout=20)
            finally:
                if process.poll() is None:
                    stop_owned(env,name);process.wait(timeout=20)
                if light:write(folder/'light.json',light.stop())
        after,pg,rd,_=sampler.sample();save_sample(folder,after,pg,rd);stops+=guard.sample(after)
        points=[];dropped=0;failures=0
        with (folder/'raw.json').open(encoding='utf-8') as f:
            for line in f:
                x=json.loads(line)
                if x.get('type')!='Point':continue
                if x['metric']=='http_req_duration':points.append(x['data']['value'])
                if x['metric']=='dropped_iterations':dropped+=x['data']['value']
                if x['metric']=='noop_failures':failures+=x['data']['value']
        with gzip.open(folder/'raw.json.gz','wb') as f:f.write((folder/'raw.json').read_bytes())
        write(folder/'raw-sha256.json',{'sha256':sha256(folder/'raw.json.gz')})
        row={'sampling':enabled,'planned':plan,'requests':len(points),'dropped':dropped,'failures':failures,'exitCode':code,
            'p95Ms':percentile(points,.95),'p99Ms':percentile(points,.99),'stopReasons':stops,'warnings':guard.warnings}
        rows.append(row);write(root/'legs.json',rows)
        if code or stops or failures or dropped or len(points)!=plan:raise AssertionError('no-op delivery/safety gate failed')
    result=compare(rows,t['generator']['maxSamplingOverheadFraction']);write(root/'comparison.json',result);print(json.dumps(result))
    return 0
if __name__=='__main__':raise SystemExit(main())
