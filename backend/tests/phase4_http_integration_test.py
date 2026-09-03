import json
import os
from datetime import datetime
from pathlib import Path
import subprocess
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BASE_URL = os.environ.get("TICKETING_BASE_URL", "http://127.0.0.1:8080")
BACKEND_ROOT = Path(__file__).resolve().parents[1]
USER_ID = "U-1001"
OTHER_USER_ID = "U-SEED-HOLDER"
SESSION_ID = "ses-concert-1001"
SEAT_ID = f"{SESSION_ID}-A01"
KEY_PREFIX = "it-phase4-"


def psql(sql: str) -> str:
    command = [
        "docker", "compose", "exec", "-T", "postgres", "psql",
        "-U", "ticketing", "-d", "ticketing", "-v", "ON_ERROR_STOP=1",
        "-At", "-F", "\t", "-c", sql,
    ]
    completed = subprocess.run(
        command,
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


def cleanup_phase4_data() -> None:
    psql(
        f"""
        BEGIN;
        UPDATE session_seats
        SET status = 'AVAILABLE', current_reservation_id = NULL
        WHERE current_reservation_id IN (
            SELECT id FROM reservations
            WHERE idempotency_key LIKE '{KEY_PREFIX}%'
        ) OR id = '{SEAT_ID}';
        DELETE FROM user_notifications WHERE order_id IN (
            SELECT id FROM orders WHERE reservation_id IN (
                SELECT id FROM reservations WHERE idempotency_key LIKE '{KEY_PREFIX}%'
            )
        );
        DELETE FROM refunds WHERE order_id IN (
            SELECT id FROM orders WHERE reservation_id IN (
                SELECT id FROM reservations WHERE idempotency_key LIKE '{KEY_PREFIX}%'
            )
        );
        DELETE FROM payment_attempts WHERE order_id IN (
            SELECT id FROM orders WHERE reservation_id IN (
                SELECT id FROM reservations WHERE idempotency_key LIKE '{KEY_PREFIX}%'
            )
        );
        DELETE FROM orders
        WHERE reservation_id IN (
            SELECT id FROM reservations
            WHERE idempotency_key LIKE '{KEY_PREFIX}%'
        );
        DELETE FROM reservation_session_seats
        WHERE reservation_id IN (
            SELECT id FROM reservations
            WHERE idempotency_key LIKE '{KEY_PREFIX}%'
        );
        DELETE FROM reservations
        WHERE idempotency_key LIKE '{KEY_PREFIX}%';
        COMMIT;
        """
    )


def request_json(path: str, *, method: str = "GET", user_id: str | None = USER_ID,
                 body=None, idempotency_key: str | None = None):
    headers = {"Content-Type": "application/json"}
    if user_id is not None:
        headers["X-User-Id"] = user_id
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(BASE_URL + path, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)
    except Exception as error:
        raise AssertionError(
            f"Backend is required at {BASE_URL}; {method} {path} failed: {error}"
        ) from error


def create_pending_order(key: str = "it-phase4-get"):
    status, payload = request_json(
        "/reservations",
        method="POST",
        body={"sessionId": SESSION_ID, "seatIds": [SEAT_ID]},
        idempotency_key=key,
    )
    if status != 201:
        raise AssertionError((status, payload))
    return payload["order"]


def assert_iso_utc(test: unittest.TestCase, value: str) -> None:
    test.assertTrue(value.endswith("Z"), value)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    test.assertIsNotNone(parsed.tzinfo)


class OrderGetHttpIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        cleanup_phase4_data()

    def tearDown(self) -> None:
        cleanup_phase4_data()

    def test_current_user_reads_complete_pending_order_without_mutation(self) -> None:
        created = create_pending_order()
        before = psql(
            f"""
            SELECT ticket_order.status, reservation.status,
                   inventory.status, inventory.current_reservation_id
            FROM orders AS ticket_order
            JOIN reservations AS reservation
                ON reservation.id = ticket_order.reservation_id
            JOIN reservation_session_seats AS item
                ON item.reservation_id = reservation.id
            JOIN session_seats AS inventory
                ON inventory.id = item.session_seat_id
            WHERE ticket_order.id = '{created['id']}';
            """
        )

        status, order = request_json(f"/orders/{created['id']}")
        self.assertEqual(status, 200, order)
        self.assertEqual(set(order), {
            "id", "reservationId", "eventId", "sessionId", "seatIds",
            "status", "totalAmount", "expiresAt", "createdAt",
        })
        self.assertEqual(order["id"], created["id"])
        self.assertEqual(order["reservationId"], created["reservationId"])
        self.assertEqual(order["eventId"], "evt-concert-2026")
        self.assertEqual(order["sessionId"], SESSION_ID)
        self.assertEqual(order["seatIds"], [SEAT_ID])
        self.assertEqual(order["status"], "PENDING_PAYMENT")
        self.assertEqual(order["totalAmount"], 128000)
        assert_iso_utc(self, order["expiresAt"])
        assert_iso_utc(self, order["createdAt"])
        self.assertNotIn("paidAt", order)

        after = psql(
            f"""
            SELECT ticket_order.status, reservation.status,
                   inventory.status, inventory.current_reservation_id
            FROM orders AS ticket_order
            JOIN reservations AS reservation
                ON reservation.id = ticket_order.reservation_id
            JOIN reservation_session_seats AS item
                ON item.reservation_id = reservation.id
            JOIN session_seats AS inventory
                ON inventory.id = item.session_seat_id
            WHERE ticket_order.id = '{created['id']}';
            """
        )
        self.assertEqual(after, before)

    def test_missing_and_other_user_do_not_reveal_order(self) -> None:
        created = create_pending_order()
        for order_id, user_id in (
            ("TKT-NOT-PRESENT", USER_ID),
            (created["id"], OTHER_USER_ID),
        ):
            with self.subTest(order_id=order_id, user_id=user_id):
                status, payload = request_json(
                    f"/orders/{order_id}", user_id=user_id
                )
                self.assertEqual(status, 404)
                self.assertEqual(payload, {
                    "code": "ORDER_NOT_FOUND",
                    "message": "Order not found",
                })

    def test_invalid_user_header_matches_reservation_validation(self) -> None:
        for user_id in (None, "", "U-NOT-PRESENT"):
            with self.subTest(user_id=user_id):
                status, payload = request_json(
                    "/orders/TKT-NOT-PRESENT", user_id=user_id
                )
                self.assertEqual(status, 400)
                self.assertEqual(payload["code"], "INVALID_ARGUMENT")

    def test_paid_seed_order_includes_paid_at(self) -> None:
        order_id = "TKT-SEED-SOLD-ses-concert-1001"
        status, order = request_json(
            f"/orders/{order_id}", user_id=OTHER_USER_ID
        )
        self.assertEqual(status, 200, order)
        self.assertEqual(order["status"], "PAID")
        assert_iso_utc(self, order["paidAt"])

    def test_cancel_is_atomic_and_idempotent(self) -> None:
        created = create_pending_order("it-phase4-cancel")
        first_status, first = request_json(
            f"/orders/{created['id']}/cancel", method="POST"
        )
        second_status, second = request_json(
            f"/orders/{created['id']}/cancel", method="POST"
        )
        self.assertEqual((first_status, second_status), (200, 200))
        self.assertEqual((first["status"], second["status"]), ("CANCELLED", "CANCELLED"))
        state = psql(
            f"""
            SELECT ticket_order.status, reservation.status,
                   inventory.status, inventory.current_reservation_id IS NULL,
                   COUNT(notification.id)
            FROM orders AS ticket_order
            JOIN reservations AS reservation ON reservation.id = ticket_order.reservation_id
            JOIN reservation_session_seats AS item ON item.reservation_id = reservation.id
            JOIN session_seats AS inventory ON inventory.id = item.session_seat_id
            LEFT JOIN user_notifications AS notification
              ON notification.order_id = ticket_order.id
             AND notification.type = 'ORDER_CANCELLED'
            WHERE ticket_order.id = '{created['id']}'
            GROUP BY ticket_order.status, reservation.status,
                     inventory.status, inventory.current_reservation_id;
            """
        )
        self.assertEqual(state.split("\t"), ["CANCELLED", "CANCELLED", "AVAILABLE", "t", "1"])

    def test_cancel_discovers_expiry_and_returns_expired(self) -> None:
        created = create_pending_order("it-phase4-cancel-expired")
        reservation_id = created["reservationId"]
        psql(
            f"""
            UPDATE reservations SET created_at = clock_timestamp() - INTERVAL '20 minutes',
                expires_at = clock_timestamp() - INTERVAL '1 minute'
            WHERE id = '{reservation_id}';
            UPDATE orders SET created_at = clock_timestamp() - INTERVAL '20 minutes',
                expires_at = clock_timestamp() - INTERVAL '1 minute'
            WHERE id = '{created['id']}';
            """
        )
        status, payload = request_json(f"/orders/{created['id']}/cancel", method="POST")
        self.assertEqual(status, 409, payload)
        self.assertEqual(payload["code"], "ORDER_EXPIRED")
        self.assertEqual(psql(f"SELECT status FROM orders WHERE id = '{created['id']}';"), "EXPIRED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
