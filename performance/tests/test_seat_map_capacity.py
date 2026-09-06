import copy
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'performance/scripts'))
import characterize_seat_map_capacity as capacity
import summarize_seat_map_capacity as summary


class CapacityTests(unittest.TestCase):
    def test_fixed_runtime_configuration(self):
        config = json.loads((ROOT / 'backend/config/config.performance.json').read_text())
        capacity.validate_config(config)
        for key, value in [('seat_map_compute_workers', 8), ('seat_map_compute_queue_capacity', 32)]:
            changed = copy.deepcopy(config)
            changed['custom_config'][key] = value
            with self.assertRaises(RuntimeError): capacity.validate_config(changed)
        for section, key, value in [('db_clients', 'number_of_connections', 8),
                                    ('redis_clients', 'timeout', 1)]:
            changed = copy.deepcopy(config)
            changed[section][0][key] = value
            with self.assertRaises(RuntimeError): capacity.validate_config(changed)

    def fixture(self):
        manifest = {'runnerExit': 0, 'verifierExit': 0, 'redisOutcomes': {'success': 902, 'timeout': 0},
                    'compute': {'rejected': 0}, 'drained': True,
                    'formalInventoryBefore': 'AVAILABLE\t5000', 'formalInventoryAfter': 'AVAILABLE\t5000',
                    'rates': {'seat': 60}, 'arguments': {'duration': 15}}
        metrics = {key: {'values': {'count': 901}} for key in
                   ('ticketing_capacity_seat_completed_total', 'ticketing_capacity_seat_success_total', 'ticketing_display_exact_total')}
        return manifest, metrics

    def test_boundary_extra_iteration_allowed_but_under_delivery_not(self):
        manifest, metrics = self.fixture()
        self.assertEqual(capacity.failures(manifest, metrics), [])
        metrics['ticketing_capacity_seat_completed_total']['values']['count'] = 899
        self.assertIn('seat target not delivered', capacity.failures(manifest, metrics))

    def test_http_200_cannot_mask_degradation_or_queue_rejection(self):
        manifest, metrics = self.fixture()
        metrics['ticketing_display_degraded_total'] = {'values': {'count': 1}}
        manifest['compute']['rejected'] = 1
        reasons = capacity.failures(manifest, metrics)
        self.assertIn('ticketing_display_degraded_total', reasons)
        self.assertIn('compute rejection/incomplete drain', reasons)

    def test_counter_error_and_database_failure_fail_closed(self):
        manifest, metrics = self.fixture()
        manifest['redisOutcomes']['timeout'] = 1
        manifest['verifierExit'] = 1
        self.assertIn('redis_timeout', capacity.failures(manifest, metrics))
        self.assertIn('runner/verifier failure', capacity.failures(manifest, metrics))

    def test_independent_mixed_and_full_display_checks(self):
        source = (ROOT / 'performance/k6/diagnostics/post-offload-capacity.js').read_text()
        for fragment in ("public_read: scenario('publicRead'", "auth_warm: scenario('authWarm'",
                         "seat_map: scenario('seatMap'", 'iterationInTest % 100', "responseType: 'text'",
                         'counts.AVAILABLE === 5000 - expectedHeld', "response.status === 503",
                         "ticketing_display_degraded_total: ['count==0']"):
            self.assertIn(fragment, source)
        driver = Path(capacity.__file__).read_text()
        self.assertNotIn('force-recreate', driver)
        self.assertNotIn('volume rm', driver)
        self.assertIn("args.duration + 90", driver)
        self.assertIn("args.drain_seconds != 180", driver)

    def test_incomplete_evidence_is_never_relabelled_success(self):
        with mock.patch.object(summary, 'read', return_value={'error': 'sampling unavailable', 'runnerExit': 1}):
            result = summary.summarize('failed-capacity-run')
        self.assertTrue(result['incomplete'])
        self.assertEqual(result['runnerExit'], 1)
        with self.assertRaises(ValueError): summary.summarize('../unrelated')

    def test_stale_interval_is_unavailable_not_clamped_quantile(self):
        key = 'ticketing_seat_map_compute_queue_wait_seconds_bucket{le="+Inf"}'
        value = summary.interval_histogram({key: 10}, {key: 9})
        self.assertIn('unavailable', value)
        self.assertNotIn('p95Seconds', value)


if __name__ == '__main__':
    unittest.main()
