from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CHECKOUT = (ROOT / "src/services/CheckoutSessionService.cpp").read_text(encoding="utf-8")
CHECKOUT_CONTROLLER = (ROOT / "src/controllers/CheckoutSessionController.cpp").read_text(encoding="utf-8")
PAYMENT = (ROOT / "src/services/PaymentService.cpp").read_text(encoding="utf-8")
ORDER = (ROOT / "src/services/OrderService.cpp").read_text(encoding="utf-8")
ORDER_CONTROLLER = (ROOT / "src/controllers/OrderController.cpp").read_text(encoding="utf-8")
DTO = (ROOT / "src/dto/TicketDtos.h").read_text(encoding="utf-8")


class OperationDispositionSourceContractTest(unittest.TestCase):
    def test_confirm_uses_locked_entry_state(self) -> None:
        for value in ("CONFIRMED_NOW", "REUSED_CONFIRMATION", "ALREADY_CONFIRMED"):
            self.assertIn(value, CHECKOUT)
        self.assertIn('body["checkoutSession"]', CHECKOUT_CONTROLLER)
        self.assertIn('body["disposition"]', CHECKOUT_CONTROLLER)

    def test_payment_uses_attempt_creation_fact(self) -> None:
        self.assertIn("StartPaymentOutcome::StartedNew", PAYMENT)
        self.assertIn("StartPaymentOutcome::ReusedProcessing", PAYMENT)
        self.assertIn('"STARTED_NEW"', PAYMENT)
        self.assertIn('"REUSED_PROCESSING"', PAYMENT)
        self.assertIn('"ALREADY_PAID"', PAYMENT)
        self.assertIn('value["disposition"]', DTO)

    def test_cancel_uses_lifecycle_outcome(self) -> None:
        self.assertIn("OrderLifecycleOutcome::AlreadyCancelled", ORDER)
        self.assertIn('"CANCELLED_NOW"', ORDER)
        self.assertIn('"ALREADY_CANCELLED"', ORDER)
        self.assertIn('body["order"]', ORDER_CONTROLLER)


if __name__ == "__main__":
    unittest.main(verbosity=2)
