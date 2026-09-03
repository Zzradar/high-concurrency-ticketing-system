from pathlib import Path
import re
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (BACKEND_ROOT / "db/migrations/005_add_payment_lifecycle.sql").read_text(
    encoding="utf-8"
)
COMPOSE = (BACKEND_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
DTO = (BACKEND_ROOT / "src/dto/TicketDtos.h").read_text(encoding="utf-8")
PAYMENT_REPOSITORY = (
    BACKEND_ROOT / "src/repositories/PaymentRepository.cpp"
).read_text(encoding="utf-8")


class Phase8SchemaContractTest(unittest.TestCase):
    def test_payment_attempt_shape_and_state_constraints(self) -> None:
        self.assertRegex(MIGRATION, r"CREATE TABLE payment_attempts\s*\(")
        for field in (
            "started_at", "processing_deadline", "scheduled_complete_at",
            "completed_at", "timed_out_at", "accepted_at", "failure_reason",
        ):
            self.assertRegex(MIGRATION, rf"\b{field}\b")
        for status in ("PROCESSING", "SUCCEEDED", "FAILED", "TIMED_OUT"):
            self.assertIn(f"'{status}'", MIGRATION)
        self.assertIn("processing_deadline > started_at", MIGRATION)
        self.assertIn("scheduled_complete_at >= started_at", MIGRATION)
        self.assertIn("payment_attempts_state_shape_check", MIGRATION)

    def test_only_one_processing_attempt_per_order(self) -> None:
        self.assertRegex(
            MIGRATION,
            r"CREATE UNIQUE INDEX payment_attempts_one_processing_per_order_idx"
            r"[\s\S]+ON payment_attempts\(order_id\)"
            r"[\s\S]+WHERE status = 'PROCESSING'",
        )

    def test_refunds_and_notifications_are_idempotent(self) -> None:
        self.assertRegex(MIGRATION, r"payment_attempt_id\s+TEXT NOT NULL UNIQUE")
        self.assertRegex(MIGRATION, r"dedupe_key\s+TEXT NOT NULL UNIQUE")
        for notification_type in (
            "PAYMENT_SUCCEEDED", "ORDER_CANCELLED", "ORDER_EXPIRED",
            "AUTO_REFUND_COMPLETED",
        ):
            self.assertIn(f"'{notification_type}'", MIGRATION)
        self.assertIn("ON CONFLICT (payment_attempt_id) DO NOTHING", PAYMENT_REPOSITORY)

    def test_does_not_extend_order_or_checkout_states(self) -> None:
        self.assertNotIn("PAYMENT_PROCESSING", MIGRATION)
        self.assertNotIn("REFUNDED", MIGRATION)
        self.assertNotIn("ALTER TABLE orders", MIGRATION)
        self.assertNotIn("ALTER TABLE checkout_sessions", MIGRATION)

    def test_dtos_and_fresh_database_order_are_registered(self) -> None:
        for dto in ("struct PaymentAttempt", "struct PaymentStartResult", "struct UserNotification"):
            self.assertIn(dto, DTO)
        sequence = (
            "005_add_payment_lifecycle.sql", "006_demo_seed.sql",
            "007_verify_seed.sql", "008_verify_checkout_schema.sql",
            "009_verify_payment_schema.sql",
        )
        positions = [COMPOSE.index(name) for name in sequence]
        self.assertEqual(positions, sorted(positions))


if __name__ == "__main__":
    unittest.main(verbosity=2)
