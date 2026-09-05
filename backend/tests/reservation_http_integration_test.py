import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import subprocess
import threading
import unittest

from auth_test_support import anonymous_request, client_for, reset_auth_clients


BASE_URL = os.environ.get("TICKETING_BASE_URL", "http://127.0.0.1:8080")
BACKEND_ROOT = Path(__file__).resolve().parents[1]
USER_ID = "U-1001"
SESSION_ID = "ses-concert-1001"
TEST_SEATS = [f"{SESSION_ID}-{label}" for label in ("A01", "A02", "A04")]


def psql(sql: str) -> str:
    command = [
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


def cleanup_phase3_data() -> None:
    reset_auth_clients()
    seat_list = ", ".join(f"'{seat}'" for seat in TEST_SEATS)
    psql(
        f"""
        BEGIN;
        UPDATE session_seats
        SET status = 'AVAILABLE', current_reservation_id = NULL
        WHERE current_reservation_id IN (
            SELECT id FROM reservations
            WHERE idempotency_key LIKE 'it-phase3-%'
        ) OR id IN ({seat_list});
        DELETE FROM user_notifications WHERE order_id IN (
            SELECT id FROM orders WHERE reservation_id IN (
                SELECT id FROM reservations WHERE idempotency_key LIKE 'it-phase3-%'
            )
        );
        DELETE FROM orders
        WHERE reservation_id IN (
            SELECT id FROM reservations
            WHERE idempotency_key LIKE 'it-phase3-%'
        );
        DELETE FROM reservation_session_seats
        WHERE reservation_id IN (
            SELECT id FROM reservations
            WHERE idempotency_key LIKE 'it-phase3-%'
        );
        DELETE FROM reservations
        WHERE idempotency_key LIKE 'it-phase3-%';
        UPDATE sessions SET status = 'ON_SALE' WHERE id = '{SESSION_ID}';
        COMMIT;
        """
    )


def request_json(
    *,
    body=None,
    raw_body: bytes | None = None,
    user_id: str | None = USER_ID,
    idempotency_key: str | None = None,
    timeout: float = 30,
):
    headers = {}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    if user_id is None or user_id == "":
        status, payload, _ = anonymous_request(
            "/reservations", method="POST", body=body, raw_body=raw_body,
            headers=headers, timeout=timeout,
        )
    else:
        status, payload, _ = client_for(user_id).request(
            "/reservations", method="POST", body=body, raw_body=raw_body,
            headers=headers, timeout=timeout,
        )
    return status, payload


def get_json(path: str):
    status, payload, _ = anonymous_request(path, timeout=10)
    return status, payload


def assert_iso_utc(test: unittest.TestCase, value: str) -> None:
    test.assertTrue(value.endswith("Z"), value)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    test.assertIsNotNone(parsed.tzinfo)


def prefix_counts(prefix: str) -> tuple[int, int, int]:
    output = psql(
        f"""
        SELECT
            COUNT(DISTINCT reservation.id),
            COUNT(DISTINCT ticket_order.id),
            COUNT(item.session_seat_id)
        FROM reservations AS reservation
        LEFT JOIN orders AS ticket_order
            ON ticket_order.reservation_id = reservation.id
        LEFT JOIN reservation_session_seats AS item
            ON item.reservation_id = reservation.id
        WHERE reservation.idempotency_key LIKE '{prefix}%';
        """
    )
    reservation_count, order_count, item_count = output.split("\t")
    return int(reservation_count), int(order_count), int(item_count)


class ReservationHttpIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        cleanup_phase3_data()

    def tearDown(self) -> None:
        cleanup_phase3_data()

    def assert_result(self, payload, seat_ids, total_amount) -> None:
        self.assertEqual(set(payload), {"reservation", "order"})
        reservation = payload["reservation"]
        order = payload["order"]
        self.assertEqual(reservation["userId"], USER_ID)
        self.assertEqual(reservation["sessionId"], SESSION_ID)
        self.assertEqual(reservation["seatIds"], sorted(seat_ids))
        self.assertEqual(reservation["status"], "ACTIVE")
        self.assertTrue(reservation["id"].startswith("RSV-"))
        self.assertEqual(order["reservationId"], reservation["id"])
        self.assertEqual(order["eventId"], "evt-concert-2026")
        self.assertEqual(order["sessionId"], SESSION_ID)
        self.assertEqual(order["seatIds"], sorted(seat_ids))
        self.assertEqual(order["status"], "PENDING_PAYMENT")
        self.assertEqual(order["totalAmount"], total_amount)
        self.assertTrue(order["id"].startswith("TKT-"))
        self.assertNotIn("paidAt", order)
        self.assertEqual(reservation["expiresAt"], order["expiresAt"])
        self.assertEqual(reservation["createdAt"], order["createdAt"])
        assert_iso_utc(self, reservation["expiresAt"])
        assert_iso_utc(self, reservation["createdAt"])

    def test_basic_success_and_database_invariants(self) -> None:
        status, payload = request_json(
            body={"sessionId": SESSION_ID, "seatIds": TEST_SEATS[:2]},
            idempotency_key="it-phase3-basic",
        )
        self.assertEqual(status, 201, payload)
        self.assert_result(payload, TEST_SEATS[:2], 256000)

        get_status, seats = get_json(f"/sessions/{SESSION_ID}/seats")
        self.assertEqual(get_status, 200)
        states = {seat["id"]: seat["status"] for seat in seats}
        self.assertEqual([states[seat] for seat in TEST_SEATS[:2]], ["HELD", "HELD"])

        invariant = psql(
            """
            SELECT
                COUNT(*) FILTER (
                    WHERE inventory.status = 'HELD'
                      AND inventory.current_reservation_id IS NOT NULL
                ),
                ticket_order.total_amount,
                SUM(item.reserved_price),
                reservation.expires_at = ticket_order.expires_at,
                COUNT(DISTINCT item.session_id)
            FROM reservations AS reservation
            JOIN orders AS ticket_order
                ON ticket_order.reservation_id = reservation.id
            JOIN reservation_session_seats AS item
                ON item.reservation_id = reservation.id
            JOIN session_seats AS inventory
                ON inventory.id = item.session_seat_id
            WHERE reservation.idempotency_key = 'it-phase3-basic'
            GROUP BY ticket_order.total_amount,
                     reservation.expires_at,
                     ticket_order.expires_at;
            """
        )
        self.assertEqual(invariant.split("\t"), ["2", "256000", "256000", "t", "1"])

    def test_same_key_accepts_different_input_order(self) -> None:
        key = "it-phase3-order-normalization"
        first_status, first = request_json(
            body={"sessionId": SESSION_ID, "seatIds": TEST_SEATS[:2]},
            idempotency_key=key,
        )
        second_status, second = request_json(
            body={"sessionId": SESSION_ID, "seatIds": list(reversed(TEST_SEATS[:2]))},
            idempotency_key=key,
        )
        self.assertEqual(first_status, 201, first)
        self.assertEqual(second_status, 200, second)
        self.assertEqual(second, first)
        self.assertEqual(prefix_counts(key), (1, 1, 2))

    def test_same_key_different_request_is_idempotency_conflict(self) -> None:
        key = "it-phase3-content-conflict"
        first_status, _ = request_json(
            body={"sessionId": SESSION_ID, "seatIds": [TEST_SEATS[0]]},
            idempotency_key=key,
        )
        second_status, error = request_json(
            body={"sessionId": SESSION_ID, "seatIds": [TEST_SEATS[1]]},
            idempotency_key=key,
        )
        self.assertEqual(first_status, 201)
        self.assertEqual(second_status, 409)
        self.assertEqual(error, {
            "code": "IDEMPOTENCY_CONFLICT",
            "message": "Idempotency key was already used for a different reservation request",
        })
        self.assertEqual(prefix_counts(key), (1, 1, 1))

    def test_different_key_seat_conflict_rolls_back_loser(self) -> None:
        winner_key = "it-phase3-seat-winner"
        loser_key = "it-phase3-seat-loser"
        winner_status, _ = request_json(
            body={"sessionId": SESSION_ID, "seatIds": [TEST_SEATS[0]]},
            idempotency_key=winner_key,
        )
        loser_status, error = request_json(
            body={"sessionId": SESSION_ID, "seatIds": [TEST_SEATS[0]]},
            idempotency_key=loser_key,
        )
        self.assertEqual(winner_status, 201)
        self.assertEqual(loser_status, 409)
        self.assertEqual(error, {
            "code": "SEAT_CONFLICT",
            "message": "Selected seats are no longer available",
        })
        self.assertEqual(prefix_counts(winner_key), (1, 1, 1))
        self.assertEqual(prefix_counts(loser_key), (0, 0, 0))

    def test_same_key_true_concurrency_returns_one_business_result(self) -> None:
        request_count = 12
        barrier = threading.Barrier(request_count)
        key = "it-phase3-same-key-concurrent"

        def send(_):
            barrier.wait()
            return request_json(
                body={"sessionId": SESSION_ID, "seatIds": TEST_SEATS[:2]},
                idempotency_key=key,
            )

        with ThreadPoolExecutor(max_workers=request_count) as executor:
            responses = list(executor.map(send, range(request_count)))

        statuses = [status for status, _ in responses]
        self.assertEqual(statuses.count(201), 1, statuses)
        self.assertEqual(statuses.count(200), request_count - 1, statuses)
        payloads = [json.dumps(payload, sort_keys=True) for _, payload in responses]
        self.assertEqual(len(set(payloads)), 1)
        counts = prefix_counts(key)
        self.assertEqual(counts, (1, 1, 2))
        print(json.dumps({
            "metric": "same_key_concurrency",
            "requests": request_count,
            "http201": statuses.count(201),
            "http200": statuses.count(200),
            "http409": statuses.count(409),
            "reservations": counts[0],
            "orders": counts[1],
            "seatStates": "HELD,HELD",
        }, ensure_ascii=False))

    def test_different_keys_true_concurrency_has_one_winner(self) -> None:
        request_count = 20
        barrier = threading.Barrier(request_count)

        def send(index):
            barrier.wait()
            return request_json(
                body={"sessionId": SESSION_ID, "seatIds": [TEST_SEATS[0]]},
                idempotency_key=f"it-phase3-hot-seat-{index:02d}",
            )

        with ThreadPoolExecutor(max_workers=request_count) as executor:
            responses = list(executor.map(send, range(request_count)))

        statuses = [status for status, _ in responses]
        self.assertEqual(statuses.count(201), 1, statuses)
        self.assertEqual(statuses.count(409), request_count - 1, responses)
        for status, payload in responses:
            if status == 409:
                self.assertEqual(payload["code"], "SEAT_CONFLICT")
        counts = prefix_counts("it-phase3-hot-seat-")
        self.assertEqual(counts, (1, 1, 1))
        seat_state = psql(
            f"SELECT status FROM session_seats WHERE id = '{TEST_SEATS[0]}';"
        )
        self.assertEqual(seat_state, "HELD")
        print(json.dumps({
            "metric": "different_key_hot_seat",
            "requests": request_count,
            "http201": statuses.count(201),
            "http200": statuses.count(200),
            "http409": statuses.count(409),
            "reservations": counts[0],
            "orders": counts[1],
            "seatStates": seat_state,
        }, ensure_ascii=False))

    def test_crossing_multi_seat_requests_are_atomic(self) -> None:
        barrier = threading.Barrier(2)
        requests = (
            ("it-phase3-cross-left", TEST_SEATS[:2]),
            ("it-phase3-cross-right", TEST_SEATS[1:]),
        )

        def send(item):
            key, seats = item
            barrier.wait()
            return key, seats, request_json(
                body={"sessionId": SESSION_ID, "seatIds": seats},
                idempotency_key=key,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(send, requests))

        statuses = [response[2][0] for response in responses]
        self.assertEqual(statuses.count(201), 1, responses)
        self.assertEqual(statuses.count(409), 1, responses)
        winner = next(item for item in responses if item[2][0] == 201)
        loser = next(item for item in responses if item[2][0] == 409)
        self.assertEqual(loser[2][1]["code"], "SEAT_CONFLICT")
        states = dict(
            line.split("\t")
            for line in psql(
                "SELECT id, status FROM session_seats "
                f"WHERE id IN ({', '.join(repr(seat) for seat in TEST_SEATS)}) "
                "ORDER BY id;"
            ).splitlines()
        )
        self.assertEqual([states[seat] for seat in winner[1]], ["HELD", "HELD"])
        loser_only = next(seat for seat in loser[1] if seat not in winner[1])
        self.assertEqual(states[loser_only], "AVAILABLE")
        counts = prefix_counts("it-phase3-cross-")
        self.assertEqual(counts, (1, 1, 2))
        print(json.dumps({
            "metric": "crossing_multi_seat",
            "requests": 2,
            "http201": statuses.count(201),
            "http200": statuses.count(200),
            "http409": statuses.count(409),
            "reservations": counts[0],
            "orders": counts[1],
            "seatStates": states,
        }, ensure_ascii=False, sort_keys=True))

    def test_request_validation_and_session_errors(self) -> None:
        cases = (
            ("missing-auth", None, "it-phase3-validation-user", {"sessionId": SESSION_ID, "seatIds": [TEST_SEATS[0]]}, 401),
            ("empty-auth", "", "it-phase3-validation-empty-user", {"sessionId": SESSION_ID, "seatIds": [TEST_SEATS[0]]}, 401),
            ("missing-key", USER_ID, None, {"sessionId": SESSION_ID, "seatIds": [TEST_SEATS[0]]}, 400),
            ("empty-key", USER_ID, "", {"sessionId": SESSION_ID, "seatIds": [TEST_SEATS[0]]}, 400),
            ("long-key", USER_ID, "x" * 129, {"sessionId": SESSION_ID, "seatIds": [TEST_SEATS[0]]}, 400),
            ("missing-session", USER_ID, "it-phase3-validation-session", {"seatIds": [TEST_SEATS[0]]}, 400),
            ("empty-session", USER_ID, "it-phase3-validation-empty-session", {"sessionId": "", "seatIds": [TEST_SEATS[0]]}, 400),
            ("non-string-session", USER_ID, "it-phase3-validation-session-type", {"sessionId": 1001, "seatIds": [TEST_SEATS[0]]}, 400),
            ("seats-not-array", USER_ID, "it-phase3-validation-seat-array", {"sessionId": SESSION_ID, "seatIds": TEST_SEATS[0]}, 400),
            ("empty-seats", USER_ID, "it-phase3-validation-empty", {"sessionId": SESSION_ID, "seatIds": []}, 400),
            ("empty-seat-id", USER_ID, "it-phase3-validation-empty-seat", {"sessionId": SESSION_ID, "seatIds": [""]}, 400),
            ("non-string-seat-id", USER_ID, "it-phase3-validation-seat-type", {"sessionId": SESSION_ID, "seatIds": [1]}, 400),
            ("seven-seats", USER_ID, "it-phase3-validation-seven", {"sessionId": SESSION_ID, "seatIds": [f"seat-{i}" for i in range(7)]}, 400),
            ("duplicate", USER_ID, "it-phase3-validation-duplicate", {"sessionId": SESSION_ID, "seatIds": [TEST_SEATS[0], TEST_SEATS[0]]}, 400),
            ("unknown-session", USER_ID, "it-phase3-validation-unknown-session", {"sessionId": "not-present", "seatIds": [TEST_SEATS[0]]}, 404),
            ("unknown-seat", USER_ID, "it-phase3-validation-unknown-seat", {"sessionId": SESSION_ID, "seatIds": [f"{SESSION_ID}-Z99"]}, 400),
            ("other-session-seat", USER_ID, "it-phase3-validation-other-session", {"sessionId": SESSION_ID, "seatIds": ["ses-concert-1002-A01"]}, 400),
        )
        for name, user_id, key, body, expected_status in cases:
            with self.subTest(name=name):
                status, payload = request_json(
                    body=body,
                    user_id=user_id,
                    idempotency_key=key,
                )
                self.assertEqual(status, expected_status, payload)
                expected_code = {
                    401: "UNAUTHENTICATED",
                    404: "SESSION_NOT_FOUND",
                }.get(expected_status, "INVALID_ARGUMENT")
                self.assertEqual(payload["code"], expected_code)

        status, payload = request_json(
            raw_body=b"{invalid-json",
            idempotency_key="it-phase3-validation-json",
        )
        self.assertEqual(status, 400, payload)
        self.assertEqual(payload["code"], "INVALID_ARGUMENT")

        psql(f"UPDATE sessions SET status = 'SOLD_OUT' WHERE id = '{SESSION_ID}';")
        try:
            status, payload = request_json(
                body={"sessionId": SESSION_ID, "seatIds": [TEST_SEATS[0]]},
                idempotency_key="it-phase3-validation-sold-out",
            )
            self.assertEqual(status, 409, payload)
            self.assertEqual(payload, {
                "code": "SESSION_NOT_AVAILABLE",
                "message": "Session is not available for reservation",
            })
        finally:
            psql(f"UPDATE sessions SET status = 'ON_SALE' WHERE id = '{SESSION_ID}';")

    def test_z_phase3_test_scope_is_restored(self) -> None:
        seat_list = ", ".join(f"'{seat}'" for seat in TEST_SEATS)
        seats = psql(
            f"""
            SELECT id, status, current_reservation_id IS NULL
            FROM session_seats
            WHERE id IN ({seat_list})
            ORDER BY id;
            """
        )
        self.assertEqual(
            [line.split("\t") for line in seats.splitlines()],
            [[seat, "AVAILABLE", "t"] for seat in sorted(TEST_SEATS)],
        )

        leftovers = psql(
            """
            SELECT
                (SELECT count(*) FROM reservations
                 WHERE idempotency_key LIKE 'it-phase3-%'),
                (SELECT count(*) FROM orders AS ticket_order
                 JOIN reservations AS reservation
                   ON reservation.id = ticket_order.reservation_id
                 WHERE reservation.idempotency_key LIKE 'it-phase3-%'),
                (SELECT count(*) FROM reservation_session_seats AS item
                 JOIN reservations AS reservation
                   ON reservation.id = item.reservation_id
                 WHERE reservation.idempotency_key LIKE 'it-phase3-%');
            """
        )
        self.assertEqual(leftovers.split("\t"), ["0", "0", "0"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
