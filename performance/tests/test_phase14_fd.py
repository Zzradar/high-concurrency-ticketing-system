import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'performance/scripts'))
from phase14_fd import LIMIT, OVERRIDE, parse_limits, validate_limits, FdGuard, apply_override, equivalent_fingerprint


class FdTests(unittest.TestCase):
    def record(self, fraction=0, events=None):
        return dict(soft=LIMIT, hard=LIMIT, fraction=fraction, errorTimestamps=events or [],
                    dockerUlimits=[dict(Name='nofile', Soft=LIMIT, Hard=LIMIT)])

    def test_actual_process_limits_override_inspect(self):
        self.assertEqual(parse_limits('Max open files            65535                65535                files\n'),
                         {'soft': LIMIT, 'hard': LIMIT})
        r = self.record(); r['soft'] = 1024
        with self.assertRaises(ValueError): validate_limits(r)
        r = self.record(); r['dockerUlimits'] = None
        with self.assertRaises(ValueError): validate_limits(r)
        with self.assertRaises(ValueError): parse_limits('unavailable')

    def test_three_consecutive_points_and_immediate_errors(self):
        guard = FdGuard()
        for fraction, expected in [(.85, False), (.86, False), (.84, False), (.85, False), (.9, False), (.9, True)]:
            self.assertEqual(guard.sample(self.record(fraction)), expected)
        self.assertTrue(FdGuard().sample(self.record(events=['2026-09-12T00:00:00Z'])))

    def test_overlay_only_changes_backend_nofile_and_preserves_original(self):
        original = {'services': {'backend': {'image': 'fixed', 'ports': [18414]}, 'postgres': {'image': 'fixed-pg'}}}
        saved = copy.deepcopy(original)
        with tempfile.TemporaryDirectory() as folder:
            result = apply_override(Mock(root=Path(folder)), original)
            self.assertEqual(original, saved)
            self.assertEqual(result['services']['postgres'], original['services']['postgres'])
            result['services']['backend'].pop('ulimits')
            self.assertEqual(result, original)
            self.assertEqual(json.loads((Path(folder)/'fd-override.json').read_text()), OVERRIDE)
            self.assertEqual(len(json.loads((Path(folder)/'fd-compose-hashes.json').read_text())), 3)

    def test_equivalence_rejects_input_image_and_threshold_changes(self):
        a = {'controlHead': 'old', 'image': 'fixed', 'inputs': {'sessions': 'hash'}, 'targetsSha256': 'frozen'}
        b = {**a, 'controlHead': 'new'}
        equivalent_fingerprint(a, b)
        for key in ('image', 'inputs', 'targetsSha256'):
            with self.assertRaises(ValueError): equivalent_fingerprint(a, {**b, key: 'changed'})

    def test_core_plan_and_workload_unchanged(self):
        from phase14_core import core_plan
        from phase14_model import load_targets
        self.assertEqual(core_plan(load_targets()), json.loads((ROOT/'docs/phase14_core_plan.json').read_text()))


if __name__ == '__main__': unittest.main()
