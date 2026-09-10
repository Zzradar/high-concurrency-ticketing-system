"""Reduced-input real k6 scheduling fixture using the production flow and guards."""
import argparse
from datetime import datetime,timezone
import secrets
from run_phase14 import build_spec,guard_delivery,execute_case,Environment,RESULTS,load_targets,write

def probe_spec(t,case,run_id,**kwargs):
    spec=build_spec(t,'G0',run_id,**kwargs)
    original=spec['deliverySchedule']['main']['businessExecutor']
    spec['scenarios']={'constant':original,'main':{'executor':'ramping-arrival-rate','exec':'control','startRate':0,
        'timeUnit':'2s','preAllocatedVUs':20,'stages':[{'target':20,'duration':'2s'}],'gracefulStop':'30s'}}
    spec['mapping']={'constant':{'count':20,'step':'health'},'main':{'count':10,'step':'health'}}
    spec['plan']={'constant':20,'main':10};spec['loadSeconds']=2
    spec['deliverySchedule']=guard_delivery(spec['scenarios'],t)
    spec['fixture']='production executors/flow, reduced no-op counts; not capacity'
    return spec

def main():
    t=load_targets(smoke=True);records=[]
    root=RESULTS/('phase14-delivery-probe-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'));root.mkdir()
    for shards in (1,2):
        run_id='phase14-smoke-g0-guard-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(3)
        args=argparse.Namespace(case='G0',round=0,window=0,path='formal',session_count=1,shards=shards)
        code=execute_case(args,t,Environment(t,RESULTS/run_id),spec_factory=probe_spec)
        records.append({'runId':run_id,'shards':shards,'passed':code==0});write(root/'results.json',records)
        if code:return code
    return 0
if __name__=='__main__':raise SystemExit(main())
