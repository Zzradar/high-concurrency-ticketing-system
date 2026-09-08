import time
import unittest

from order_expiry_integration_test import (
    PREFIX, TEST_SEATS, cleanup_test_data, create_order, make_expired, psql,
    wait_for_order_status,
)


class OrderLifecycleIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        cleanup_test_data()

    def tearDown(self) -> None:
        cleanup_test_data()

    def test_valid_processing_attempt_defers_expiry(self) -> None:
        order_id, reservation_id = create_order(PREFIX + "grace", [TEST_SEATS[0]])
        make_expired(order_id, reservation_id)
        psql(
            f"""
            INSERT INTO payment_attempts (
                id, order_id, status, started_at, processing_deadline,
                scheduled_complete_at
            ) VALUES (
                'PAY-IT-GRACE', '{order_id}', 'PROCESSING',
                clock_timestamp() - INTERVAL '2 minutes',
                clock_timestamp() + INTERVAL '1 minute',
                clock_timestamp() + INTERVAL '30 seconds'
            );
            """
        )
        time.sleep(6)
        self.assertEqual(psql(f"SELECT status FROM orders WHERE id = '{order_id}';"), "PENDING_PAYMENT")
        self.assertEqual(psql("SELECT status FROM payment_attempts WHERE id = 'PAY-IT-GRACE';"), "PROCESSING")

    def test_expired_processing_deadline_times_out_then_expires(self) -> None:
        order_id, reservation_id = create_order(PREFIX + "deadline", [TEST_SEATS[1]])
        psql(
            f"""
            BEGIN;
            UPDATE reservations
            SET created_at = CURRENT_TIMESTAMP - INTERVAL '20 minutes',
                expires_at = CURRENT_TIMESTAMP - INTERVAL '1 minute'
            WHERE id = '{reservation_id}';
            UPDATE orders
            SET created_at = CURRENT_TIMESTAMP - INTERVAL '20 minutes',
                expires_at = CURRENT_TIMESTAMP - INTERVAL '1 minute'
            WHERE id = '{order_id}';
            INSERT INTO payment_attempts (
                id, order_id, status, started_at, processing_deadline,
                scheduled_complete_at
            ) VALUES (
                'PAY-IT-DEADLINE', '{order_id}', 'PROCESSING',
                clock_timestamp() - INTERVAL '3 minutes',
                clock_timestamp() - INTERVAL '30 seconds',
                clock_timestamp() - INTERVAL '1 minute'
            );
            COMMIT;
            """
        )
        wait_for_order_status(order_id, "EXPIRED")
        self.assertEqual(psql("SELECT status FROM payment_attempts WHERE id = 'PAY-IT-DEADLINE';"), "TIMED_OUT")
        state = psql(
            f"""
            SELECT ticket_order.status,
                   reservation.status,
                   inventory.status,
                   inventory.current_reservation_id IS NULL,
                   COUNT(notification.id)
            FROM orders AS ticket_order
            JOIN reservations AS reservation
              ON reservation.id = ticket_order.reservation_id
            JOIN reservation_session_seats AS item
              ON item.reservation_id = reservation.id
            JOIN session_seats AS inventory
              ON inventory.id = item.session_seat_id
            LEFT JOIN user_notifications AS notification
              ON notification.order_id = ticket_order.id
             AND notification.type = 'ORDER_EXPIRED'
            WHERE ticket_order.id = '{order_id}'
            GROUP BY ticket_order.status,
                     reservation.status,
                     inventory.status,
                     inventory.current_reservation_id;
            """
        )
        self.assertEqual(
            state.split("\t"), ["EXPIRED", "EXPIRED", "AVAILABLE", "t", "1"]
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
