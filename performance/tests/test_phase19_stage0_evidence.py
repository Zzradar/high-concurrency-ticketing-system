import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('phase19_evidence', ROOT/'performance/scripts/phase19_stage0_evidence.py')
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


class EvidenceTests(unittest.TestCase):
    def test_failed_or_incomplete_logs_cannot_be_promoted(self):
        for text in ['Ran 3 tests in 1s\nFAILED (errors=1)', 'Ran 3 tests in 1s', 'OK']:
            with self.assertRaises(ValueError):
                evidence.test_count(text)
        self.assertEqual(evidence.test_count('Ran 3 tests in 1s\nOK\nRan 1 test in 2s\nOK\n'), 4)

    def test_redacts_paths_and_provider_secrets(self):
        private = Path('/private-fixture')
        output = evidence.redact(str(ROOT)+'/test '+str(private)+'/log sk_test_123abc whsec_456abc', private)
        self.assertNotIn(str(ROOT), output)
        self.assertNotIn(str(private), output)
        self.assertNotIn('123abc', output)
        self.assertNotIn('456abc', output)


if __name__ == '__main__':
    unittest.main()
