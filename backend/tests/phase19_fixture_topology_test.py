import os
import unittest
from unittest.mock import patch
from phase18_fixture_topology import topology


class TopologyTests(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_legacy_defaults(self):
        self.assertEqual(topology()['api'], 'phase18-policy-api')

    @patch.dict(os.environ, {}, clear=True)
    def test_new_prefix_cannot_reuse_old_networks(self):
        os.environ['PHASE18_FIXTURE_PREFIX'] = 'phase18-phase19-stage0'
        with self.assertRaises(ValueError):
            topology()
        os.environ['PHASE18_FIXTURE_DATA_NETWORK'] = 'phase19-mixed-data'
        os.environ['PHASE18_FIXTURE_INGRESS_NETWORK'] = 'phase19-mixed-ingress'
        self.assertEqual(topology()['api'], 'phase18-phase19-stage0-api')

    @patch.dict(os.environ, {}, clear=True)
    def test_arbitrary_resources_rejected(self):
        for prefix in ['main', 'phase16-api', 'phase18-policy-api', 'phase18-phase19-x;bad']:
            os.environ['PHASE18_FIXTURE_PREFIX'] = prefix
            with self.assertRaises(ValueError):
                topology()


if __name__ == '__main__':
    unittest.main(verbosity=2)
