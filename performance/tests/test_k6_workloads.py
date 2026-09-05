from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
PERFORMANCE_ROOT = REPO_ROOT / "performance"


def source(relative: str) -> str:
    return (PERFORMANCE_ROOT / relative).read_text(encoding="utf-8")


class WorkloadTests(unittest.TestCase):
    def test_remaining_workloads_use_real_contracts_and_one_shot_indices(self):
        seat_map = source("k6/workloads/seat-map-read.js")
        temporary = source("k6/workloads/temporary-hold-contention.js")
        checkout = source("k6/workloads/checkout.js")
        payment_start = source("k6/workloads/payment-start.js")
        payment_lifecycle = source("k6/workloads/payment-lifecycle.js")
        login = source("k6/workloads/login.js")
        self.assertIn("responseType: 'none'", seat_map)
        self.assertIn("seat-map preflight contract failed", seat_map)
        self.assertIn("SEAT_TEMPORARILY_HELD", temporary)
        self.assertIn("created === 1 && conflicts === contenders - 1", temporary)
        self.assertNotIn("groupIndex % seats.length", temporary)
        self.assertIn("/checkout-sessions/${created.json('id')}/confirm", checkout)
        self.assertIn("checkoutSession.status", checkout)
        self.assertIn("STARTED_NEW", payment_start)
        self.assertIn("paymentAttempt.status", payment_start)
        self.assertIn("sleep(1)", payment_lifecycle)
        self.assertIn("scenarioFor(config.mode, 'RATE', '20s')", payment_lifecycle)
        self.assertIn("AUTH_BUSY", login)
        self.assertIn("exec.scenario.iterationInTest", login)
        self.assertNotIn("iteration % users.length", login)

    def test_synthetic_mixes_use_independent_k6_scenarios(self):
        reads = source("k6/workloads/synthetic-mixed-read.js")
        writes = source("k6/workloads/synthetic-mixed-transactional.js")
        for scenario in ("public_read", "auth_warm", "seat_map"):
            self.assertIn(f"{scenario}:", reads)
        self.assertIn("PUBLIC_RATE", reads)
        self.assertIn("AUTH_RATE", reads)
        self.assertIn("SEAT_MAP_RATE", reads)
        self.assertIn("checkout:", writes)
        self.assertIn("payment:", writes)
        self.assertIn("CHECKOUT_POOL_OFFSET", writes)
        self.assertNotIn("% seats.length", writes)

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
        self.assertIn("required index=${index}, available count=${sessions.length}", workload)
        self.assertIn("GET /auth/me", workload)

    def test_formal_contention_is_one_batch_per_unique_seat(self):
        workload = source("k6/workloads/formal-seat-contention.js")
        self.assertIn("const seat = seats[groupIndex]", workload)
        self.assertNotIn("groupIndex % seats.length", workload)
        self.assertIn("required index=${groupIndex}, available count=${seats.length}", workload)
        self.assertIn("http.batch(requests)", workload)
        self.assertIn("batch: contenders", workload)
        self.assertIn("batchPerHost: contenders", workload)
        self.assertIn("const validGroup = successes === 1 && conflicts === contenders - 1", workload)
        self.assertIn("recordResult('unexpected', 'formal_group')", workload)
        self.assertIn("reservationHeaders(session, key)", workload)
        self.assertNotIn("response.error_code", workload)


if __name__ == "__main__":
    unittest.main()
