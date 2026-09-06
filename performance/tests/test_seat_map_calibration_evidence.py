import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class CalibrationEvidenceTests(unittest.TestCase):
    def test_calibration_evidence_keeps_outcomes_display_and_recovery_distinct(self):
        directory = ROOT / 'performance/experiments/phase10b-seat-map'
        data = json.loads((directory / 'calibration-measurements.json').read_text(encoding='utf-8'))
        runs = data['runs']
        self.assertEqual(len(runs), 7)
        for run in runs:
            self.assertEqual((run['runnerExit'], run['verifierExit'], run['finalInFlight']), (0, 0, 0))
            self.assertEqual(len(run['stages']), 11)
            self.assertNotIn('json_serialize', run['stages'])
            self.assertEqual(sum(run['redisOutcomes'].values()), run['business']['http_reqs'])
            self.assertEqual(run['redisOutcomes']['success'], run['stages']['owner_parse']['samples'])
            self.assertEqual(run['postgres']['calls'], run['stages']['redis_lookup']['samples'])
            self.assertEqual(run['formalInventoryBefore'], run['formalInventoryAfter'])
            self.assertEqual(run['formalInventoryAfter'], 'AVAILABLE\t5000')
            self.assertEqual(run['resources']['backend']['workingSetBytes']['seriesCount'], 1)
            self.assertEqual(run['resources']['k6']['workingSetBytes']['seriesCount'], 1)
            self.assertTrue(run['gzip']['bodyEquality'])
        high = next(r for r in runs if r['arguments']['density'] == 90 and r['arguments']['rate'] == 60)
        display = high['display']
        self.assertEqual(display['ticketing_display_degraded_total']['count'], 712)
        self.assertEqual(display['ticketing_display_exact_total']['count'], 189)
        self.assertEqual(display['ticketing_display_degraded_total']['count'], high['redisOutcomes']['timeout'])
        self.assertEqual(display['ticketing_display_invalid_total']['count'], 0)
        drain = next(r for r in runs if r['arguments']['drain_seconds'])
        self.assertGreaterEqual(drain['timeline'][-1]['epoch'] - drain['runnerFinishedEpoch'], 180)
        self.assertEqual(drain['timeline'][-1]['sumClientOmem'], 0)
        self.assertLess(drain['memory']['rssBytes']['after'], drain['memory']['rssBytes']['peak'])
        self.assertGreater(drain['memory']['rssBytes']['after'], drain['memory']['rssBytes']['before'])
        report = (directory / 'calibration.md').read_text(encoding='utf-8')
        for phrase in ('展示校验并未通过', 'B：部分恢复', '没有开启 CPU profile', '不进入真正优化'):
            self.assertIn(phrase, report)


if __name__ == '__main__':
    unittest.main()
