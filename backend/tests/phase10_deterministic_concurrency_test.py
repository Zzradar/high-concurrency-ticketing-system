from concurrent.futures import ThreadPoolExecutor
import json
import time
import unittest

from phase10_locking_test_support import (
    PerformanceClient,
    PersistentTransaction,
    cleanup_users,
    force_success_backend,
    load_credentials,
    psql,
    wait_for_blocked_by,
)


SESSION_ID = "perf-session-001-001"
SEATS = [f"perf-ss-001-001-{index:06d}" for index in range(1, 4)]


class DeterministicConcurrencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        force_success_backend()
        cls.credentials = load_credentials(3)
        cls.clients = [PerformanceClient(value) for value in cls.credentials]
        cls.user_ids = [value["userId"] for value in cls.credentials]

    def setUp(self) -> None:
        cleanup_users(self.user_ids, [SESSION_ID], SEATS)

    def tearDown(self) -> None:
        cleanup_users(self.user_ids, [SESSION_ID], SEATS)

    def create_reservation(self, client_index: int, seat_id: str, key: str):
        return self.clients[client_index].request(
            "/reservations",
            method="POST",
            body={"sessionId": SESSION_ID, "seatIds": [seat_id]},
            headers={"Idempotency-Key": key},
        )

    def test_formal_seat_lock_wait_then_one_winner(self) -> None:
        with PersistentTransaction() as locker, ThreadPoolExecutor(max_workers=1) as pool:
            locker.lock_row("session_seats", SEATS[0])
            future = pool.submit(
                self.create_reservation, 0, SEATS[0], "phase10-lock-seat-winner"
            )
            evidence = wait_for_blocked_by(locker.pid, future=future)
            self.assertEqual(evidence["waitEventType"], "Lock")
            self.assertIn(locker.pid, evidence["blockingPids"])
            locker.rollback()
            status, winner = future.result(timeout=20)

        self.assertEqual(status, 201, winner)
        loser_status, loser = self.create_reservation(
            1, SEATS[0], "phase10-lock-seat-loser"
        )
        self.assertEqual(loser_status, 409, loser)
        self.assertEqual(loser["code"], "SEAT_CONFLICT")
        state = psql(
            f"""
            SELECT count(DISTINCT reservation.id),
                   count(DISTINCT ticket_order.id),
                   seat.status,
                   seat.current_reservation_id IS NOT NULL
            FROM session_seats AS seat
            LEFT JOIN reservation_session_seats AS item ON item.session_seat_id = seat.id
            LEFT JOIN reservations AS reservation
              ON reservation.id = item.reservation_id AND reservation.status = 'ACTIVE'
            LEFT JOIN orders AS ticket_order
              ON ticket_order.reservation_id = reservation.id
            WHERE seat.id = '{SEATS[0]}'
            GROUP BY seat.status, seat.current_reservation_id;
            """
        )
        self.assertEqual(state.split("\t"), ["1", "1", "HELD", "t"])

    def test_checkout_confirm_lock_wait_reuses_one_result(self) -> None:
        status, checkout = self.clients[0].request(
            "/checkout-sessions",
            method="POST",
            body={"sessionId": SESSION_ID, "seatIds": [SEATS[1]]},
        )
        self.assertEqual(status, 201, checkout)
        path = f"/checkout-sessions/{checkout['id']}/confirm"
        with PersistentTransaction() as locker, ThreadPoolExecutor(max_workers=2) as pool:
            locker.lock_row("checkout_sessions", checkout["id"])
            first = pool.submit(self.clients[0].request, path, method="POST")
            first_evidence = wait_for_blocked_by(locker.pid, future=first)
            second = pool.submit(self.clients[0].request, path, method="POST")
            self.assertEqual(first_evidence["waitEventType"], "Lock")
            locker.rollback()
            responses = [first.result(timeout=30), second.result(timeout=30)]

        self.assertEqual([value[0] for value in responses], [200, 200], responses)
        results = [value[1]["checkoutSession"] for value in responses]
        order_ids = {value["order"]["id"] for value in results}
        reservation_ids = {value["reservationId"] for value in results}
        self.assertEqual(len(order_ids), 1)
        self.assertEqual(len(reservation_ids), 1)
        db_state = psql(
            f"""
            SELECT checkout.status,
                   checkout.active_confirm_idempotency_key IS NOT NULL,
                   count(DISTINCT reservation.id),
                   count(DISTINCT ticket_order.id)
            FROM checkout_sessions AS checkout
            LEFT JOIN reservations AS reservation
              ON reservation.id = checkout.reservation_id
            LEFT JOIN orders AS ticket_order
              ON ticket_order.reservation_id = reservation.id
            WHERE checkout.id = '{checkout['id']}'
            GROUP BY checkout.status, checkout.active_confirm_idempotency_key;
            """
        )
        self.assertEqual(db_state.split("\t"), ["RESERVED", "t", "1", "1"])

    def test_payment_callback_then_cancel_has_order_first_chain(self) -> None:
        reservation_status, created = self.create_reservation(
            2, SEATS[2], "phase10-lock-pay-cancel"
        )
        self.assertEqual(reservation_status, 201, created)
        order = created["order"]
        reservation = created["reservation"]
        pay_status, started = self.clients[2].request(
            f"/orders/{order['id']}/pay", method="POST"
        )
        self.assertEqual(pay_status, 202, started)
        attempt_id = started["paymentAttempt"]["id"]

        with PersistentTransaction() as locker, ThreadPoolExecutor(max_workers=1) as pool:
            locker.lock_row("reservations", reservation["id"])
            callback_evidence = wait_for_blocked_by(locker.pid, timeout=12)
            callback_pid = callback_evidence["blockedPid"]
            cancel = pool.submit(
                self.clients[2].request,
                f"/orders/{order['id']}/cancel",
                method="POST",
                timeout=30,
            )
            cancel_evidence = wait_for_blocked_by(
                callback_pid,
                timeout=10,
                future=cancel,
                exclude_pids={callback_pid},
            )
            chain = {
                "externalReservationLocker": locker.pid,
                "paymentCallback": callback_pid,
                "cancel": cancel_evidence["blockedPid"],
            }
            print("BLOCKING_CHAIN " + json.dumps(chain, sort_keys=True))
            locker.rollback()
            cancel_status, cancel_body = cancel.result(timeout=20)

        self.assertEqual(cancel_status, 409, cancel_body)
        self.assertEqual(cancel_body["code"], "ORDER_NOT_CANCELLABLE")
        deadline = time.monotonic() + 10
        state = ""
        while time.monotonic() < deadline:
            state = psql(
                f"""
                SELECT ticket_order.status, reservation.status, seat.status,
                       attempt.status, attempt.accepted_at IS NOT NULL
                FROM orders AS ticket_order
                JOIN reservations AS reservation ON reservation.id = ticket_order.reservation_id
                JOIN reservation_session_seats AS item ON item.reservation_id = reservation.id
                JOIN session_seats AS seat ON seat.id = item.session_seat_id
                JOIN payment_attempts AS attempt ON attempt.order_id = ticket_order.id
                WHERE ticket_order.id = '{order['id']}' AND attempt.id = '{attempt_id}';
                """
            )
            if state.startswith("PAID\t"):
                break
            time.sleep(0.1)
        self.assertEqual(state.split("\t"), ["PAID", "CONFIRMED", "SOLD", "SUCCEEDED", "t"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
