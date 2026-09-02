from pathlib import Path
import re
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    BACKEND_ROOT / "db/migrations/003_add_checkout_sessions.sql"
).read_text(encoding="utf-8")
REVISION_MIGRATION = (
    BACKEND_ROOT / "db/migrations/004_add_checkout_session_revision.sql"
).read_text(encoding="utf-8")
COMPOSE = (BACKEND_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
DATABASE_TEST = (
    BACKEND_ROOT / "db/tests/002_verify_checkout_schema.sql"
).read_text(encoding="utf-8")


class Phase5SchemaContractTest(unittest.TestCase):
    def test_checkout_tables_and_exact_states_exist(self) -> None:
        self.assertRegex(MIGRATION, r"CREATE TABLE checkout_sessions\s*\(")
        self.assertRegex(MIGRATION, r"CREATE TABLE checkout_session_seats\s*\(")
        for status in ("SELECTING", "SUBMITTING", "RESERVED", "ABANDONED"):
            self.assertIn(f"'{status}'", MIGRATION)
        self.assertNotIn("'EXPIRED'", MIGRATION)

    def test_identity_recovery_and_relationship_constraints(self) -> None:
        self.assertIn("active_confirm_idempotency_key", MIGRATION)
        self.assertIn("reservation_id", MIGRATION)
        self.assertRegex(MIGRATION, r"reservation_id\s+TEXT\s+UNIQUE")
        self.assertIn("PRIMARY KEY (checkout_session_id, session_seat_id)", MIGRATION)
        self.assertIn("REFERENCES session_seats(id, session_id)", MIGRATION)
        self.assertIn("REFERENCES checkout_sessions(id, session_id)", MIGRATION)
        self.assertNotRegex(MIGRATION, r"\border_id\b")
        self.assertNotRegex(MIGRATION, r"\bexpires_at\b")
        self.assertNotIn("UNIQUE (user_id, session_id)", MIGRATION)

    def test_state_shape_and_timestamps_are_database_enforced(self) -> None:
        self.assertIn("checkout_sessions_state_shape_check", MIGRATION)
        self.assertIn("status = 'SUBMITTING'", MIGRATION)
        self.assertIn("active_confirm_idempotency_key IS NOT NULL", MIGRATION)
        self.assertIn("status = 'RESERVED'", MIGRATION)
        self.assertIn("reservation_id IS NOT NULL", MIGRATION)
        self.assertRegex(MIGRATION, r"created_at\s+TIMESTAMPTZ\s+NOT NULL")
        self.assertRegex(MIGRATION, r"updated_at\s+TIMESTAMPTZ\s+NOT NULL")

    def test_seat_revision_is_nonnegative_and_defaults_to_zero(self) -> None:
        self.assertRegex(
            REVISION_MIGRATION,
            r"revision\s+BIGINT\s+NOT NULL\s+DEFAULT\s+0",
        )
        self.assertIn("CHECK (revision >= 0)", REVISION_MIGRATION)

    def test_compose_applies_phase5_before_seed_and_verify(self) -> None:
        expected = (
            "/docker-entrypoint-initdb.d/001_initial_schema.sql",
            "/docker-entrypoint-initdb.d/002_add_reservation_idempotency.sql",
            "/docker-entrypoint-initdb.d/003_add_checkout_sessions.sql",
            "/docker-entrypoint-initdb.d/004_add_checkout_session_revision.sql",
            "/docker-entrypoint-initdb.d/005_demo_seed.sql",
            "/docker-entrypoint-initdb.d/006_verify_seed.sql",
            "/docker-entrypoint-initdb.d/007_verify_checkout_schema.sql",
        )
        positions = [COMPOSE.index(path) for path in expected]
        self.assertEqual(positions, sorted(positions))

    def test_database_verification_exercises_key_constraints(self) -> None:
        self.assertIn("WHEN check_violation", DATABASE_TEST)
        self.assertIn("WHEN unique_violation", DATABASE_TEST)
        self.assertIn("WHEN foreign_key_violation", DATABASE_TEST)
        self.assertIn("ROLLBACK", DATABASE_TEST)


if __name__ == "__main__":
    unittest.main()
