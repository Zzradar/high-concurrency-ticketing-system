from pathlib import Path
import re
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = (BACKEND_ROOT / "db/migrations/001_initial_schema.sql").read_text(encoding="utf-8")
SEED = (BACKEND_ROOT / "db/seeds/001_demo_seed.sql").read_text(encoding="utf-8")


class SchemaContractTest(unittest.TestCase):
    def test_required_tables_exist(self) -> None:
        for table in (
            "events",
            "sessions",
            "seats",
            "session_seats",
            "reservations",
            "reservation_session_seats",
            "orders",
        ):
            self.assertRegex(SCHEMA, rf"CREATE TABLE\s+{table}\s*\(")

    def test_inventory_and_order_statuses_are_exact(self) -> None:
        for status in ("AVAILABLE", "HELD", "SOLD"):
            self.assertIn(f"'{status}'", SCHEMA)
        for status in ("ACTIVE", "CONFIRMED", "CANCELLED", "EXPIRED"):
            self.assertIn(f"'{status}'", SCHEMA)
        for status in ("PENDING_PAYMENT", "PAID", "CANCELLED", "EXPIRED"):
            self.assertIn(f"'{status}'", SCHEMA)
        self.assertNotIn("'SELECTED'", SCHEMA)

    def test_money_and_time_types_follow_contract(self) -> None:
        for column in ("price", "reserved_price", "total_amount"):
            self.assertRegex(SCHEMA, rf"{column}\s+BIGINT\s+NOT NULL")
        for column in ("start_time", "gate_time", "expires_at", "created_at"):
            self.assertRegex(SCHEMA, rf"{column}\s+TIMESTAMPTZ\s+NOT NULL")

    def test_session_seat_uniqueness_and_reservation_link(self) -> None:
        self.assertIn("UNIQUE (session_id, seat_id)", SCHEMA)
        self.assertIn("current_reservation_id", SCHEMA)
        self.assertIn("PRIMARY KEY (reservation_id, session_seat_id)", SCHEMA)

        seats_table = SCHEMA.split("CREATE TABLE seats (", 1)[1].split(
            "CREATE INDEX seats_venue_row_number_idx", 1
        )[0]
        self.assertNotRegex(seats_table, r"\bstatus\b")

    def test_seed_matches_frontend_demo_shape(self) -> None:
        for event_id in ("evt-concert-2026", "evt-basketball-finals"):
            self.assertIn(event_id, SEED)
        for session_id in (
            "ses-concert-1001",
            "ses-concert-1002",
            "ses-concert-1003",
            "ses-basketball-2001",
            "ses-basketball-2002",
        ):
            self.assertIn(session_id, SEED)
        self.assertIn("generate_series(1, 10)", SEED)
        self.assertRegex(SEED, re.compile(r"\('A'\).*\('F'\)", re.DOTALL))
        self.assertIn("'U-1001'", SEED)


if __name__ == "__main__":
    unittest.main()
