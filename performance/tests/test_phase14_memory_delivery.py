import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class MemoryDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / 'docs/phase14_memory_results.json').read_text(encoding='utf-8'))

    def test_failed_qualification_has_no_formal_capacity(self):
        a = self.data
        self.assertEqual(a['qualification']['status'], 'fail')
        self.assertFalse(a['qualification']['formalCapacity'])
        self.assertEqual(len(a['formalMatrix']['runs']), 10)
        self.assertTrue(all(x['status'] == 'not_run' for x in a['formalMatrix']['runs']))
        self.assertIsNone(a['formalThroughput'])
        self.assertIsNone(a['formalBusinessFailureRate'])
        self.assertLess(a['observedFragmentSeconds'], 120)

    def test_actual_limits_and_incomplete_trend_are_preserved(self):
        a = self.data
        for key, item in a['effectiveLimits'].items():
            expected = (2 if key == '4' else 3) * 1024**3
            self.assertEqual(item['inspectLimit'], expected)
            self.assertEqual(item['cgroupLimit'], expected)
        self.assertGreater(a['qualification']['peaks']['0'], .9)
        self.assertTrue(all(v is None for v in a['qualification']['last30SecondsGrowthFraction'].values()))
        self.assertFalse(any(a['safetyFlags'].values()))
        digest = hashlib.sha256((ROOT / 'performance/phase14/load-main-memory.json').read_bytes()).hexdigest()
        self.assertEqual(digest, a['runtimeMemoryManifest']['overrideSha256'])

    def test_restoration_cleanup_and_evidence(self):
        a = self.data
        self.assertTrue(a['restoration']['passed'])
        self.assertEqual(a['finalFingerprint'], a['restoration']['baseline'])
        self.assertEqual(a['restoration']['redisDbsize'], 0)
        self.assertTrue(a['finalInvariants']['passed'])
        self.assertFalse(a['originalCorrectness']['passed'])
        self.assertTrue(a['cleanup']['ssh']['load']['negativeAuthenticationCheck'])
        self.assertFalse(a['cleanup']['ssh']['load']['remainingPrivateKey'])
        self.assertTrue(all(v['running'] == 0 for v in a['cleanup']['services']['containers'].values()))
        self.assertEqual(len(a['baselineReferences']['originalEvidence']), 6)
        self.assertEqual(a['sourceHead'], a['qualification']['fingerprint']['controlHead'])
        self.assertTrue((ROOT / 'docs/images/phase14_memory_resources.png').is_file())


if __name__ == '__main__':
    unittest.main()
