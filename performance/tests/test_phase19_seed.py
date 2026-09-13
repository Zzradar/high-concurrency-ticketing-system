import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('phase19_seed', ROOT / 'performance/experiments/phase19-global-polling-mixed-load/protocol/seed.py')
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)


class SeedTests(unittest.TestCase):
    def test_reuses_generator_with_exact_namespace_and_disjoint_capacity(self):
        statement, users, shape = seed.prepare()
        self.assertEqual(shape.active_auth_sessions, 5000)
        self.assertEqual(shape.session_seats, 25000)
        self.assertNotIn('perf-', statement)
        self.assertIn("WHERE user_id LIKE 'phase19-user-%'", statement)
        self.assertEqual(len({u['userId'] for u in users}), 5000)
        self.assertEqual(len({u['sessionToken'] for u in users}), 5000)
        self.assertTrue(all(u['userId'].startswith('phase19-user-') for u in users))

    def test_fresh_database_guard_runs_before_any_mutation(self):
        calls = []
        def sql(statement):
            calls.append(statement)
            return '1'
        with self.assertRaisesRegex(RuntimeError, 'fresh owned volume'):
            seed.seed(sql, Path('unused'))
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].startswith('SELECT'))


if __name__ == '__main__':
    unittest.main()
