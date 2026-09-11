"""Cross-artifact checks: an interrupted fragment must not become capacity."""
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]


class FdDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.result=json.loads((ROOT/'docs/phase14_fd_resume_results.json').read_text(encoding='utf-8'))

    def test_invalid_fragment_preserves_all_ten_jobs_and_no_capacity_claim(self):
        a=self.result;rows=a['campaign']['runs']
        self.assertEqual(len(rows),10)
        self.assertEqual(rows[0]['status'],'invalid_measurement')
        self.assertTrue(all(row['status']=='not_run' for row in rows[1:]))
        self.assertIsNone(a['formalThroughput']);self.assertIsNone(a['formalBusinessFailureRate'])
        self.assertFalse(a['serviceCapacityProven']);self.assertFalse(a['full24Completed'])
        self.assertEqual(a['verdict']['capacity']['status'],'not_applicable')

    def test_fd_fix_and_resource_stop_are_distinct(self):
        a=self.result
        self.assertEqual(a['fd']['after'],{'soft':65535,'hard':65535})
        self.assertLess(a['fd']['peakFraction'],.85)
        self.assertEqual(a['fd']['errorTimestamps'],[])
        self.assertIn('invalid generator memory',a['stopReasons'])
        self.assertFalse(a['resources']['business']['oom'])
        self.assertFalse(a['finalCorrectness']['passed'])
        self.assertTrue(all(value==0 for value in a['finalCorrectness']['global'].values()))
        self.assertTrue((ROOT/a['images']['resourceCurve']).is_file())
        config=json.loads((ROOT/'docs/phase14_fd_compose_redacted.json').read_text())
        self.assertEqual(config['measurementCommit'],a['sourceHead'])
        self.assertEqual(config['evidence']['fd-rendered-role-compose.json']['redactedContent']['services']['backend']['ulimits']['nofile'],a['fd']['after'])

    def test_reuse_and_cleanup_have_explicit_evidence(self):
        a=self.result;d=a['deltaQualification'];c=a['cleanup']
        self.assertEqual(d['kind'],'phase14-fd-delta')
        self.assertEqual(d['measurementCommit'],a['sourceHead'])
        self.assertNotEqual(d['originalQualification']['measurementCommit'],a['sourceHead'])
        self.assertEqual(len(d['originalQualification']['sha256']),64)
        self.assertFalse(a['tests']['fullSuiteRerun'])
        self.assertTrue(all(row['running']==0 for row in c['services']['containers'].values()))
        self.assertTrue(c['ssh']['load']['negativeAuthenticationCheck'])
        self.assertFalse(c['ssh']['load']['remainingPrivateKey'])


if __name__=='__main__':unittest.main()
