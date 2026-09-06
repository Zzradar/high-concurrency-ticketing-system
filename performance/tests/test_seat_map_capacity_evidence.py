import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CapacityEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads((ROOT / 'performance/experiments/phase10b-seat-map/post-offload-capacity-measurements.json').read_text(encoding='utf-8'))
        cls.runs = cls.evidence['runs']

    def test_explicit_boundaries_repetitions_and_failed_evidence(self):
        self.assertEqual(len({run['runId'] for run in self.runs}), len(self.runs))
        for density in (0, 90):
            runs = [r for r in self.runs if r['arguments']['density'] == density
                    and r['arguments']['duration'] == 15 and not r['arguments']['mixed']]
            self.assertEqual(sorted(r['arguments']['rate'] for r in runs), [60, 60, 60, 100, 100])
            for run in runs:
                if run['arguments']['rate'] == 60:
                    self.assertEqual(run['failures'], [])
                else:
                    self.assertGreater(run['compute']['rejected'], 0)
                    self.assertEqual(run['runnerExit'], 99)
                    self.assertTrue(run['failures'])

    def test_fixed_runtime_inventory_display_and_generator_accounting(self):
        for run in self.runs:
            self.assertEqual(run['identityBefore'], run['identityAfter'])
            self.assertEqual((run['identityBefore']['workers'], run['identityBefore']['queueCapacity']), (4, 16))
            self.assertEqual(run['verifierExit'], 0)
            self.assertEqual(run['formalInventoryBefore'], 'AVAILABLE\t5000')
            self.assertEqual(run['formalInventoryAfter'], 'AVAILABLE\t5000')
            self.assertTrue(run['drained'])
            http = run['http']
            exact = http['ticketing_display_exact_total']['count']
            completed = http['ticketing_capacity_seat_completed_total']['count']
            rejected = http['ticketing_seat_map_503_total']['count']
            self.assertEqual(exact + rejected, completed)
            self.assertEqual(rejected, run['compute']['rejected'])
            self.assertEqual(run['redisOutcomes'], {'success': completed + 1,
                             'timeout': 0, 'error': 0, 'parse_error': 0})
            self.assertEqual(http['ticketing_display_degraded_total']['count'], 0)
            self.assertEqual(http['ticketing_display_invalid_total']['count'], 0)
            for sample in run['timeline']:
                self.assertLessEqual(sample['queue'], 16)
                self.assertLessEqual(sample['active'], 4)

    def test_mixed_does_not_mask_seat_rejection_with_public_auth_success(self):
        mixed, = [r for r in self.runs if r['arguments']['mixed']]
        self.assertEqual(mixed['rates'], {'seat': 150, 'public': 200, 'auth': 200})
        self.assertTrue(mixed['failures'])
        for kind in ('public', 'auth'):
            self.assertEqual(mixed['http'][f'ticketing_capacity_{kind}_success_total']['count'], 3000)
        self.assertEqual(self.evidence['scope']['mixed4Executed'], False)
        self.assertEqual(self.evidence['scope']['mixed8Executed'], False)

    def test_long_observation_preserves_drain_and_browser_scope(self):
        long, = [r for r in self.runs if r['arguments']['duration'] == 300]
        self.assertEqual(long['arguments']['drain_seconds'], 180)
        self.assertGreaterEqual(long['endEpoch'] - long['runnerFinishedEpoch'], 180)
        self.assertTrue(long['httpP95Trend'])
        self.assertGreater(len(long['timeline']), 100)
        self.assertEqual(self.evidence['scope']['browser']['contentEncoding'], 'gzip')


if __name__ == '__main__':
    unittest.main()
