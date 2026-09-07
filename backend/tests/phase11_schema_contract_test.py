from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (ROOT / "db/migrations/007_add_payment_provider_recovery.sql").read_text(encoding="utf-8")


class Phase11SchemaContractTest(unittest.TestCase):
    def test_lease_migration_preserves_business_checks(self):
        migration = (ROOT / "db/migrations/008_add_reconciliation_leases.sql").read_text(encoding="utf-8")
        self.assertNotIn("DROP CONSTRAINT", migration)
        self.assertNotIn("CREATE TABLE", migration)
        self.assertNotIn("payment_provider_events", migration)
        for field in ("reconciliation_lease_until", "reconciliation_lease_token"):
            self.assertEqual(migration.count("ADD COLUMN " + field), 2)

    def test_attempt_provider_recovery_shape(self):
        for field in ("provider_payment_id", "provider_status", "provider_last_sync_at",
                      "provider_terminal_at", "provider_retry_count", "next_reconcile_at"):
            self.assertIn(field, MIGRATION)
        self.assertIn("ALTER COLUMN scheduled_complete_at DROP NOT NULL", MIGRATION)
        self.assertIn("payment_attempts_provider_payment_unique_idx", MIGRATION)

    def test_async_refund_shape(self):
        for value in ("'SYSTEM'", "'BUYER'", "'PROCESSING'", "'SUCCEEDED'", "'FAILED'"):
            self.assertIn(value, MIGRATION)
        self.assertIn("refunds_state_shape_check", MIGRATION)
        self.assertIn("refunds_provider_refund_unique_idx", MIGRATION)
        self.assertIn("AUTO_REFUND_FAILED", MIGRATION)

    def test_inbox_does_not_store_payload(self):
        self.assertIn("CREATE TABLE payment_provider_events", MIGRATION)
        self.assertIn("payload_sha256", MIGRATION)
        self.assertNotIn("raw_payload", MIGRATION)
        self.assertIn("UNIQUE (provider, provider_event_id)", MIGRATION)


if __name__ == "__main__":
    unittest.main(verbosity=2)
