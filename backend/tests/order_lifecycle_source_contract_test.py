from pathlib import Path
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (BACKEND_ROOT / path).read_text(encoding="utf-8")


class OrderLifecycleSourceContractTest(unittest.TestCase):
    def test_cancel_route_and_errors_are_exposed(self) -> None:
        header = read("src/controllers/OrderController.h")
        source = read("src/controllers/OrderController.cpp")
        self.assertIn('"/orders/{orderId}/cancel"', header)
        self.assertIn("drogon::Post", header)
        self.assertIn('"ORDER_NOT_CANCELLABLE"', source)
        self.assertIn('"ORDER_EXPIRED"', source)

    def test_order_is_first_lock_and_uses_wall_clock(self) -> None:
        repository = read("src/repositories/OrderRepository.cpp")
        lifecycle = read("src/services/OrderLifecycleService.cpp")
        self.assertIn("clock_timestamp() >= expires_at AS expired", repository)
        self.assertIn("FOR UPDATE SKIP LOCKED", repository)
        self.assertIn("WHERE id = $1 AND user_id = $2", repository)
        self.assertLess(lifecycle.index("lockOrder(state)"), lifecycle.index("lockAttempt(state)"))
        self.assertLess(lifecycle.index("lockAttempt(state)"), lifecycle.index("lockReservation(state)"))
        self.assertLess(lifecycle.index("lockReservation(state)"), lifecycle.index("lockSeats(state)"))

    def test_cancel_and_expire_share_formal_transition_core(self) -> None:
        lifecycle = read("src/services/OrderLifecycleService.cpp")
        expiry = read("src/services/OrderExpiryService.cpp")
        self.assertIn('state->targetStatus = "CANCELLED"', lifecycle)
        self.assertIn('state->targetStatus = "EXPIRED"', lifecycle)
        self.assertIn("lifecycleService_.expireForWorker", expiry)
        self.assertIn("releaseReservationSeats", lifecycle)
        self.assertIn("transitionReservation", lifecycle)
        self.assertIn("transitionOrder", lifecycle)

    def test_processing_grace_and_timeout_are_checked_under_lock(self) -> None:
        lifecycle = read("src/services/OrderLifecycleService.cpp")
        payment = read("src/repositories/PaymentRepository.cpp")
        self.assertIn("startedBeforeOrderExpiry", lifecycle)
        self.assertIn("deadlinePassed", lifecycle)
        self.assertIn("markAttemptTimedOut", lifecycle)
        self.assertIn("FOR UPDATE OF attempt", payment)


if __name__ == "__main__":
    unittest.main(verbosity=2)
