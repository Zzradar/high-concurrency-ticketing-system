import hashlib
import json
from pathlib import Path
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[2]


class FinalDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result=json.loads((ROOT/'docs/phase14_dual_host_results.json').read_text(encoding='utf-8'))

    def test_report_identifies_the_actual_immutable_source(self):
        r=self.result
        tree=subprocess.check_output(['git','rev-parse',r['testedCommit']+'^{tree}'],cwd=ROOT).decode().strip()
        self.assertEqual(tree,r['testedTree'])
        targets=subprocess.check_output(['git','show',r['testedCommit']+':performance/baseline/phase14-targets.json'],cwd=ROOT)
        self.assertEqual(hashlib.sha256(targets).hexdigest(),r['targetsSha256'])

    def test_stop_preserves_the_complete_frozen_matrix_without_capacity_claim(self):
        r=self.result['formal'];plan=json.loads((ROOT/'docs/phase14_formal_plan.json').read_text(encoding='utf-8'))
        self.assertEqual(len(r['matrix']),24)
        self.assertEqual([(x['case'],x['arguments']) for x in r['matrix']],[(x['case'],x['arguments']) for x in plan['jobs']])
        self.assertEqual(r['matrix'][0]['status'],'invalid_measurement')
        self.assertTrue(all(x['status']=='not_run_after_stop' for x in r['matrix'][1:]))
        self.assertEqual(r['validCapacityRuns'],0)
        self.assertEqual(r['capacityConclusion'],'unavailable')
        self.assertEqual(len(r['initialization']['ready']),7)
        self.assertEqual(len(r['initialization']['shards']),8)
        self.assertLess(r['delivery']['main']['completed'],r['delivery']['main']['started'])

    def test_functional_smoke_keeps_valid_reset_and_http_metric_order(self):
        rows=self.result['smoke']['runs']
        self.assertEqual(len(rows),25)
        self.assertTrue(all(x['passed'] for x in rows))
        for row in rows:
            with self.subTest(run=row['runId']):
                if row['case']!='G0':
                    self.assertTrue(row['reset']['passed'])
                    self.assertEqual(row['reset']['redisDbsize'],0)
                if row['case'] not in ('G0','E1'):
                    self.assertTrue(row['postgresDeltaValid'])
                    self.assertEqual(row['dropped'],0)
                h=row['http']
                if h['httpSuccessRate'] is not None:
                    self.assertTrue(0<=h['httpSuccessRate']<=1)
                    q=h['httpDurationMs']
                    self.assertLessEqual(q['p50'],q['p95'])
                    self.assertLessEqual(q['p95'],q['p99'])

    def test_final_state_does_not_overwrite_interrupted_workflow_failure(self):
        r=self.result['formal']
        self.assertFalse(r['originalCorrectness']['passed'])
        self.assertFalse(r['finalAudit']['passed'])
        self.assertTrue(all(v==0 for v in r['finalAudit']['global'].values()))
        payment=r['finalAudit']['scoped']['paymentTerminal']
        self.assertEqual(payment['paid'],payment['orders'])
        self.assertEqual(payment['invalid'],0)
        self.assertNotEqual(payment['orders'],r['delivery']['payment']['completed'])


if __name__=='__main__':unittest.main()
