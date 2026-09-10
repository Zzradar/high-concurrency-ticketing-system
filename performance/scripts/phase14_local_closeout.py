"""Fresh v3 incremental smoke matrix; unaffected O/H/E evidence is not rerun."""
import argparse
from datetime import datetime,timezone
import secrets
from run_phase14 import Environment,RESULTS,load_targets,execute_case,write,compare_background

def main():
    t=load_targets(smoke=True);root=RESULTS/('phase14-v3-closeout-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'));root.mkdir()
    records=[];passed={'U1':[],'U2':[]};controls={}
    jobs=[('U1',{'round':i}) for i in (0,1)]+[('U2',{'round':i,'shards':i+1}) for i in (0,1)]+[('J1',{'window':i}) for i in range(3)]+[('S1',{})]+[(case,{'control_only':control}) for case in ('L1','L2') for control in (True,False)]
    for case,overrides in jobs:
        run_id='phase14-smoke-'+case.lower()+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(3)
        args=argparse.Namespace(case=case,round=0,window=0,path='formal',session_count=1,shards=1,control_only=False,passed_u1=passed['U1'],passed_u2=passed['U2'])
        for key,value in overrides.items():setattr(args,key,value)
        env=Environment(t,RESULTS/run_id)
        try:code=execute_case(args,t,env)
        except Exception as error:
            write(env.root/'execution-error.json',{'type':type(error).__name__,'message':str(error)});code=1
        records.append({'case':case,'arguments':overrides,'runId':run_id,'functionalSmoke':code==0})
        write(root/'campaign.json',{'mode':'smoke','targetsSha256':t['sourceSha256'],'runs':records})
        if code:return code
        if case in passed:passed[case]=[t['burst']['users']]
        if case.startswith('L'):
            if args.control_only:controls[case]=env.root
            else:write(env.root/'login-background-comparison.json',compare_background(controls[case],env.root,t))
    return 0
if __name__=='__main__':raise SystemExit(main())
