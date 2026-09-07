from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


class Phase11ProviderSourceContractTest(unittest.TestCase):
    def test_terminal_snapshot_is_transactional_and_secret_free(self):
        header = read("src/repositories/PaymentRepository.h")
        snapshot = header.split("struct PaymentTerminalSnapshot")[1].split("};")[0]
        self.assertNotIn("clientSecret", snapshot)
        lifecycle = read("src/services/OrderLifecycleService.cpp")
        self.assertIn("recordTerminalSnapshot(\n                state->transaction", lifecycle)
        self.assertIn("snapshot.provider != value.provider", lifecycle)
        self.assertIn("snapshot.amount != state->order.totalAmount", lifecycle)
        service = read("src/services/PaymentReconciliationService.cpp")
        self.assertIn("reconciliation_lease_token = $3", service)
        self.assertIn("attempt.provider_status IN ('succeeded','canceled')", service)
        self.assertIn("OR attempt.next_reconcile_at IS NULL", service)
        self.assertIn("completeProviderPayment", service)
        repository = read("src/repositories/PaymentRepository.cpp")
        nonterminal = repository.split("void PaymentRepository::recordProviderPayment")[1].split("void PaymentRepository::recordTerminalSnapshot")[0]
        self.assertNotIn("bool terminal", nonterminal)
        self.assertNotIn("provider_terminal_at =", nonterminal)

    def test_provider_boundary_and_direct_async_rest(self):
        interface = read("src/payments/PaymentProvider.h")
        stripe = read("src/payments/StripePaymentProvider.cpp")
        for operation in ("createOrRecoverPayment", "retrievePayment",
                          "createOrRecoverRefund", "retrieveRefund"):
            self.assertIn(operation, interface)
        self.assertIn("HttpClient", read("src/payments/StripePaymentProvider.h"))
        self.assertIn("sendRequest", stripe)
        self.assertNotIn("Future", stripe)
        self.assertNotIn("condition_variable", stripe)

    def test_idempotency_and_secret_boundaries(self):
        stripe = read("src/payments/StripePaymentProvider.cpp")
        self.assertIn('"Idempotency-Key"', stripe)
        self.assertIn("input.attemptId", stripe)
        self.assertIn("input.refundId", stripe)
        dto = read("src/dto/TicketDtos.h")
        self.assertIn('value["paymentAction"]["clientSecret"]', dto)
        migration = read("db/migrations/007_add_payment_provider_recovery.sql")
        self.assertNotIn("client_secret", migration.lower())

    def test_webhook_is_raw_signed_and_inbox_only(self):
        controller = read("src/controllers/StripeWebhookController.cpp")
        verifier = read("src/payments/StripeWebhookVerifier.cpp")
        header = read("src/controllers/StripeWebhookController.h")
        self.assertIn('"/payment-webhooks/stripe"', header)
        self.assertNotIn("AuthFilter", header)
        self.assertIn("request->body()", controller)
        self.assertIn("hmacSha256Hex", verifier)
        self.assertIn("constantTimeEqual", verifier)
        self.assertIn("v1", verifier)

    def test_reconciliation_claims_without_locking_over_http(self):
        service = read("src/services/PaymentReconciliationService.cpp")
        self.assertIn("FOR UPDATE SKIP LOCKED", service)
        self.assertIn("PaymentProviderFactory::createNamed", service)
        self.assertIn("AUTO_REFUND_FAILED", service)
        self.assertIn("AUTO_REFUND_COMPLETED", service)


if __name__ == "__main__":
    unittest.main(verbosity=2)
