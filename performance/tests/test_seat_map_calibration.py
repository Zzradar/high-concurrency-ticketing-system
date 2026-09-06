import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'performance/scripts'))
import calibrate_seat_map as calibration
import summarize_seat_map_calibration as summary


class CalibrationTests(unittest.TestCase):
    def test_summary_requires_exact_container_identity_and_preserves_failure(self):
        with self.assertRaisesRegex(ValueError, 'container ID'):
            summary.summarize(Path('unused'), 'backend')
        with mock.patch.object(summary, 'read', return_value={'error': 'stop line'}):
            result = summary.summarize(Path('failed-run'), 'a' * 64)
        self.assertTrue(result['incompleteOrFailed'])
        self.assertEqual(result['error'], 'stop line')

    def test_counter_delta_requires_all_fixed_outcomes_and_no_reset(self):
        before = {f'ticketing_seat_map_redis_lookup_total{{outcome="{key}"}}': 7 for key in calibration.OUTCOMES}
        after = {key: value + 3 for key, value in before.items()}
        self.assertEqual(calibration.outcome_delta(before, after), dict.fromkeys(calibration.OUTCOMES, 3))
        with self.assertRaisesRegex(RuntimeError, 'missing'):
            calibration.outcome_delta({}, after)
        with self.assertRaisesRegex(RuntimeError, 'reset'):
            calibration.outcome_delta(after, before)

    def test_memory_and_conservative_stop_before_health_io(self):
        sample = {'backendProcessAndCgroup': 'VmRSS:\t100 kB\n4000000000\ninactive_file 10\n'}
        self.assertEqual(calibration.memory(sample), {'rssBytes': 102400, 'workingSetBytes': 3999999990})
        with mock.patch.object(calibration.run_k6, 'http_json') as http:
            with self.assertRaisesRegex(RuntimeError, 'stop line'):
                calibration.check_safety(sample)
            http.assert_not_called()
        with self.assertRaisesRegex(RuntimeError, 'memory safety'):
            calibration.memory({'backendProcessAndCgroup': ''})

    def test_diagnostics_remove_early_serialization_and_keep_fixed_counter_contract(self):
        controller = (ROOT / 'backend/src/controllers/SeatController.cpp').read_text()
        self.assertNotIn('getBody()', controller)
        self.assertIn('newHttpJsonResponse(body)', controller)
        metrics = (ROOT / 'backend/src/observability/PerformanceMetrics.cpp').read_text()
        self.assertNotIn('"json_serialize"', metrics)
        self.assertIn('"success", "timeout", "error", "parse_error"', metrics)
        service = (ROOT / 'backend/src/services/SeatHoldService.cpp').read_text().split('void SeatHoldService::readOwners(')[1]
        self.assertIn('redisError->code() == drogon::nosql::RedisErrorCode::kTimeout', service)
        self.assertIn('if (!parsed)', service)
        self.assertLess(service.index('parsed = true'), service.index('(*done)(std::move(read))'))
        config = json.loads((ROOT / 'backend/config/config.performance.json').read_text())
        metric = next(c for c in config['plugins'][0]['config']['collectors'] if c['name'] == 'ticketing_seat_map_redis_lookup_total')
        self.assertEqual((metric['type'], metric['labels']), ('counter', ['outcome']))

    def test_independent_workload_checks_payload_without_masking_display_degradation(self):
        script = (ROOT / 'performance/k6/diagnostics/seat-map-calibration.js').read_text()
        for code in ("['identity', 'gzip']", "'Accept-Encoding': encoding", 'responseType: body',
                     'value.HELD === expectedHeld', 'value.AVAILABLE === 5000',
                     'value.SOLD === 0', 'degraded.add(fallback ? 1 : 0)', 'invalid.add(1)'):
            self.assertIn(code, script)
        self.assertNotIn('Accept-Encoding', (ROOT / 'performance/k6/workloads/seat-map-read.js').read_text())
        driver = Path(calibration.__file__).read_text()
        self.assertIn('time.sleep(6)', driver)
        self.assertIn("choices=(10, 30, 60)", driver)
        self.assertNotIn('volume rm', driver)
        self.assertNotIn('force-recreate', driver)



if __name__ == '__main__':
    unittest.main()
