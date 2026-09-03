from concurrent.futures import ThreadPoolExecutor
import time
import unittest

from auth_test_support import AuthenticatedClient, test_user_values, username_for_user
from checkout_session_test_support import cleanup_seat_holds, psql


USER_ID = "U-PHASE9-MULTI"
SESSION_ID = "ses-concert-1001"
SEATS = [f"{SESSION_ID}-{label}" for label in ("A01", "A02")]


def cleanup(*, recreate_user: bool = False) -> None:
    cleanup_seat_holds()
    seat_ids = ", ".join(repr(seat_id) for seat_id in SEATS)
    psql(
        f"""
        BEGIN;
        DROP TRIGGER IF EXISTS phase9_delay_reservation ON reservations;
        DROP FUNCTION IF EXISTS phase9_delay_reservation();
        DELETE FROM checkout_sessions WHERE user_id = '{USER_ID}';
        UPDATE session_seats
        SET status = 'AVAILABLE', current_reservation_id = NULL
        WHERE id IN ({seat_ids}) OR current_reservation_id IN (
            SELECT id FROM reservations WHERE user_id = '{USER_ID}'
        );
        DELETE FROM user_notifications WHERE user_id = '{USER_ID}';
        DELETE FROM refunds WHERE order_id IN (
            SELECT id FROM orders WHERE user_id = '{USER_ID}'
        );
        DELETE FROM payment_attempts WHERE order_id IN (
            SELECT id FROM orders WHERE user_id = '{USER_ID}'
        );
        DELETE FROM orders WHERE user_id = '{USER_ID}';
        DELETE FROM reservation_session_seats WHERE reservation_id IN (
            SELECT id FROM reservations WHERE user_id = '{USER_ID}'
        );
        DELETE FROM reservations WHERE user_id = '{USER_ID}';
        DELETE FROM user_sessions WHERE user_id = '{USER_ID}';
        DELETE FROM app_users WHERE id = '{USER_ID}';
        COMMIT;
        """
    )
    if recreate_user:
        psql(
            "INSERT INTO app_users "
            "(id, display_name, username, password_hash, status) VALUES "
            + test_user_values((USER_ID,))
            + ";"
        )


def clients() -> tuple[AuthenticatedClient, AuthenticatedClient]:
    username = username_for_user(USER_ID)
    first = AuthenticatedClient(username)
    second = AuthenticatedClient(username)
    first.login()
    second.login()
    return first, second


def create_checkout(client: AuthenticatedClient, seat_id: str) -> dict:
    status, value, _ = client.request(
        "/checkout-sessions",
        method="POST",
        body={"sessionId": SESSION_ID, "seatIds": [seat_id]},
    )
    if status != 201:
        raise AssertionError((status, value))
    return value


def create_order(client: AuthenticatedClient, seat_id: str, key: str) -> dict:
    status, value, _ = client.request(
        "/reservations",
        method="POST",
        body={"sessionId": SESSION_ID, "seatIds": [seat_id]},
        headers={"Idempotency-Key": key},
    )
    if status != 201:
        raise AssertionError((status, value))
    return value["order"]


