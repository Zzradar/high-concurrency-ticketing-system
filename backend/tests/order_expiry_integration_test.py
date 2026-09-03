import json
import os
from pathlib import Path
import subprocess
import time
import unittest
from urllib.request import Request, urlopen


BASE_URL = os.environ.get("TICKETING_BASE_URL", "http://127.0.0.1:8080")
BACKEND_ROOT = Path(__file__).resolve().parents[1]
USER_ID = "U-1001"
SESSION_ID = "ses-concert-1001"
TEST_SEATS = [f"{SESSION_ID}-{label}" for label in ("A01", "A02", "A04")]
PREFIX = "it-phase4-expiry-"
SEED_HOLDER = "RSV-SEED-HELD-ses-concert-1001"


def psql(sql: str) -> str:
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "ticketing",
            "-d",
            "ticketing",
            "-v",
            "ON_ERROR_STOP=1",
            "-At",
            "-F",
            "\t",
            "-c",
            sql,
        ],
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"psql failed ({completed.returncode}): {completed.stderr}\nSQL: {sql}"
        )
    return completed.stdout.strip()


def cleanup_test_data() -> None:
    seat_list = ", ".join(repr(seat) for seat in TEST_SEATS)
    psql(
        f"""
        BEGIN;
        UPDATE session_seats
        SET status = 'AVAILABLE', current_reservation_id = NULL
        WHERE current_reservation_id IN (
            SELECT id FROM reservations WHERE idempotency_key LIKE '{PREFIX}%'
        ) OR id IN ({seat_list});
        DELETE FROM user_notifications WHERE order_id IN (
            SELECT id FROM orders WHERE reservation_id IN (
                SELECT id FROM reservations WHERE idempotency_key LIKE '{PREFIX}%'
            )
        );
        DELETE FROM refunds WHERE order_id IN (
            SELECT id FROM orders WHERE reservation_id IN (
                SELECT id FROM reservations WHERE idempotency_key LIKE '{PREFIX}%'
            )
        );
        DELETE FROM payment_attempts WHERE order_id IN (
            SELECT id FROM orders WHERE reservation_id IN (
                SELECT id FROM reservations WHERE idempotency_key LIKE '{PREFIX}%'
            )
        );
        DELETE FROM orders
        WHERE reservation_id IN (
            SELECT id FROM reservations WHERE idempotency_key LIKE '{PREFIX}%'
        );
        DELETE FROM reservation_session_seats
        WHERE reservation_id IN (
            SELECT id FROM reservations WHERE idempotency_key LIKE '{PREFIX}%'
        );
        DELETE FROM reservations WHERE idempotency_key LIKE '{PREFIX}%';
        COMMIT;
        """
    )


def create_order(key: str, seat_ids: list[str]) -> tuple[str, str]:
    request = Request(
        BASE_URL + "/reservations",
        data=json.dumps({"sessionId": SESSION_ID, "seatIds": seat_ids}).encode(),
        headers={
            "Content-Type": "application/json",
            "X-User-Id": USER_ID,
            "Idempotency-Key": key,
        },
        method="POST",
    )
    with urlopen(request, timeout=15) as response:
        payload = json.load(response)
        if response.status != 201:
            raise AssertionError((response.status, payload))
    return payload["order"]["id"], payload["reservation"]["id"]


def make_expired(order_id: str, reservation_id: str, minutes_ago: int = 1) -> None:
    psql(
        f"""
        BEGIN;
        UPDATE reservations
        SET created_at = CURRENT_TIMESTAMP - INTERVAL '20 minutes',
            expires_at = CURRENT_TIMESTAMP - INTERVAL '{minutes_ago} minutes'
        WHERE id = '{reservation_id}';
        UPDATE orders
        SET created_at = CURRENT_TIMESTAMP - INTERVAL '20 minutes',
            expires_at = CURRENT_TIMESTAMP - INTERVAL '{minutes_ago} minutes'
        WHERE id = '{order_id}';
        COMMIT;
        """
    )


