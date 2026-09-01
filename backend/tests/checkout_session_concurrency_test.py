import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from checkout_session_test_support import (
    TEST_SEATS,
    TEST_USERS,
    cleanup_phase5_data,
    confirm_checkout,
    create_checkout,
    psql,
    request_json,
)


class CheckoutSessionConcurrencyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cleanup_phase5_data(recreate_users=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cleanup_phase5_data()

    def setUp(self) -> None:
        cleanup_phase5_data(recreate_users=True)

    def test_concurrent_confirm_reuses_one_server_key_and_result(self) -> None:
        _, checkout = create_checkout(TEST_USERS[0], TEST_SEATS[:2])
        request_count = 10
        barrier = threading.Barrier(request_count)

        def send(_):
            barrier.wait()
            return confirm_checkout(checkout["id"], TEST_USERS[0])

        with ThreadPoolExecutor(max_workers=request_count) as executor:
            responses = list(executor.map(send, range(request_count)))

        self.assertEqual([status for status, _ in responses], [200] * request_count)
        reservation_ids = {value["reservation"]["id"] for _, value in responses}
        order_ids = {value["order"]["id"] for _, value in responses}
        self.assertEqual(len(reservation_ids), 1)
        self.assertEqual(len(order_ids), 1)
        counts = psql(
            f"""
            SELECT COUNT(DISTINCT reservation.id),
                   COUNT(DISTINCT ticket_order.id),
                   COUNT(item.session_seat_id),
                   COUNT(DISTINCT checkout.active_confirm_idempotency_key)
            FROM checkout_sessions AS checkout
            JOIN reservations AS reservation
              ON reservation.user_id = checkout.user_id
             AND reservation.idempotency_key = checkout.active_confirm_idempotency_key
            JOIN orders AS ticket_order ON ticket_order.reservation_id = reservation.id
            JOIN reservation_session_seats AS item ON item.reservation_id = reservation.id
            WHERE checkout.id = '{checkout['id']}';
            """
        )
        self.assertEqual(counts.split("\t"), ["1", "1", "2", "1"])
        print(json.dumps({
            "metric": "checkout_same_session_confirm",
            "requests": request_count,
            "http200": request_count,
            "reservations": 1,
            "orders": 1,
            "serverKeys": 1,
        }))

    def test_replace_and_confirm_serialize_on_checkout_row(self) -> None:
        _, checkout = create_checkout(TEST_USERS[0], [TEST_SEATS[0]])
        barrier = threading.Barrier(2)

        def replace():
            barrier.wait()
            return request_json(
                f"/checkout-sessions/{checkout['id']}/seats",
                method="PUT",
                user_id=TEST_USERS[0],
                body={"seatIds": [TEST_SEATS[1], TEST_SEATS[2]]},
            )

        def confirm():
            barrier.wait()
            return confirm_checkout(checkout["id"], TEST_USERS[0])

        with ThreadPoolExecutor(max_workers=2) as executor:
            replace_future = executor.submit(replace)
            confirm_future = executor.submit(confirm)
            replace_result = replace_future.result()
            confirm_result = confirm_future.result()

        self.assertEqual(confirm_result[0], 200, confirm_result)
        self.assertIn(replace_result[0], (200, 409), replace_result)
        final_seats = confirm_result[1]["seatIds"]
        if replace_result[0] == 200:
            self.assertEqual(final_seats, TEST_SEATS[1:3])
        else:
            self.assertEqual(replace_result[1]["code"], "CHECKOUT_SESSION_NOT_MODIFIABLE")
            self.assertEqual(final_seats, [TEST_SEATS[0]])
        association = psql(
            f"""
            SELECT string_agg(item.session_seat_id, ',' ORDER BY item.session_seat_id)
            FROM checkout_sessions AS checkout
            JOIN reservation_session_seats AS item
              ON item.reservation_id = checkout.reservation_id
            WHERE checkout.id = '{checkout['id']}';
            """
        )
        self.assertEqual(association.split(","), final_seats)

    def test_independent_checkout_sessions_confirm_concurrently(self) -> None:
        _, first = create_checkout(TEST_USERS[0], [TEST_SEATS[0]])
        _, second = create_checkout(TEST_USERS[0], [TEST_SEATS[1]])
        barrier = threading.Barrier(2)

        def send(checkout_id):
            barrier.wait()
            return confirm_checkout(checkout_id, TEST_USERS[0])

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(send, (first["id"], second["id"])))
        self.assertEqual([status for status, _ in responses], [200, 200])
        self.assertEqual(
            len({value["reservation"]["id"] for _, value in responses}), 2
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
