from pathlib import Path
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    BACKEND_ROOT / "db/migrations/002_add_reservation_idempotency.sql"
).read_text(encoding="utf-8")
COMPOSE = (BACKEND_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
INITIAL_SCHEMA = (
    BACKEND_ROOT / "db/migrations/001_initial_schema.sql"
).read_text(encoding="utf-8")
SEED = (BACKEND_ROOT / "db/seeds/001_demo_seed.sql").read_text(encoding="utf-8")


class Phase3SchemaContractTest(unittest.TestCase):
    def test_migration_adds_nullable_bounded_idempotency_key(self) -> None:
        self.assertIn("ADD COLUMN idempotency_key TEXT", MIGRATION)
        self.assertIn(
            "reservations_idempotency_key_length_check", MIGRATION
        )
        self.assertIn("char_length(idempotency_key) BETWEEN 1 AND 128", MIGRATION)
        self.assertIn("reservations_user_idempotency_unique", MIGRATION)
        self.assertIn("UNIQUE (user_id, idempotency_key)", MIGRATION)
        self.assertNotIn("NOT NULL", MIGRATION)

    def test_initial_schema_and_seed_remain_pre_phase3(self) -> None:
        self.assertNotIn("idempotency_key", INITIAL_SCHEMA)
        self.assertNotIn("idempotency_key", SEED)

    def test_compose_fresh_init_order_is_schema_migration_seed_verify(self) -> None:
        expected = (
            "/docker-entrypoint-initdb.d/001_initial_schema.sql",
            "/docker-entrypoint-initdb.d/002_add_reservation_idempotency.sql",
            "/docker-entrypoint-initdb.d/003_add_checkout_sessions.sql",
            "/docker-entrypoint-initdb.d/004_add_checkout_session_revision.sql",
            "/docker-entrypoint-initdb.d/005_add_payment_lifecycle.sql",
            "/docker-entrypoint-initdb.d/006_add_user_authentication.sql",
            "/docker-entrypoint-initdb.d/007_demo_seed.sql",
            "/docker-entrypoint-initdb.d/008_verify_seed.sql",
        )
        positions = [COMPOSE.index(path) for path in expected]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("db/seeds/001_demo_seed.sql", COMPOSE)
        self.assertNotIn("db/seeds/003_demo_seed.sql", COMPOSE)


if __name__ == "__main__":
    unittest.main()
