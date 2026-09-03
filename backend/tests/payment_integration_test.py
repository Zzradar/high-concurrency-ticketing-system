from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BASE_URL = os.environ.get("TICKETING_BASE_URL", "http://127.0.0.1:8080")
BACKEND_ROOT = Path(__file__).resolve().parents[1]
USER_ID = "U-PHASE8-A"
OTHER_USER_ID = "U-PHASE8-B"
SESSION_ID = "ses-concert-1001"
PREFIX = "it-phase8-"
SEATS = [f"{SESSION_ID}-{label}" for label in ("A01", "A02", "A04", "A05", "A06")]


def psql(sql: str) -> str:
    completed = subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "ticketing",
         "-d", "ticketing", "-v", "ON_ERROR_STOP=1", "-At", "-F", "\t", "-c", sql],
        cwd=BACKEND_ROOT, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    if completed.returncode:
        raise AssertionError(f"psql failed: {completed.stderr}\n{sql}")
    return completed.stdout.strip()


def request_json(path: str, *, method="GET", user_id=USER_ID, body=None):
    headers = {"Content-Type": "application/json", "X-User-Id": user_id}
    data = None if body is None else json.dumps(body).encode()
    request = Request(BASE_URL + path, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)


def cleanup(*, create_users=False) -> None:
    users = f"'{USER_ID}', '{OTHER_USER_ID}'"
    seat_list = ", ".join(repr(value) for value in SEATS)
    psql(
        f"""
        BEGIN;
        DELETE FROM checkout_sessions WHERE user_id IN ({users});
        UPDATE session_seats SET status = 'AVAILABLE', current_reservation_id = NULL
        WHERE id IN ({seat_list}) OR current_reservation_id IN (
            SELECT id FROM reservations WHERE user_id IN ({users})
        );
        DELETE FROM user_notifications WHERE user_id IN ({users});
        DELETE FROM refunds WHERE order_id IN (SELECT id FROM orders WHERE user_id IN ({users}));
        DELETE FROM payment_attempts WHERE order_id IN (SELECT id FROM orders WHERE user_id IN ({users}));
        DELETE FROM orders WHERE user_id IN ({users});
        DELETE FROM reservation_session_seats WHERE reservation_id IN (
            SELECT id FROM reservations WHERE user_id IN ({users})
        );
        DELETE FROM reservations WHERE user_id IN ({users});
        DELETE FROM app_users WHERE id IN ({users});
        COMMIT;
        """
    )
    if create_users:
        psql(
            f"INSERT INTO app_users (id, display_name) VALUES "
            f"('{USER_ID}', 'Phase 8 user'), ('{OTHER_USER_ID}', 'Phase 8 other');"
        )


def create_order(key: str, seat_id: str):
    request = Request(
        BASE_URL + "/reservations",
        data=json.dumps({"sessionId": SESSION_ID, "seatIds": [seat_id]}).encode(),
        headers={"Content-Type": "application/json", "X-User-Id": USER_ID,
                 "Idempotency-Key": PREFIX + key}, method="POST",
    )
    with urlopen(request, timeout=30) as response:
        payload = json.load(response)
        if response.status != 201:
            raise AssertionError((response.status, payload))
    return payload["order"], payload["reservation"]


def wait_attempt(attempt_id: str, statuses=("SUCCEEDED", "FAILED"), timeout=12):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, payload = request_json(f"/payment-attempts/{attempt_id}")
        if status == 200 and payload["status"] in statuses:
            return payload
        time.sleep(0.2)
    raise AssertionError(psql(f"SELECT status FROM payment_attempts WHERE id = '{attempt_id}';"))


class PaymentIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        cleanup(create_users=True)

    def tearDown(self) -> None:
        time.sleep(0.1)
        cleanup()

    def test_concurrent_start_reuses_attempt_and_success_is_atomic(self) -> None:
        order, reservation = create_order("success", SEATS[0])
        with ThreadPoolExecutor(max_workers=10) as executor:
            responses = list(executor.map(
                lambda _: request_json(f"/orders/{order['id']}/pay", method="POST"),
                range(10),
            ))
        self.assertEqual({status for status, _ in responses}, {202})
        attempt_ids = {body["paymentAttempt"]["id"] for _, body in responses}
        self.assertEqual(len(attempt_ids), 1)
        attempt = wait_attempt(attempt_ids.pop())
        self.assertEqual(attempt["status"], "SUCCEEDED")
        self.assertIn("acceptedAt", attempt)
        state = psql(
            f"""
            SELECT o.status, r.status, s.status, s.current_reservation_id IS NULL,
                   COUNT(n.id)
            FROM orders o JOIN reservations r ON r.id=o.reservation_id
            JOIN reservation_session_seats x ON x.reservation_id=r.id
            JOIN session_seats s ON s.id=x.session_seat_id
            LEFT JOIN user_notifications n ON n.order_id=o.id AND n.type='PAYMENT_SUCCEEDED'
            WHERE o.id='{order['id']}'
            GROUP BY o.status,r.status,s.status,s.current_reservation_id;
            """
        )
        self.assertEqual(state.split("\t"), ["PAID", "CONFIRMED", "SOLD", "t", "1"])
        status, replay = request_json(f"/orders/{order['id']}/pay", method="POST")
        self.assertEqual(status, 200)
        self.assertEqual(replay["order"]["status"], "PAID")
        self.assertEqual(replay["paymentAttempt"]["id"], attempt["id"])

    def test_cancel_during_processing_keeps_attempt_and_late_success_refunds(self) -> None:
        order, _ = create_order("cancel-late", SEATS[1])
        status, started = request_json(f"/orders/{order['id']}/pay", method="POST")
        self.assertEqual(status, 202)
        attempt_id = started["paymentAttempt"]["id"]
        cancel_status, cancelled = request_json(f"/orders/{order['id']}/cancel", method="POST")
        self.assertEqual((cancel_status, cancelled["status"]), (200, "CANCELLED"))
        self.assertEqual(psql(f"SELECT status FROM payment_attempts WHERE id='{attempt_id}';"), "PROCESSING")
        attempt = wait_attempt(attempt_id)
        self.assertNotIn("acceptedAt", attempt)
        state = psql(
            f"""
            SELECT o.status, r.status, s.status,
                   (SELECT COUNT(*) FROM refunds WHERE payment_attempt_id='{attempt_id}'),
                   (SELECT COUNT(*) FROM user_notifications WHERE order_id=o.id AND type='AUTO_REFUND_COMPLETED')
            FROM orders o JOIN reservations r ON r.id=o.reservation_id
            JOIN reservation_session_seats x ON x.reservation_id=r.id
            JOIN session_seats s ON s.id=x.session_seat_id
            WHERE o.id='{order['id']}';
            """
        )
        self.assertEqual(state.split("\t"), ["CANCELLED", "CANCELLED", "AVAILABLE", "1", "1"])

    def test_late_success_expires_without_reviving_inventory(self) -> None:
        order, reservation = create_order("expired-late", SEATS[2])
        _, started = request_json(f"/orders/{order['id']}/pay", method="POST")
        attempt_id = started["paymentAttempt"]["id"]
        psql(
            f"""
            UPDATE payment_attempts
            SET started_at=clock_timestamp()-INTERVAL '20 seconds',
                processing_deadline=clock_timestamp()-INTERVAL '1 second'
            WHERE id='{attempt_id}';
            UPDATE reservations SET created_at=clock_timestamp()-INTERVAL '20 minutes',
                expires_at=clock_timestamp()-INTERVAL '1 second' WHERE id='{reservation['id']}';
            UPDATE orders SET created_at=clock_timestamp()-INTERVAL '20 minutes',
                expires_at=clock_timestamp()-INTERVAL '1 second' WHERE id='{order['id']}';
            """
        )
        attempt = wait_attempt(attempt_id)
        self.assertNotIn("acceptedAt", attempt)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline and psql(f"SELECT status FROM orders WHERE id='{order['id']}';") != "EXPIRED":
            time.sleep(0.2)
        self.assertEqual(psql(f"SELECT status FROM orders WHERE id='{order['id']}';"), "EXPIRED")
        self.assertEqual(psql(f"SELECT status FROM session_seats WHERE id='{SEATS[2]}';"), "AVAILABLE")
        self.assertEqual(psql(f"SELECT COUNT(*) FROM refunds WHERE payment_attempt_id='{attempt_id}';"), "1")

    def test_timed_out_attempt_can_refund_after_another_attempt_is_accepted(self) -> None:
        order, _ = create_order("duplicate-late", SEATS[3])
        _, first = request_json(f"/orders/{order['id']}/pay", method="POST")
        first_id = first["paymentAttempt"]["id"]
        psql(
            f"UPDATE payment_attempts "
            f"SET started_at=clock_timestamp()-INTERVAL '20 seconds', "
            f"processing_deadline=clock_timestamp()-INTERVAL '1 second' "
            f"WHERE id='{first_id}';"
        )
        status, second = request_json(f"/orders/{order['id']}/pay", method="POST")
        self.assertEqual(status, 202)
        second_id = second["paymentAttempt"]["id"]
        self.assertNotEqual(first_id, second_id)
        first_result = wait_attempt(first_id)
        second_result = wait_attempt(second_id)
        accepted = [value for value in (first_result, second_result) if "acceptedAt" in value]
        self.assertEqual(len(accepted), 1)
        unaccepted = first_result if "acceptedAt" not in first_result else second_result
        self.assertEqual(psql(f"SELECT COUNT(*) FROM refunds WHERE payment_attempt_id='{unaccepted['id']}';"), "1")
        self.assertEqual(psql(f"SELECT status FROM orders WHERE id='{order['id']}';"), "PAID")

    def test_checkout_stays_reserved_and_notification_ownership_is_enforced(self) -> None:
        order, reservation = create_order("checkout-stays", SEATS[4])
        psql(
            f"""
            INSERT INTO checkout_sessions (
                id,user_id,session_id,status,active_confirm_idempotency_key,reservation_id
            ) VALUES ('CHK-PHASE8-STAYS','{USER_ID}','{SESSION_ID}','RESERVED','phase8-k1','{reservation['id']}');
            """
        )
        _, started = request_json(f"/orders/{order['id']}/pay", method="POST")
        attempt = wait_attempt(started["paymentAttempt"]["id"])
        self.assertIn("acceptedAt", attempt)
        self.assertEqual(psql("SELECT status FROM checkout_sessions WHERE id='CHK-PHASE8-STAYS';"), "RESERVED")
        status, _ = request_json(f"/payment-attempts/{attempt['id']}", user_id=OTHER_USER_ID)
        self.assertEqual(status, 404)
        status, notifications = request_json("/notifications")
        self.assertEqual(status, 200)
        notification = next(item for item in notifications if item["orderId"] == order["id"])
        foreign_status, _ = request_json(
            f"/notifications/{notification['id']}/read", method="POST", user_id=OTHER_USER_ID
        )
        self.assertEqual(foreign_status, 404)
        read_status, read = request_json(f"/notifications/{notification['id']}/read", method="POST")
        self.assertEqual(read_status, 200)
        self.assertIn("readAt", read)


if __name__ == "__main__":
    unittest.main(verbosity=2)
