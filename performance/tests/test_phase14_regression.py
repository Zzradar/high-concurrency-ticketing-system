import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from phase14_regression import RedisFixture

class RegressionFixtureTests(unittest.TestCase):
    def test_legacy_redis_restart_preserves_container_and_assertions(self):
        with tempfile.TemporaryDirectory() as tmp:
            env=Mock(root=Path(tmp));env.compose.return_value.stdout=b''
            run=RedisFixture(env)
            for args in [('kill','redis'),('rm','-f','redis'),('up','-d','redis')]:run(*args)
            self.assertEqual([c.args for c in env.compose.call_args_list],[('stop','redis'),('start','redis')])
            self.assertTrue((Path(tmp)/'redis-fixture-adaptation.json').is_file())
    def test_unexpected_or_other_service_rejected(self):
        run=RedisFixture(Mock())
        for args in [('rm','-f','redis'),('down',),('stop','backend'),('stop','unrelated'),('prune',)]:
            with self.assertRaises(ValueError):run(*args)

class ExporterFixtureTests(unittest.TestCase):
    def test_metric_selects_exact_series_and_state(self):
        from phase14_exporter_fixture import metric
        raw='pg_backend_activity_waiting{state="idle"} 0\npg_backend_activity_waiting{state="active"} 2\npg_backend_activity_waiting_extra 99\n'
        self.assertEqual(metric(raw,'pg_backend_activity_waiting',state='idle'),0)
        self.assertEqual(metric(raw,'pg_backend_activity_waiting',state='active'),2)
        self.assertEqual(metric(raw,'pg_backend_activity_waiting'),2)

class SamplingComparisonTests(unittest.TestCase):
    def test_short_control_cannot_claim_capacity_even_below_overhead_limit(self):
        from phase14_sampling_overhead import compare
        rows=[{'sampling':False,'p95Ms':10,'p99Ms':20},{'sampling':True,'p95Ms':10.2,'p99Ms':20.1}]*2
        result=compare(rows,.05)
        self.assertTrue(result['passed']);self.assertEqual(result['capacity'],'not_applicable')
        self.assertEqual(result['measurement_validity'],'fail')
        rows[1]={**rows[1],'p95Ms':20};self.assertFalse(compare(rows,.05)['passed'])

class SimulationFailureFixtureTests(unittest.TestCase):
    def test_forced_failure_is_separate_service_and_does_not_change_main(self):
        from phase14_regression import failure_service
        model={'services':{'backend':{'environment':{'TICKETING_PAYMENT_PROVIDER':'simulation','TICKETING_PAYMENT_FORCE_OUTCOME':'SUCCESS'},'mem_limit':2147483648,'cpus':4}}}
        result=failure_service(model,18415)['services']['backend-failure']
        self.assertEqual(result['environment']['TICKETING_PAYMENT_FORCE_OUTCOME'],'FAILURE')
        self.assertEqual(model['services']['backend']['environment']['TICKETING_PAYMENT_FORCE_OUTCOME'],'SUCCESS')
        self.assertEqual(result['mem_limit'],2147483648);self.assertEqual(result['cpus'],4)
        self.assertEqual(result['ports'][0]['host_ip'],'127.0.0.1')

class LiveMetricsTests(unittest.TestCase):
    def test_missing_samples_dynamic_labels_and_inflight_are_not_accepted(self):
        from phase14_regression import check_live_metrics
        self.assertFalse(check_live_metrics('')['passed'])
        result=check_live_metrics('ticketing_flow_requests_in_flight{flow="auth",user="private"} 1\n')
        self.assertFalse(result['passed']);self.assertEqual(result['invalidLabels'],[['user','private']])
        self.assertTrue(result['nonzeroInflight'])

class NoopCleanupTests(unittest.TestCase):
    def test_cleanup_reinspects_project_and_uses_exact_id(self):
        import json
        from phase14_sampling_overhead import stop_owned
        env=Mock(project='phase14-capacity')
        env.command.return_value.stdout=json.dumps([{'Id':'exact-id','Config':{'Labels':{'com.docker.compose.project':'other'}}}]).encode()
        with self.assertRaises(ValueError):stop_owned(env,'named')
        self.assertEqual(env.command.call_count,1)
        env.command.return_value.stdout=json.dumps([{'Id':'exact-id','Config':{'Labels':{'com.docker.compose.project':'phase14-capacity'}}}]).encode()
        stop_owned(env,'named');self.assertEqual(env.command.call_args.args,(['docker','stop','exact-id'],))

class NoopBaselineTests(unittest.TestCase):
    def test_long_control_uses_existing_baseline_without_changing_smoke_input(self):
        from phase14_sampling_overhead import baseline_seconds
        from phase14_model import load_targets
        t=load_targets(smoke=True);before=t['calibration']['baselineSeconds']
        self.assertEqual(baseline_seconds(t),before)
        self.assertEqual(baseline_seconds(t,True),load_targets()['calibration']['baselineSeconds'])
        self.assertEqual(t['calibration']['baselineSeconds'],before)
