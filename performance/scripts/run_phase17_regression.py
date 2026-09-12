"""Reuse the unchanged Phase14 G0/U1/U2 smoke model in a new private project.
The current image is built from the Phase17 Release binary.
Never points at a pre-existing Phase14 project or modifies its dataset/results.
"""
import argparse,json,sys
from pathlib import Path
import run_phase14 as phase14
from phase14_model import load_targets
ROOT=Path(__file__).resolve().parents[2]
def main():
    parser=argparse.ArgumentParser();parser.add_argument('variant',choices=['current']);args=parser.parse_args()
    phase14.GENERATED=ROOT/'performance/generated/phase17-comparison'
    targets=load_targets(smoke=True)
    targets['environment']['localPort']=18137
    targets['environment']['prometheusPort']=19137
    project='phase14-phase17-'+args.variant
    override=ROOT/'backend/build/phase17'/('compose-'+args.variant+'.json')
    override.write_text(json.dumps({'services':{'backend':{'image':'phase17-'+args.variant+':local','healthcheck':{'test':['CMD','python3','-c',"import json,urllib.request;assert json.load(urllib.request.urlopen('http://127.0.0.1:8080/health'))=={'database':'up','status':'ok'}"]}}}}),encoding='utf-8')
    class Environment(phase14.Environment):
        def compose(self,*arguments,**kwargs):
            return self.command(['docker','compose','-p',self.project,'-f',str(phase14.COMPOSE),'-f',str(override),*arguments],**kwargs)
    prepare=Environment(targets,phase14.RESULTS/('phase17-'+args.variant+'-prepare'),project=project)
    if not (prepare.data/'base.dump').exists():prepare.prepare()
    records=[]
    try:
        for case in ['G0','U1','U2']:
            env=Environment(targets,phase14.RESULTS/('phase17-'+args.variant+'-'+case.lower()),project=project)
            options=argparse.Namespace(case=case,round=0,window=0,path='formal',session_count=1,shards=1,core=False,deadline_at=None)
            result=phase14.execute_case(options,targets,env)
            ids=json.loads(env.sql("SELECT COALESCE(json_agg(queryid),'[]') FROM pg_stat_statements WHERE query LIKE '%WITH sales_clock AS MATERIALIZED%' AND query NOT LIKE '%pg_stat_statements%';"))
            (env.root/'gate-query-ids.json').write_text(json.dumps(ids),encoding='utf-8')
            records.append({'case':case,'passed':result==0,'directory':str(env.root.relative_to(ROOT))})
            print(json.dumps(records[-1]),flush=True)
            if result:raise RuntimeError('Phase14 representative gate failed; evidence retained')
    finally:
        output=ROOT/'performance/experiments/phase17-admin-publishing';output.mkdir(parents=True,exist_ok=True)
        (output/(args.variant+'-runs.json')).write_text(json.dumps(records,indent=2),encoding='utf-8')
        prepare.compose('stop')
if __name__=='__main__':main()
