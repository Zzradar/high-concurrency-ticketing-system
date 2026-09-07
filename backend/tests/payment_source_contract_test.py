from pathlib import Path
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (BACKEND_ROOT / path).read_text(encoding="utf-8")


class PaymentSourceContractTest(unittest.TestCase):
    def test_routes_and_user_scoping_are_registered(self) -> None:
        order = read("src/controllers/OrderController.h")
        payment = read("src/controllers/PaymentController.h")
        notification = read("src/controllers/NotificationController.h")
        self.assertIn('"/orders/{orderId}/pay"', order)
        self.assertIn('"/payment-attempts/{paymentAttemptId}"', payment)
        self.assertIn('"/notifications"', notification)
        self.assertIn('"/notifications/{notificationId}/read"', notification)
        repository = read("src/repositories/PaymentRepository.cpp")
        self.assertIn("ticket_order.user_id = $2", repository)

    def test_provider_is_non_blocking_and_callback_is_order_first(self) -> None:
        payment = read("src/services/PaymentService.cpp")
        lifecycle = read("src/services/OrderLifecycleService.cpp")
        provider = read("src/payments/SimulationPaymentProvider.cpp")
        self.assertIn("getLoop()->runAfter", provider)
        self.assertNotIn("sleep_for", payment)
        self.assertNotIn("sleep(", payment)
        self.assertIn("PaymentProviderFactory::create", payment)
        self.assertNotIn("PaymentSimulation::decide", payment)
        self.assertLess(lifecycle.index("lockOrder(state)"), lifecycle.index("lockCallbackAttempt(state)"))

    def test_attempt_is_committed_before_provider_and_redis_is_not_used(self) -> None:
        payment = read("src/services/PaymentService.cpp")
        committed = payment[payment.index("void PaymentService::commitAttempt"):]
        self.assertLess(committed.index("setCommitCallback"), committed.index("startProvider(state"))
        combined = payment + read("src/services/OrderLifecycleService.cpp")
        self.assertNotIn("SeatHoldService", combined)
        self.assertNotIn("getRedisClient", combined)

    def test_callback_supports_accept_failure_timeout_and_refund(self) -> None:
        lifecycle = read("src/services/OrderLifecycleService.cpp")
        for token in (
            "markSucceeded", "markFailed", "markTimedOut", "insertRefund",
            "sellReservationSeats",
            "DUPLICATE_LATE_PAYMENT",
        ):
            self.assertIn(token, lifecycle)
        self.assertIn("accepted", read("src/repositories/PaymentRepository.cpp"))

    def test_configuration_is_validated_and_has_deterministic_non_http_seam(self) -> None:
        config = read("config/config.docker.json")
        main = read("src/main.cpp")
        simulation = read("src/services/PaymentSimulation.cpp")
        self.assertIn('"min_delay_seconds": 2.0', config)
        self.assertIn('"max_delay_seconds": 6.0', config)
        self.assertIn('"failure_rate": 0.01', config)
        self.assertIn('"processing_grace_seconds": 10.0', config)
        self.assertIn("PaymentProviderFactory::validateConfiguration", main)
        self.assertIn("TICKETING_PAYMENT_FORCE_OUTCOME", simulation)
        self.assertNotIn("force", read("src/controllers/OrderController.cpp").lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
