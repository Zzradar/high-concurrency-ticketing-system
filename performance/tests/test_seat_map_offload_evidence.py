import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class OffloadEvidenceTests(unittest.TestCase):
    def test_explicit_matrix_preserves_failure_and_success_boundaries(self):
        evidence = json.loads((ROOT / 'performance/experiments/phase10b-seat-map/callback-offload-measurements.json').read_text())
        runs = evidence['runs']
        self.assertEqual(len(runs), 10)
        self.assertEqual(len({r['runId'] for r in runs}), 10)
        before = [r for r in runs if r['phase'] == 'before']
        self.assertEqual([r['redisOutcomes']['timeout'] for r in before], [404, 744])
        failed, = [r for r in runs if r['phase'] == 'workers2']
        self.assertTrue(failed['incompleteOrFailed'])
        self.assertEqual(failed['compute']['submissions']['rejected'], 97)
        self.assertEqual(failed['business']['system_error'], 97)
        self.assertNotIn('verifierExit', failed)
        self.assertIn('later read-only', failed['finalSampleScope'])
        candidates = [r for r in runs if r['phase'] == 'workers4']
        self.assertEqual({(r['arguments']['rate'], r['arguments']['density'], r['arguments']['encoding'],
                          r['arguments']['duration'], r['arguments']['drain_seconds']) for r in candidates},
                         {(30, 0, 'identity', 15, 0), (60, 0, 'identity', 15, 0),
                          (60, 0, 'identity', 30, 180), (10, 90, 'identity', 15, 0),
                          (60, 90, 'identity', 15, 0), (30, 0, 'gzip', 15, 0), (60, 0, 'gzip', 15, 0)})
        for run in candidates:
            self.assertEqual(run['redisOutcomes'], {'success': run['business']['http_reqs'],
                             'timeout': 0, 'error': 0, 'parse_error': 0})
            self.assertEqual((run['runnerExit'], run['verifierExit'], run['finalInFlight']), (0, 0, 0))
            self.assertEqual(run['formalInventoryBefore'], run['formalInventoryAfter'])
            for key in ('dropped_iterations', 'system_error', 'unexpected'):
                self.assertEqual(run['business'][key], 0)
            compute = run['compute']
            self.assertEqual(compute['queueCapacity'], 16)
            self.assertEqual(compute['submissions']['rejected'], 0)
            self.assertEqual(compute['execution']['samples'], compute['submissions']['accepted'])
            self.assertEqual(compute['timeline'][-1]['active'], 0)
            self.assertEqual(compute['timeline'][-1]['depth'], 0)
            for sample in compute['timeline']:
                self.assertLessEqual(sample['depth'], 16)
                self.assertLessEqual(sample['active'], 4)
            if run['arguments']['density']:
                display = run['display']
                self.assertEqual(display['ticketing_display_exact_total']['count'], run['business']['iterations'])
                self.assertEqual(display['ticketing_display_degraded_total']['count'], 0)
                self.assertEqual(display['ticketing_display_invalid_total']['count'], 0)
        drain, = [r for r in candidates if r['arguments']['drain_seconds']]
        self.assertGreaterEqual(drain['endEpoch'] - drain['runnerFinishedEpoch'], 180)
        self.assertLessEqual(drain['memory']['rssBytes']['after'], drain['memory']['rssBytes']['before'])
        self.assertEqual(evidence['scope']['browser']['contentEncoding'], 'gzip')


if __name__ == '__main__':
    unittest.main()
