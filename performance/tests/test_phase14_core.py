from copy import deepcopy
import json
from pathlib import Path
import sys,tempfile,time,unittest
from unittest.mock import Mock,patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'performance/scripts'))
from phase14_core import probe_budget,core_spec,core_jobs,core_plan,units,arm,verify_init_evidence
from phase14_initialization import Initialization
from phase14_model import load_targets
from run_phase14 import build_spec


class CoreTests(unittest.TestCase):
    def test_init_qualification_rejects_one_pass_and_fault_fixture(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)
            for q in ({'status':'pass','faultFixture':False,'runs':[{}]},
                      {'status':'pass','faultFixture':True,'runs':[{},{}]}):
                (p/'init-qualification.json').write_text(json.dumps(q))
                with patch('phase14_campaign.current_fingerprint',return_value={}):
                    with self.assertRaisesRegex(ValueError,'two consecutive'):verify_init_evidence(p,Mock())

    def test_deadline_prevents_new_generator_even_before_command_adaptation(self):
        from phase14_dual import DualEnvironment
        with patch('phase14_dual.time.time',return_value=200):
            with self.assertRaisesRegex(RuntimeError,'launch forbidden'):
                DualEnvironment.start_generator(Mock(deadline_at=199),[],None)

    def test_abort_failure_is_preserved_in_initialization_record(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError,'initial failure'):
                with Initialization(Path(folder),'test',['0'],9999999999999,lambda:time.sleep(.001),abort=Mock(side_effect=OSError('stop error'))):
                    raise RuntimeError('initial failure')
            record=json.loads((Path(folder)/'initialization.json').read_text())
            self.assertEqual(record['status'],'fail');self.assertIn('abort failed: stop error',record['error'])

    def test_probe_budget_is_rate_times_deadline_with_static_headroom(self):
        budget=probe_budget(load_targets())
        self.assertEqual(len(budget),4)
        for row in budget.values():
            self.assertEqual(row['rate']*row['hardDeadlineSeconds'],60)
            self.assertEqual(row['preAllocatedVUs'],96)
        s=core_spec(load_targets(),'U1','test')
        for name,row in budget.items():
            self.assertEqual(s['scenarios'][name]['preAllocatedVUs'],row['preAllocatedVUs'])
            self.assertEqual(s['scenarios'][name]['maxVUs'],row['preAllocatedVUs'])

    def test_every_main_executor_business_count_and_identity_is_unchanged(self):
        for smoke in (False,True):
            t=load_targets(smoke=smoke)
            for case,changes in core_jobs():
                kwargs={'round_index':changes.get('round',0),'window_index':changes.get('window',0),
                    'path':changes.get('path','formal'),'control_only':changes.get('control_only',False),
                    'passed_u1':[t['burst']['users']],'passed_u2':[t['burst']['users']]}
                before=build_spec(t,case,'test',**kwargs);after=core_spec(t,case,'test',**kwargs)
                for key in ('targets','mapping','plan','loadSeconds','startupPlan'):
                    self.assertEqual(before[key],after[key])
                for name,scenario in before['scenarios'].items():
                    actual=deepcopy(after['scenarios'][name])
                    if name.startswith('control_') or name=='payment':
                        actual['preAllocatedVUs']=scenario['preAllocatedVUs'];actual.pop('maxVUs')
                    self.assertEqual(scenario,actual)

    def test_four_main_segments_and_exactly_one_global_probe(self):
        t=load_targets();u=units(4,t,'U1')
        self.assertEqual([x['shard'] for x in u],['0','1','2','3','4'])
        self.assertEqual(sum(x['role']=='probe' for x in u),1)
        self.assertEqual(u[-1]['segment'],'0:1')
        self.assertEqual(len(units(4,t,'G0')),4)
        self.assertEqual([x['segment'] for x in u[:4]],['0:1/4','1/4:1/2','1/2:3/4','3/4:1'])

    def test_core_plan_is_the_requested_ten_jobs_with_full_windows(self):
        p=core_plan(load_targets())
        self.assertEqual(len(p['jobs']),10)
        self.assertEqual([x['case'] for x in p['jobs']],['U1','U2','O1','O1','O1','H1','H1','H3','L2','L2'])
        self.assertEqual([x['businessSecondsUpperBound'] for x in p['jobs'][:5]],[1740,1740,60,30,10])
        self.assertEqual(sum(v for k,v in p['jobs'][1]['logicalPlan'].items() if k.startswith('refresh_')),185000)
        checked=json.loads((ROOT/'docs/phase14_core_plan.json').read_text(encoding='utf-8'))
        self.assertEqual(checked,p)

    def test_initialization_deadline_precedes_business_release_and_abort(self):
        spec=core_spec(load_targets(),'U1','test');arm(spec,100)
        self.assertEqual(spec['initializationDeadlineAtMs'],130000)
        self.assertEqual(spec['releaseAtMs'],160000)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);log=(root/'console.log').open('wb');abort=Mock()
            with self.assertRaisesRegex(RuntimeError,'frozen release'):
                with Initialization(root,'test',['0'],160000,lambda:time.sleep(.001),deadline_at_ms=130000,abort=abort) as i:
                    with patch('phase14_initialization.time.time',return_value=131):
                        i.wait(Mock(poll=Mock(return_value=None)),log,'0')
            log.close();abort.assert_called_once()
            d=json.loads((root/'initialization.json').read_text())
            self.assertEqual(d['status'],'fail');self.assertEqual(d['deadlineAtMs'],130000)


if __name__=='__main__':unittest.main()