class Phase9MultiClientIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        cleanup(recreate_user=True)

    def tearDown(self) -> None:
        cleanup()

    def test_confirm_and_pay_dispositions_across_two_cookie_jars(self) -> None:
        first, second = clients()
        checkout = create_checkout(first, SEATS[0])
        psql(
            f"""
            CREATE FUNCTION phase9_delay_reservation() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                IF NEW.user_id = '{USER_ID}' THEN
                    PERFORM pg_sleep(1.5);
                END IF;
                RETURN NEW;
            END;
            $$;
            CREATE TRIGGER phase9_delay_reservation
            BEFORE INSERT ON reservations
            FOR EACH ROW EXECUTE FUNCTION phase9_delay_reservation();
            """
        )

        def confirm(client: AuthenticatedClient):
            return client.request(
                f"/checkout-sessions/{checkout['id']}/confirm", method="POST"
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(confirm, first)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if psql(
                    f"SELECT status FROM checkout_sessions WHERE id='{checkout['id']}';"
                ) == "SUBMITTING":
                    break
                time.sleep(0.05)
            else:
                self.fail("checkout never reached SUBMITTING")
            second_response = confirm(second)
            first_response = first_future.result(timeout=30)

        first_status, first_value, _ = first_response
        second_status, second_value, _ = second_response
        self.assertEqual((first_status, second_status), (200, 200))
        self.assertEqual(first_value["disposition"], "CONFIRMED_NOW")
        self.assertEqual(second_value["disposition"], "REUSED_CONFIRMATION")
        first_order = first_value["checkoutSession"]["order"]
        second_order = second_value["checkoutSession"]["order"]
        self.assertEqual(first_order["id"], second_order["id"])

        status, replay, _ = second.request(
            f"/checkout-sessions/{checkout['id']}/confirm", method="POST"
        )
        self.assertEqual((status, replay["disposition"]), (200, "ALREADY_CONFIRMED"))
        self.assertEqual(replay["checkoutSession"]["order"]["id"], first_order["id"])

        started_status, started, _ = first.request(
            f"/orders/{first_order['id']}/pay", method="POST"
        )
        reused_status, reused, _ = second.request(
            f"/orders/{first_order['id']}/pay", method="POST"
        )
        self.assertEqual((started_status, reused_status), (202, 202))
        self.assertEqual(started["disposition"], "STARTED_NEW")
        self.assertEqual(reused["disposition"], "REUSED_PROCESSING")
        attempt_id = started["paymentAttempt"]["id"]
        self.assertEqual(reused["paymentAttempt"]["id"], attempt_id)

        psql(
            f"""
            BEGIN;
            UPDATE payment_attempts
            SET status='SUCCEEDED', completed_at=clock_timestamp(),
                accepted_at=clock_timestamp(), failure_reason=NULL
            WHERE id='{attempt_id}' AND status='PROCESSING';
            UPDATE reservations SET status='CONFIRMED'
            WHERE id='{first_order['reservationId']}';
            UPDATE session_seats SET status='SOLD', current_reservation_id=NULL
            WHERE current_reservation_id='{first_order['reservationId']}';
            UPDATE orders SET status='PAID', paid_at=clock_timestamp()
            WHERE id='{first_order['id']}';
            COMMIT;
            """
        )
        paid_status, paid, _ = second.request(
            f"/orders/{first_order['id']}/pay", method="POST"
        )
        self.assertEqual((paid_status, paid["disposition"]), (200, "ALREADY_PAID"))
        self.assertEqual(paid["paymentAttempt"]["id"], attempt_id)

    def test_cancel_and_order_recovery_across_two_cookie_jars(self) -> None:
        first, second = clients()
        order = create_order(first, SEATS[1], "phase9-multi-cancel")

        first_status, first_value, _ = first.request(
            f"/orders/{order['id']}/cancel", method="POST"
        )
        second_status, second_value, _ = second.request(
            f"/orders/{order['id']}/cancel", method="POST"
        )
        self.assertEqual((first_status, second_status), (200, 200))
        self.assertEqual(first_value["disposition"], "CANCELLED_NOW")
        self.assertEqual(second_value["disposition"], "ALREADY_CANCELLED")
        self.assertEqual(first_value["order"]["id"], second_value["order"]["id"])

        list_status, orders, _ = second.request(
            f"/orders?status=CANCELLED&sessionId={SESSION_ID}&limit=10"
        )
        self.assertEqual(list_status, 200)
        self.assertEqual([value["id"] for value in orders], [order["id"]])
        invalid_status, invalid, _ = second.request("/orders?limit=0")
        self.assertEqual((invalid_status, invalid["code"]), (400, "INVALID_ARGUMENT"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
