import json,copy,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'performance/scripts'))
from phase14_memory import MAIN_BYTES,PROBE_BYTES,OVERRIDE,main_shard,apply_main_override,validate_units,assess

class MemoryTests(unittest.TestCase):
    def units(self,fraction=.6):
        return [{'runId':'r','name':'container-'+str(i),'inspectLimit':PROBE_BYTES if i==4 else MAIN_BYTES,
            'cgroupLimit':PROBE_BYTES if i==4 else MAIN_BYTES,'fraction':fraction,'events':{'oom':0,'oom_kill':0}} for i in range(5)]
    def samples(self):
        return [{'time':i,'loadHost':{'memoryFraction':.6,'generatorCgroups':self.units()},
             **{k:False for k in ('oom','restarted','swapping','networkExhausted','fdExhausted')}} for i in range(121)]
    def test_only_segmented_main_changes(self):
        self.assertTrue(main_shard(['PHASE14_ROLE=main','--execution-segment','0:1/4']))
        self.assertFalse(main_shard(['PHASE14_ROLE=probe','--execution-segment','0:1']))
        self.assertFalse(main_shard(['PHASE14_ROLE=main']))
    def test_standard_overlay_matches_measured_bytes(self):
        self.assertEqual(OVERRIDE,{'services':{'k6':{'mem_limit':3221225472}}})
        self.assertEqual(PROBE_BYTES,2147483648)
    def test_overlay_keeps_probe_base_and_cpu(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);base=p/'base.json';base.write_text('{}')
            env=Mock(root=p,load_project='phase14-formal-load',models={'load':{'services':{'k6':{'mem_limit':str(PROBE_BYTES),'cpus':4}}}});env.role_file.return_value=str(base)
            env.docker.return_value=Mock(stdout=json.dumps({'services':{'k6':{'mem_limit':str(MAIN_BYTES),'cpus':4}}}).encode())
            original=copy.deepcopy(env.models)
            argv=['docker','compose','run','-e','PHASE14_ROLE=main','--execution-segment','0:1/4']
            result=apply_main_override(env,argv)
            self.assertEqual(env.models,original);self.assertLess(result.index('-f'),result.index('run'))
            model=json.loads((p/'main-memory.rendered.json').read_text());self.assertEqual(model['services']['k6'],{'mem_limit':str(MAIN_BYTES),'cpus':4})
    def test_actual_cgroup_and_inspect_required(self):
        validate_units(self.units(),'r')
        for field in ['inspectLimit','cgroupLimit']:
            rows=self.units();rows[0][field]=PROBE_BYTES
            with self.assertRaises(ValueError):validate_units(rows,'r')
        with self.assertRaises(ValueError):validate_units(self.units()[:4],'r')
    def test_short_result_requires_full_observation_and_headroom(self):
        summary={'dropped':0,'counts':[]};inv={'passed':True}
        self.assertEqual(assess(self.samples(),'r',0,summary,inv)['status'],'pass')
        self.assertEqual(assess(self.samples()[:30],'r',0,summary,inv)['status'],'fail')
        rows=self.samples();rows[100]['loadHost']['generatorCgroups'][0]['fraction']=.8
        self.assertEqual(assess(rows,'r',0,summary,inv)['status'],'fail')
        rows=self.samples()
        for x in rows[115:]:x['loadHost']['generatorCgroups'][1]['fraction']=.66
        self.assertEqual(assess(rows,'r',0,summary,inv)['status'],'fail')
    def test_frozen_formal_plan_is_unchanged(self):
        from phase14_core import core_plan
        from phase14_model import load_targets
        self.assertEqual(core_plan(load_targets()),json.loads((ROOT/'docs/phase14_core_plan.json').read_text()))

if __name__=='__main__':unittest.main()
