"""Deterministic DB-stage crashes; no production fault flags or weakened CHECKs.

Run only against the isolated Phase11 compose project with Fake Stripe.
Advisory-lock triggers stop a transaction at a known stage after HTTP returns.
"""
import subprocess
import time
import unittest

from phase11_stripe_integration_test import (
    BACKEND_ROOT, fake, payment_for_attempt, signed_webhook, wait_until,
)
from payment_integration_test import cleanup, create_order, psql, request_json, SEATS


def compose(*args):
    return subprocess.run(["docker", "compose", *args], cwd=BACKEND_ROOT,
                          check=True, capture_output=True, text=True).stdout


class CrashWindowIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.locker = None
        fake("/__admin__/reset", {})
        psql("DELETE FROM payment_provider_events;")
        cleanup(create_users=True)

    def tearDown(self):
        # Even a failed assertion must not leave a blocked backend/test trigger.
        self.remove_fault()
        compose("start", "backend")
        cleanup()
        psql("DELETE FROM payment_provider_events;")

    def start(self, key="crash"):
        order, _ = create_order(key, SEATS[0])
        status, body = request_json(f"/orders/{order['id']}/pay", method="POST")
        self.assertEqual(status, 202)
        attempt = body["paymentAttempt"]["id"]
        return order, attempt, payment_for_attempt(attempt)

    def retrieved(self, kind, object_id):
        return sum(r["kind"] == kind and r["id"] == object_id
                   for r in fake("/__admin__/state")["retrievals"])

    def wake(self, table, object_id):
        psql(f"UPDATE {table} SET next_reconcile_at=clock_timestamp() WHERE id='{object_id}';")

    def install_fault(self, table, condition, *, once=False):
        psql("CREATE SEQUENCE phase11_fault_hits;")
        action = "IF nextval('phase11_fault_hits') = 1 THEN RAISE EXCEPTION 'phase11 injected rollback'; END IF;" if once else "PERFORM pg_advisory_xact_lock(771109);"
        psql(f"""CREATE FUNCTION phase11_fault() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF {condition} THEN {action} END IF; RETURN NEW; END; $$;
            CREATE TRIGGER phase11_fault BEFORE INSERT OR UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION phase11_fault();""")
        if not once:
            self.locker = subprocess.Popen(
                ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "ticketing",
                 "-d", "ticketing", "-c", "SELECT pg_advisory_lock(771109); SELECT pg_sleep(120);"],
                cwd=BACKEND_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            wait_until(lambda: psql("SELECT COUNT(*) FROM pg_locks WHERE locktype='advisory' AND objid=771109 AND granted;") == "1")

    def wait_at_fault(self):
        wait_until(lambda: psql("SELECT COUNT(*) FROM pg_locks WHERE locktype='advisory' AND objid=771109 AND NOT granted;") != "0",
                   message="terminal local transaction reached DB crash gate")

    def remove_fault(self):
        psql("SELECT pg_terminate_backend(pid) FROM pg_locks WHERE locktype='advisory' AND objid=771109 AND granted AND pid<>pg_backend_pid();")
        if self.locker:
            self.locker.wait(timeout=10)
            self.locker = None
        psql("""DROP TRIGGER IF EXISTS phase11_fault ON payment_attempts;
            DROP TRIGGER IF EXISTS phase11_fault ON refunds;
            DROP TRIGGER IF EXISTS phase11_fault ON user_notifications;
            DROP FUNCTION IF EXISTS phase11_fault(); DROP SEQUENCE IF EXISTS phase11_fault_hits;""")

    def crash_and_restart(self, table, object_id):
        self.wait_at_fault()
        compose("kill", "-s", "SIGKILL", "backend")
        # PostgreSQL may finish an autocommit statement after its TCP client
        # dies. Terminate the precisely identified gated DB session *before*
        # releasing the gate, so this test exercises the pre-commit outcome.
        psql("SELECT pg_terminate_backend(pid) FROM pg_locks WHERE locktype='advisory' AND objid=771109 AND NOT granted;")
        wait_until(lambda: psql("SELECT COUNT(*) FROM pg_locks WHERE locktype='advisory' AND objid=771109 AND NOT granted;") == '0')
        self.remove_fault()
        self.assertEqual(psql(f"SELECT reconciliation_lease_until > clock_timestamp() FROM {table} WHERE id='{object_id}';"), "t")
        compose("start", "backend")
        # Preserve the dead owner's token, but advance only its deadline. This
        # is deterministic clock control, not removing ownership by hand.
        psql(f"UPDATE {table} SET reconciliation_lease_until=clock_timestamp()-INTERVAL '1 second', next_reconcile_at=clock_timestamp() WHERE id='{object_id}';")

    def assert_paid(self, order, attempt):
        wait_until(lambda: psql(f"SELECT status FROM orders WHERE id='{order['id']}';") == "PAID", timeout=45)
        self.assertEqual(psql(f"""SELECT a.status,a.accepted_at IS NOT NULL,
            a.provider_status,a.provider_terminal_at IS NOT NULL,
            a.next_reconcile_at IS NULL,a.reconciliation_lease_token IS NULL,
            o.status,r.status,s.status,
            (SELECT COUNT(*) FROM user_notifications WHERE order_id=o.id AND type='PAYMENT_SUCCEEDED')
            FROM payment_attempts a JOIN orders o ON o.id=a.order_id
            JOIN reservations r ON r.id=o.reservation_id
            JOIN session_seats s ON s.id='{SEATS[0]}' WHERE a.id='{attempt}';""").split('\t'),
            ['SUCCEEDED','t','succeeded','t','t','t','PAID','CONFIRMED','SOLD','1'])

    def test_a_terminal_retrieved_crash_before_local_commit(self):
        order, attempt, payment = self.start("case-a")
        self.install_fault("payment_attempts", f"NEW.id='{attempt}' AND NEW.status='SUCCEEDED'")
        before = self.retrieved("payment", payment['id'])
        fake("/__admin__/configure", {"paymentId": payment['id'], "paymentStatus": "succeeded"})
        self.wake("payment_attempts", attempt)
        self.wait_at_fault()
        self.assertGreater(self.retrieved("payment", payment['id']), before)
        self.assertEqual(psql(f"SELECT status,provider_terminal_at IS NULL,next_reconcile_at IS NOT NULL FROM payment_attempts WHERE id='{attempt}';"), 'PROCESSING\tt\tt')
        self.crash_and_restart("payment_attempts", attempt)
        self.assert_paid(order, attempt)
        self.assertGreaterEqual(self.retrieved("payment", payment['id']), before + 2)

    def test_b_final_transaction_rolls_back_once_and_inbox_handoff_survives(self):
        order, attempt, payment = self.start("case-b")
        self.install_fault("user_notifications", f"NEW.order_id='{order['id']}' AND NEW.type='PAYMENT_SUCCEEDED'", once=True)
        fake("/__admin__/configure", {"paymentId": payment['id'], "paymentStatus": "succeeded"})
        self.assertEqual(signed_webhook("evt-crash-handoff", "payment_intent.succeeded", payment_for_attempt(attempt))[0], 200)
        wait_until(lambda: psql("SELECT is_called FROM phase11_fault_hits;") == 't')
        self.assertEqual(psql(f"SELECT status,provider_terminal_at IS NULL,next_reconcile_at IS NOT NULL FROM payment_attempts WHERE id='{attempt}';"), 'PROCESSING\tt\tt')
        self.assertEqual(psql("SELECT status FROM payment_provider_events WHERE provider_event_id='evt-crash-handoff';"), 'PROCESSED')
        self.assert_paid(order, attempt)
        self.assertGreaterEqual(self.retrieved("payment", payment['id']), 2)

    def legacy_state(self, attempt, schedule):
        # Exact old recordProviderPayment output; existing CHECK remains valid.
        psql(f"UPDATE payment_attempts SET provider_status='succeeded', provider_last_sync_at=clock_timestamp(), provider_terminal_at=NULL, next_reconcile_at={schedule}, reconciliation_lease_until=NULL, reconciliation_lease_token=NULL WHERE id='{attempt}';")

    def test_c_exact_legacy_p1_null_schedule(self):
        order, attempt, payment = self.start("case-c")
        compose("stop", "backend")
        fake("/__admin__/configure", {"paymentId": payment['id'], "paymentStatus": "succeeded"})
        self.legacy_state(attempt, 'NULL')
        before = self.retrieved("payment", payment['id'])
        compose("start", "backend")
        self.assert_paid(order, attempt)
        self.assertGreater(self.retrieved("payment", payment['id']), before)

    def test_c_future_schedule_does_not_hide_terminal_evidence(self):
        order, attempt, payment = self.start("case-c-future")
        compose("stop", "backend")
        fake("/__admin__/configure", {"paymentId": payment['id'], "paymentStatus": "succeeded"})
        self.legacy_state(attempt, "clock_timestamp()+INTERVAL '1 day'")
        compose("start", "backend")
        self.assert_paid(order, attempt)

    def test_d_timed_out_expired_late_success(self):
        fake("/__admin__/configure", {"refundMode": "processing"})
        order, attempt, payment = self.start("case-d")
        psql(f"""BEGIN;
            UPDATE orders SET created_at=clock_timestamp()-INTERVAL '20 minutes', expires_at=clock_timestamp()-INTERVAL '1 second' WHERE id='{order['id']}';
            UPDATE reservations SET created_at=clock_timestamp()-INTERVAL '20 minutes', expires_at=clock_timestamp()-INTERVAL '1 second' WHERE id='{order['reservationId']}';
            UPDATE payment_attempts SET started_at=clock_timestamp()-INTERVAL '601 seconds', processing_deadline=clock_timestamp()-INTERVAL '1 second' WHERE id='{attempt}'; COMMIT;""")
        wait_until(lambda: psql(f"SELECT status FROM orders WHERE id='{order['id']}';") == 'EXPIRED')
        self.assertEqual(psql(f"SELECT status FROM payment_attempts WHERE id='{attempt}';"), 'TIMED_OUT')
        fake("/__admin__/configure", {"paymentId": payment['id'], "paymentStatus": "succeeded"})
        self.wake("payment_attempts", attempt)
        self.assert_refund_obligation(order, attempt, 'EXPIRED')

    def assert_refund_obligation(self, order, attempt, order_status='CANCELLED'):
        wait_until(lambda: psql(f"SELECT COUNT(*) FROM refunds WHERE payment_attempt_id='{attempt}';") == '1', timeout=45)
        self.assertEqual(psql(f"""SELECT a.status,a.accepted_at IS NULL,o.status,s.status,
            (SELECT COUNT(*) FROM refunds WHERE payment_attempt_id=a.id AND status='PROCESSING')
            FROM payment_attempts a JOIN orders o ON o.id=a.order_id
            JOIN session_seats s ON s.id='{SEATS[0]}' WHERE a.id='{attempt}';"""),
            f'SUCCEEDED\tt\t{order_status}\tAVAILABLE\t1')

    def test_e_crash_before_refund_obligation_commit(self):
        fake("/__admin__/configure", {"refundMode": "processing"})
        order, attempt, payment = self.start("case-e")
        self.assertEqual(request_json(f"/orders/{order['id']}/cancel", method="POST")[0], 200)
        self.install_fault("refunds", f"NEW.payment_attempt_id='{attempt}'")
        fake("/__admin__/configure", {"paymentId": payment['id'], "paymentStatus": "succeeded"})
        self.wake("payment_attempts", attempt)
        self.crash_and_restart("payment_attempts", attempt)
        self.assert_refund_obligation(order, attempt)

    def refund_ready(self, key):
        fake("/__admin__/configure", {"refundMode": "processing"})
        order, attempt, payment = self.start(key)
        request_json(f"/orders/{order['id']}/cancel", method="POST")
        fake("/__admin__/configure", {"paymentId": payment['id'], "paymentStatus": "succeeded"})
        self.wake("payment_attempts", attempt)
        refund = wait_until(lambda: psql(f"SELECT id FROM refunds WHERE payment_attempt_id='{attempt}';"))
        provider_id = wait_until(lambda: psql(f"SELECT provider_refund_id FROM refunds WHERE id='{refund}';"))
        return order, refund, provider_id

    def assert_refunded(self, order, refund):
        wait_until(lambda: psql(f"SELECT status FROM refunds WHERE id='{refund}';") == 'SUCCEEDED', timeout=45)
        self.assertEqual(psql(f"SELECT provider_status,provider_terminal_at IS NOT NULL,refunded_at IS NOT NULL,next_reconcile_at IS NULL,reconciliation_lease_token IS NULL FROM refunds WHERE id='{refund}';"), 'succeeded\tt\tt\tt\tt')
        self.assertEqual(psql(f"SELECT COUNT(*) FROM user_notifications WHERE order_id='{order['id']}' AND type='AUTO_REFUND_COMPLETED';"), '1')

    def test_f_refund_atomic_sql_rollback_then_restart(self):
        order, refund, provider_id = self.refund_ready('case-f')
        self.install_fault("user_notifications", f"NEW.order_id='{order['id']}' AND NEW.type='AUTO_REFUND_COMPLETED'", once=True)
        fake("/__admin__/configure", {"refundId": provider_id, "refundStatus": "succeeded"})
        self.wake("refunds", refund)
        wait_until(lambda: psql("SELECT is_called FROM phase11_fault_hits;") == 't')
        self.assertEqual(psql(f"SELECT status,provider_terminal_at IS NULL,next_reconcile_at IS NOT NULL FROM refunds WHERE id='{refund}';"), 'PROCESSING\tt\tt')
        compose("restart", "backend")
        self.assert_refunded(order, refund)
        self.assertGreaterEqual(self.retrieved('refund', provider_id), 2)

    def test_g_refund_claim_crash_lease_expiry_recovery(self):
        order, refund, provider_id = self.refund_ready('case-g')
        self.install_fault("refunds", f"NEW.id='{refund}' AND NEW.status='SUCCEEDED'")
        fake("/__admin__/configure", {"refundId": provider_id, "refundStatus": "succeeded"})
        self.wake("refunds", refund)
        self.crash_and_restart("refunds", refund)
        self.assert_refunded(order, refund)
        self.assertGreaterEqual(self.retrieved('refund', provider_id), 2)

    def test_payment_fallback_retrieves_and_rejects_each_identity_mismatch(self):
        order, attempt, payment = self.start('identity')
        compose('stop', 'backend')
        self.legacy_state(attempt, 'NULL')
        for field, wrong in [('id', 'pi_wrong'), ('amount', 1), ('currency', 'usd'),
                             ('metadata', {'local_payment_attempt_id': 'wrong', 'order_id': order['id']}),
                             ('metadata', {'local_payment_attempt_id': attempt, 'order_id': 'wrong'})]:
            before = self.retrieved('payment', payment['id'])
            fake('/__admin__/configure', {'paymentId': payment['id'], 'paymentStatus': 'succeeded', 'paymentPatch': {field: wrong}})
            compose('start', 'backend')
            wait_until(lambda: self.retrieved('payment', payment['id']) > before)
            compose('stop', 'backend')
            self.assertEqual(psql(f"SELECT status FROM orders WHERE id='{order['id']}';"), 'PENDING_PAYMENT')
            fake('/__admin__/configure', {'paymentId': payment['id'], 'paymentPatch': {field: payment[field]}})
        compose('start', 'backend')
        self.assert_paid(order, attempt)

    def test_stripe_terminal_failure_is_atomic_and_keeps_order_retryable(self):
        order, attempt, payment = self.start('terminal-failure')
        fake('/__admin__/configure', {'paymentId': payment['id'], 'paymentStatus': 'requires_payment_method'})
        self.wake('payment_attempts', attempt)
        wait_until(lambda: psql(f"SELECT status FROM payment_attempts WHERE id='{attempt}';") == 'FAILED')
        self.assertEqual(psql(f"SELECT provider_status,provider_terminal_at IS NOT NULL,failure_reason,next_reconcile_at IS NULL,reconciliation_lease_token IS NULL FROM payment_attempts WHERE id='{attempt}';"),
                         'requires_payment_method\tt\tcard_declined\tt\tt')
        self.assertEqual(psql(f"SELECT status FROM orders WHERE id='{order['id']}';"), 'PENDING_PAYMENT')
        self.assertEqual(psql(f"SELECT status FROM session_seats WHERE id='{SEATS[0]}';"), 'HELD')
        status, body = request_json(f"/orders/{order['id']}/pay", method='POST')
        self.assertEqual(status, 202)
        self.assertNotEqual(body['paymentAttempt']['id'], attempt)

    def test_existing_checks_still_reject_illegal_half_states(self):
        order, attempt, _ = self.start('checks')
        # A nested SQL block rolls back the rejected statement, not the CHECK.
        self.assertEqual(psql(f"""DO $$ BEGIN
            BEGIN UPDATE payment_attempts SET provider_terminal_at=clock_timestamp() WHERE id='{attempt}';
                RAISE EXCEPTION 'CHECK was not enforced';
            EXCEPTION WHEN check_violation THEN NULL; END;
            END $$; SELECT provider_terminal_at IS NULL FROM payment_attempts WHERE id='{attempt}';"""), 'DO\nt')



if __name__ == '__main__':
    unittest.main(verbosity=2)
