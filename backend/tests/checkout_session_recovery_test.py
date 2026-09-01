import subprocess
import time
import unittest

from checkout_session_test_support import (
    BACKEND_ROOT,
    SESSION_ID,
    TEST_SEATS,
    TEST_USERS,
    cleanup_phase5_data,
    create_formal_reservation,
    create_checkout,
    psql,
    request_json,
)


def restart_backend() -> None:
    completed = subprocess.run(
        ["docker", "compose", "restart", "backend"],
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr)
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            status, body = request_json("/health", user_id=None, timeout=2)
            if status == 200 and body == {"database": "up", "status": "ok"}:
                return
        except AssertionError:
            pass
        time.sleep(0.5)
    raise AssertionError("backend did not become healthy after restart")


class CheckoutSessionRecoveryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cleanup_phase5_data(recreate_users=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cleanup_phase5_data()

    def setUp(self) -> None:
        cleanup_phase5_data(recreate_users=True)

    def test_get_repairs_known_result_and_preserves_unknown_result(self) -> None:
        _, known = create_checkout(TEST_USERS[0], [TEST_SEATS[0]])
        _, unknown = create_checkout(TEST_USERS[1], [TEST_SEATS[1]])
        known_key = "it-phase5-recovery-known"
        unknown_key = "it-phase5-recovery-unknown"
        psql(
            f"""
            UPDATE checkout_sessions
            SET status = 'SUBMITTING', active_confirm_idempotency_key = '{known_key}'
            WHERE id = '{known['id']}';
            UPDATE checkout_sessions
            SET status = 'SUBMITTING', active_confirm_idempotency_key = '{unknown_key}'
            WHERE id = '{unknown['id']}';
            """
        )
        reservation_status, formal = create_formal_reservation(
            TEST_USERS[0], known_key, [TEST_SEATS[0]]
        )
        self.assertEqual(reservation_status, 201, formal)

        known_status, known_value = request_json(
            f"/checkout-sessions/{known['id']}", user_id=TEST_USERS[0]
        )
        unknown_status, unknown_value = request_json(
            f"/checkout-sessions/{unknown['id']}", user_id=TEST_USERS[1]
        )
        self.assertEqual(known_status, 200)
        self.assertEqual(known_value["status"], "RESERVED")
        self.assertEqual(known_value["reservation"]["id"], formal["reservation"]["id"])
        self.assertEqual(unknown_status, 200)
        self.assertEqual(unknown_value["status"], "SUBMITTING")
        self.assertNotIn("reservationId", unknown_value)

    def test_startup_reconciliation_is_bounded_and_does_not_buy_unknown(self) -> None:
        _, known = create_checkout(TEST_USERS[0], [TEST_SEATS[0]])
        _, unknown = create_checkout(TEST_USERS[1], [TEST_SEATS[1]])
        known_key = "it-phase5-startup-known"
        unknown_key = "it-phase5-startup-unknown"
        psql(
            f"""
            UPDATE checkout_sessions
            SET status = 'SUBMITTING', active_confirm_idempotency_key = '{known_key}'
            WHERE id = '{known['id']}';
            UPDATE checkout_sessions
            SET status = 'SUBMITTING', active_confirm_idempotency_key = '{unknown_key}'
            WHERE id = '{unknown['id']}';
            """
        )
        reservation_status, formal = create_formal_reservation(
            TEST_USERS[0], known_key, [TEST_SEATS[0]]
        )
        self.assertEqual(reservation_status, 201, formal)

        restart_backend()
        state = psql(
            f"""
            SELECT id, status, reservation_id IS NOT NULL
            FROM checkout_sessions
            WHERE id IN ('{known['id']}', '{unknown['id']}')
            ORDER BY id;
            """
        )
        rows = {row.split("\t")[0]: row.split("\t")[1:] for row in state.splitlines()}
        self.assertEqual(rows[known["id"]], ["RESERVED", "t"])
        self.assertEqual(rows[unknown["id"]], ["SUBMITTING", "f"])
        unknown_formal = psql(
            f"SELECT COUNT(*) FROM reservations WHERE user_id = '{TEST_USERS[1]}' "
            f"AND idempotency_key = '{unknown_key}';"
        )
        self.assertEqual(unknown_formal, "0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
