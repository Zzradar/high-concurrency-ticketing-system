from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
PERFORMANCE_ROOT = REPO_ROOT / "performance"


def source(relative: str) -> str:
    return (PERFORMANCE_ROOT / relative).read_text(encoding="utf-8")


class WorkloadTests(unittest.TestCase):
    def test_public_read_checks_the_real_top_level_array_contract(self):
        workload = source("k6/workloads/public-read.js")
        metrics = source("k6/lib/metrics.js")
        self.assertIn("Array.isArray(payload)", workload)
        self.assertIn("GET /events", workload)
        self.assertNotIn("response.error_code", metrics)

    def test_auth_read_selects_unique_cold_sessions_and_bounded_warm_pool(self):
        workload = source("k6/workloads/auth-read.js")
        self.assertIn("exec.scenario.iterationInTest", workload)
        self.assertIn("authMode === 'cold' ? iteration : iteration % authPoolSize", workload)
        self.assertIn("GET /auth/me", workload)

    def test_formal_contention_is_one_batch_per_unique_seat(self):
        workload = source("k6/workloads/formal-seat-contention.js")
        self.assertIn("const seat = seats[groupIndex]", workload)
        self.assertIn("http.batch(requests)", workload)
        self.assertIn("batch: contenders", workload)
        self.assertIn("batchPerHost: contenders", workload)
        self.assertIn("const validGroup = successes === 1 && conflicts === contenders - 1", workload)
        self.assertIn("recordResult('unexpected', 'formal_group')", workload)
        self.assertIn("reservationHeaders(session, key)", workload)
        self.assertNotIn("response.error_code", workload)


if __name__ == "__main__":
    unittest.main()
