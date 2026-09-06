import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'performance/scripts'))
import configure_seat_map_experiment as experiment
from summarize_seat_map_offload import histogram_delta, summarize_run


class OffloadTests(unittest.TestCase):
    def test_compute_histogram_uses_strict_delta_and_explicit_run_identity(self):
        before = {'compute_bucket{le="0.01"}': 5, 'compute_bucket{le="+Inf"}': 5}
        after = {key: value + 2 for key, value in before.items()}
        self.assertEqual(histogram_delta(before, after, 'compute')['samples'], 2)
        with self.assertRaises(ValueError):
            histogram_delta(after, before, 'compute')
        with self.assertRaises(ValueError):
            histogram_delta({}, after, 'compute')
        with self.assertRaises(ValueError):
            summarize_run('before', '../escape', 'a' * 64)

    def test_experiment_changes_only_worker_count_and_keeps_queue_fixed(self):
        original = json.loads(experiment.CONFIG.read_text(encoding='utf-8'))
        for workers in (2, 4):
            result = experiment.build_config(workers)
            self.assertLessEqual(experiment.changed_paths(original, result),
                                 {('custom_config', 'seat_map_compute_workers')})
            self.assertEqual(result['custom_config']['seat_map_compute_queue_capacity'], 16)
        for workers in (0, 1, 8, 16):
            with self.assertRaises(ValueError):
                experiment.build_config(workers)

    def test_handoff_owns_values_and_does_not_move_compute_to_http_loop(self):
        service = (ROOT / 'backend/src/services/SeatService.cpp').read_text(encoding='utf-8')
        for code in ('executor->trySubmit(', 'holds = std::move(holds)',
                     'seats = std::move(seats)', 'claimed->exchange(true)', 'if (!accepted) onBusy();'):
            self.assertIn(code, service)
        self.assertLess(service.index('executor->trySubmit('), service.index('const auto overlayStarted'))
        self.assertNotIn('queueInLoop', service)
        controller = (ROOT / 'backend/src/controllers/SeatController.cpp').read_text(encoding='utf-8')
        self.assertIn('k503ServiceUnavailable', controller)
        self.assertIn('"SEAT_MAP_BUSY"', controller)
        self.assertNotIn('getBody()', controller)
        main = (ROOT / 'backend/src/main.cpp').read_text(encoding='utf-8')
        self.assertIn('ComputeShutdown computeShutdown{seatMapCompute}', main)
        self.assertIn('seatMapCompute->shutdown()', main)

    def test_defaults_and_metric_cardinality(self):
        for name in ('config.json', 'config.docker.json', 'config.performance.json', 'config.performance.no_metrics.json'):
            config = json.loads((ROOT / 'backend/config' / name).read_text(encoding='utf-8'))
            self.assertEqual(config['custom_config']['seat_map_compute_workers'], 4)
            self.assertEqual(config['custom_config']['seat_map_compute_queue_capacity'], 16)
        collectors = json.loads(experiment.CONFIG.read_text(encoding='utf-8'))['plugins'][0]['config']['collectors']
        compute = [value for value in collectors if value['name'].startswith('ticketing_seat_map_compute_')]
        self.assertEqual(len(compute), 5)
        for value in compute:
            self.assertEqual(value['labels'], ['outcome'] if value['type'] == 'counter' else [])

    def test_failed_candidates_collect_verifier_before_failing_and_check_display(self):
        driver = (ROOT / 'performance/scripts/calibrate_seat_map.py').read_text(encoding='utf-8')
        self.assertLess(driver.index("manifest['verifierExit'] = verifier.returncode"),
                        driver.index("raise RuntimeError('compute rejection"))
        self.assertIn("if args.compute_workers is not None and args.density:", driver)
        self.assertIn("display['ticketing_display_degraded_total']['values']['count'] == 0", driver)


if __name__ == '__main__':
    unittest.main()