def wait_for_order_status(order_id: str, expected: str, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if psql(f"SELECT status FROM orders WHERE id = '{order_id}';") == expected:
            return
        time.sleep(0.25)
    actual = psql(f"SELECT status FROM orders WHERE id = '{order_id}';")
    raise AssertionError(f"order {order_id}: expected {expected}, got {actual}")


def seed_distribution() -> str:
    return psql(
        """
        SELECT session.id,
               COUNT(inventory.id),
               COUNT(*) FILTER (WHERE inventory.status = 'AVAILABLE'),
               COUNT(*) FILTER (WHERE inventory.status = 'HELD'),
               COUNT(*) FILTER (WHERE inventory.status = 'SOLD')
        FROM sessions AS session
        JOIN session_seats AS inventory ON inventory.session_id = session.id
        GROUP BY session.id
        ORDER BY session.id;
        """
    )


class OrderExpiryIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        cleanup_test_data()

    def tearDown(self) -> None:
        cleanup_test_data()

    def test_expiry_is_atomic_and_preserves_history(self) -> None:
        order_id, reservation_id = create_order(
            PREFIX + "atomic", TEST_SEATS[:2]
        )
        before_history = psql(
            f"""
            SELECT COUNT(*), SUM(reserved_price)
            FROM reservation_session_seats
            WHERE reservation_id = '{reservation_id}';
            """
        )
        unrelated_before = psql(
            "SELECT status, paid_at IS NOT NULL FROM orders "
            "WHERE id = 'TKT-SEED-SOLD-ses-concert-1001';"
        )

        make_expired(order_id, reservation_id)
        wait_for_order_status(order_id, "EXPIRED")

        domain_state = psql(
            f"""
            SELECT ticket_order.status,
                   reservation.status,
                   COUNT(*) FILTER (
                       WHERE inventory.status = 'AVAILABLE'
                         AND inventory.current_reservation_id IS NULL
                   )
            FROM orders AS ticket_order
            JOIN reservations AS reservation
              ON reservation.id = ticket_order.reservation_id
            JOIN reservation_session_seats AS item
              ON item.reservation_id = reservation.id
            JOIN session_seats AS inventory
              ON inventory.id = item.session_seat_id
            WHERE ticket_order.id = '{order_id}'
            GROUP BY ticket_order.status, reservation.status;
            """
        )
        self.assertEqual(domain_state.split("\t"), ["EXPIRED", "EXPIRED", "2"])
        self.assertEqual(before_history, "2\t256000")
        self.assertEqual(
            psql(
                f"SELECT COUNT(*), SUM(reserved_price) "
                "FROM reservation_session_seats "
                f"WHERE reservation_id = '{reservation_id}';"
            ),
            before_history,
        )
        self.assertEqual(
            psql(
                "SELECT status, paid_at IS NOT NULL FROM orders "
                "WHERE id = 'TKT-SEED-SOLD-ses-concert-1001';"
            ),
            unrelated_before,
        )

    def test_owner_mismatch_rolls_back_and_does_not_stop_later_order(self) -> None:
        bad_order, bad_reservation = create_order(
            PREFIX + "bad-owner", [TEST_SEATS[0]]
        )
        good_order, good_reservation = create_order(
            PREFIX + "good-after-bad", [TEST_SEATS[1]]
        )
        psql(
            f"""
            UPDATE session_seats
            SET current_reservation_id = '{SEED_HOLDER}'
            WHERE id = '{TEST_SEATS[0]}';
            """
        )
        make_expired(bad_order, bad_reservation, minutes_ago=2)
        make_expired(good_order, good_reservation, minutes_ago=1)

        wait_for_order_status(good_order, "EXPIRED")
        time.sleep(0.5)

        bad_state = psql(
            f"""
            SELECT ticket_order.status,
                   reservation.status,
                   inventory.status,
                   inventory.current_reservation_id
            FROM orders AS ticket_order
            JOIN reservations AS reservation
              ON reservation.id = ticket_order.reservation_id
            JOIN reservation_session_seats AS item
              ON item.reservation_id = reservation.id
            JOIN session_seats AS inventory
              ON inventory.id = item.session_seat_id
            WHERE ticket_order.id = '{bad_order}';
            """
        )
        self.assertEqual(
            bad_state.split("\t"),
            ["PENDING_PAYMENT", "ACTIVE", "HELD", SEED_HOLDER],
        )
        self.assertEqual(
            psql(
                f"SELECT status, current_reservation_id IS NULL "
                f"FROM session_seats WHERE id = '{TEST_SEATS[1]}';"
            ).split("\t"),
            ["AVAILABLE", "t"],
        )

    def test_z_seed_distribution_is_restored(self) -> None:
        rows = [line.split("\t") for line in seed_distribution().splitlines()]
        self.assertEqual(len(rows), 5)
        for row in rows:
            self.assertEqual(row[1:], ["60", "51", "4", "5"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
