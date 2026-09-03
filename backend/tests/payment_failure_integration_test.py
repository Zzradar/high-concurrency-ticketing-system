import unittest

from payment_integration_test import (
    SEATS, cleanup, create_order, psql, request_json, wait_attempt,
)


class PaymentFailureIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        cleanup(create_users=True)

    def tearDown(self) -> None:
        cleanup()

    def test_failed_attempt_keeps_formal_hold_and_allows_retry(self) -> None:
        order, _ = create_order("failure", SEATS[0])
        _, started = request_json(f"/orders/{order['id']}/pay", method="POST")
        first = wait_attempt(started["paymentAttempt"]["id"], statuses=("FAILED",))
        self.assertEqual(first["failureReason"], "SIMULATED_PAYMENT_FAILURE")
        state = psql(
            f"""
            SELECT o.status,r.status,s.status FROM orders o
            JOIN reservations r ON r.id=o.reservation_id
            JOIN reservation_session_seats x ON x.reservation_id=r.id
            JOIN session_seats s ON s.id=x.session_seat_id WHERE o.id='{order['id']}';
            """
        )
        self.assertEqual(state.split("\t"), ["PENDING_PAYMENT", "ACTIVE", "HELD"])
        retry_status, retry = request_json(f"/orders/{order['id']}/pay", method="POST")
        self.assertEqual(retry_status, 202)
        self.assertNotEqual(retry["paymentAttempt"]["id"], first["id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
