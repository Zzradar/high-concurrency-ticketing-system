import json
from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "performance" / "scripts"))

import run_login_experiment as experiment  # noqa: E402


class LoginExperimentTests(unittest.TestCase):
    def test_generated_config_changes_only_worker_and_queue(self):
        source = json.loads(experiment.SOURCE_CONFIG.read_text(encoding="utf-8"))
        candidate = experiment.build_experiment_config(4, 16)
        self.assertEqual(
            experiment.changed_paths(source, candidate),
            experiment.ALLOWED_CHANGES,
        )
        auth = candidate["custom_config"]["authentication"]
        self.assertEqual(auth["password_hash_workers"], 4)
        self.assertEqual(auth["password_hash_queue_capacity"], 16)
        self.assertEqual(auth["argon2_time_cost"], 2)
        self.assertEqual(auth["argon2_memory_cost_kib"], 65536)
        self.assertEqual(auth["argon2_parallelism"], 1)

    def test_unchanged_control_config_passes_guard(self):
        source = json.loads(experiment.SOURCE_CONFIG.read_text(encoding="utf-8"))
        candidate = experiment.build_experiment_config(2, 64)
        self.assertEqual(experiment.changed_paths(source, candidate), set())

    def test_invalid_capacity_is_rejected_before_compose(self):
        with self.assertRaisesRegex(ValueError, "must be positive"):
            experiment.build_experiment_config(0, 64)
        with self.assertRaisesRegex(ValueError, "must be positive"):
            experiment.build_experiment_config(2, 0)

    def test_override_mounts_only_generated_experiment_config(self):
        override = experiment.COMPOSE_OVERRIDE.read_text(encoding="utf-8")
        self.assertIn("auth-experiment-config.json", override)
        self.assertNotIn("password_hash_workers", override)
        self.assertNotIn("password_hash_queue_capacity", override)


if __name__ == "__main__":
    unittest.main()
