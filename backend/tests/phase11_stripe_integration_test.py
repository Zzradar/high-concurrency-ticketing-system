import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import time
import unittest
from urllib.request import Request, urlopen

from auth_test_support import anonymous_request
from payment_integration_test import cleanup, create_order, psql, request_json, SEATS


FAKE_URL = os.environ.get("FAKE_STRIPE_URL", "http://127.0.0.1:18081")
WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "whsec_phase11_test")
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def fake(path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = Request(FAKE_URL + path, data=data,
                      headers={"Content-Type": "application/json"},
                      method="POST" if data is not None else "GET")
    with urlopen(request, timeout=10) as response:
        return json.load(response)


def wait_until(predicate, timeout=15, message="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.2)
    raise AssertionError(f"Timed out waiting for {message}")


def payment_for_attempt(attempt_id):
    state = fake("/__admin__/state")
    return next((item for item in state["payments"]
                 if item["metadata"]["local_payment_attempt_id"] == attempt_id), None)


def signed_webhook(event_id, event_type, provider_object):
    body = json.dumps({"id": event_id, "type": event_type,
                       "data": {"object": provider_object}}, separators=(",", ":")).encode()
    timestamp = int(time.time())
    signature = hmac.new(WEBHOOK_SECRET.encode(),
                         str(timestamp).encode() + b"." + body,
                         hashlib.sha256).hexdigest()
    return anonymous_request(
        "/payment-webhooks/stripe", method="POST", raw_body=body,
        headers={"Content-Type": "application/json",
                 "Stripe-Signature": f"t={timestamp},v1={signature}"})[:2]


class Phase11StripeIntegrationTest(unittest.TestCase):
    def setUp(self):
        fake("/__admin__/reset", {})
        psql("DELETE FROM payment_provider_events;")
        cleanup(create_users=True)

    def tearDown(self):
        if os.environ.get("PHASE11_PRESERVE_FAILURE") != "1":
            cleanup()
            psql("DELETE FROM payment_provider_events;")

    def start(self, key, seat):
        order, _ = create_order(key, seat)
        status, response = request_json(f"/orders/{order['id']}/pay", method="POST")
        self.assertEqual(status, 202)
        self.assertEqual(response["paymentAction"]["provider"], "stripe")
        self.assertEqual(response["paymentAction"]["type"], "CLIENT_CONFIRM")
        return order, response["paymentAttempt"]["id"]

    def test_webhook_duplicate_and_out_of_order_retrieve_latest(self):
        order, attempt = self.start("stripe-webhook", SEATS[0])
        payment = wait_until(lambda: payment_for_attempt(attempt), message="provider payment")
        fake("/__admin__/configure", {"paymentId": payment["id"], "paymentStatus": "succeeded"})
        payment = payment_for_attempt(attempt)
        self.assertEqual(signed_webhook("evt-duplicate", "payment_intent.succeeded", payment)[0], 200)
        self.assertEqual(signed_webhook("evt-duplicate", "payment_intent.succeeded", payment)[0], 200)
        old = dict(payment); old["status"] = "processing"
        self.assertEqual(signed_webhook("evt-out-of-order", "payment_intent.processing", old)[0], 200)
        wait_until(lambda: psql(f"SELECT status FROM orders WHERE id='{order['id']}';") == "PAID",
                   message="paid order")
        self.assertEqual(psql("SELECT COUNT(*) FROM payment_provider_events WHERE provider_event_id='evt-duplicate';"), "1")
        self.assertEqual(psql(f"SELECT COUNT(*) FROM user_notifications WHERE order_id='{order['id']}' AND type='PAYMENT_SUCCEEDED';"), "1")

    def test_create_response_lost_and_webhook_lost_recover_by_scan(self):
        fake("/__admin__/configure", {"paymentMode": "response_lost_once"})
        order, _ = create_order("stripe-response-lost", SEATS[1])
        status, response = request_json(f"/orders/{order['id']}/pay", method="POST")
        self.assertEqual(status, 202)
        attempt = response["paymentAttempt"]["id"]
        payment = wait_until(lambda: payment_for_attempt(attempt), message="idempotent payment")
        fake("/__admin__/configure", {"paymentId": payment["id"], "paymentStatus": "succeeded"})
        wait_until(lambda: psql(f"SELECT status FROM orders WHERE id='{order['id']}';") == "PAID",
                   message="active scan payment recovery")
        state = fake("/__admin__/state")
        self.assertEqual(len([p for p in state["payments"] if p["metadata"]["local_payment_attempt_id"] == attempt]), 1)
        self.assertGreaterEqual(state["createPaymentCalls"].count(attempt), 2)

    def test_backend_restart_recovers_processing_payment(self):
        order, attempt = self.start("stripe-restart", SEATS[2])
        payment = wait_until(lambda: payment_for_attempt(attempt), message="payment before restart")
        subprocess.run(["docker", "compose", "restart", "backend"], cwd=BACKEND_ROOT, check=True)
        fake("/__admin__/configure", {"paymentId": payment["id"], "paymentStatus": "succeeded"})
        wait_until(lambda: psql(f"SELECT status FROM orders WHERE id='{order['id']}';") == "PAID",
                   timeout=20, message="restart recovery")

    def test_late_success_refund_response_lost_is_idempotent(self):
        fake("/__admin__/configure", {"refundMode": "response_lost_once"})
        order, attempt = self.start("stripe-refund-lost", SEATS[3])
        payment = payment_for_attempt(attempt)
        status, cancelled = request_json(f"/orders/{order['id']}/cancel", method="POST")
        self.assertEqual((status, cancelled["order"]["status"]), (200, "CANCELLED"))
        fake("/__admin__/configure", {"paymentId": payment["id"], "paymentStatus": "succeeded"})
        refund_id = wait_until(
            lambda: psql(f"SELECT id FROM refunds WHERE payment_attempt_id='{attempt}';") or None,
            message="refund obligation")
        provider_refund = wait_until(lambda: next(iter(fake("/__admin__/state")["refunds"]), None),
                                     message="provider refund")
        fake("/__admin__/configure", {"refundId": provider_refund["id"], "refundStatus": "succeeded"})
        wait_until(lambda: psql(f"SELECT status FROM refunds WHERE id='{refund_id}';") == "SUCCEEDED",
                   message="refund completion")
        state = fake("/__admin__/state")
        self.assertEqual(len(state["refunds"]), 1)
        self.assertGreaterEqual(state["createRefundCalls"].count(refund_id), 2)
        self.assertEqual(psql(f"SELECT status FROM orders WHERE id='{order['id']}';"), "CANCELLED")

    def test_refund_terminal_failure_notifies(self):
        fake("/__admin__/configure", {"refundMode": "failed"})
        order, attempt = self.start("stripe-refund-failed", SEATS[4])
        payment = payment_for_attempt(attempt)
        request_json(f"/orders/{order['id']}/cancel", method="POST")
        fake("/__admin__/configure", {"paymentId": payment["id"], "paymentStatus": "succeeded"})
        wait_until(lambda: psql(f"SELECT status FROM refunds WHERE payment_attempt_id='{attempt}';") == "FAILED",
                   message="failed refund")
        self.assertEqual(psql(f"SELECT COUNT(*) FROM user_notifications WHERE order_id='{order['id']}' AND type='AUTO_REFUND_FAILED';"), "1")

    def test_provider_500_is_retryable_and_recovers(self):
        fake("/__admin__/configure", {"paymentMode": "500_once"})
        order, _ = create_order("stripe-500", SEATS[0])
        status, response = request_json(f"/orders/{order['id']}/pay", method="POST")
        self.assertEqual(status, 202)
        attempt = response["paymentAttempt"]["id"]
        self.assertIsNone(response["paymentAction"])
        payment = wait_until(lambda: payment_for_attempt(attempt), message="payment after 500")
        fake("/__admin__/configure", {"paymentId": payment["id"], "paymentStatus": "succeeded"})
        wait_until(lambda: psql(f"SELECT status FROM orders WHERE id='{order['id']}';") == "PAID",
                   message="500 recovery")
        self.assertGreaterEqual(int(psql(f"SELECT provider_retry_count FROM payment_attempts WHERE id='{attempt}';")), 1)

    def test_expired_order_late_success_refunds_without_inventory_revival(self):
        fake("/__admin__/configure", {"refundMode": "succeeded"})
        order, attempt = self.start("stripe-expired-late", SEATS[1])
        payment = payment_for_attempt(attempt)
        psql(f"""
            UPDATE payment_attempts SET started_at=clock_timestamp()-INTERVAL '20 seconds',
                processing_deadline=clock_timestamp()-INTERVAL '1 second'
            WHERE id='{attempt}';
            UPDATE reservations SET created_at=clock_timestamp()-INTERVAL '20 minutes',
                expires_at=clock_timestamp()-INTERVAL '1 second'
            WHERE id='{order['reservationId']}';
            UPDATE orders SET created_at=clock_timestamp()-INTERVAL '20 minutes',
                expires_at=clock_timestamp()-INTERVAL '1 second'
            WHERE id='{order['id']}';
        """)
        wait_until(lambda: psql(f"SELECT status FROM orders WHERE id='{order['id']}';") == "EXPIRED",
                   message="expired order")
        fake("/__admin__/configure", {"paymentId": payment["id"], "paymentStatus": "succeeded"})
        psql(f"UPDATE payment_attempts SET next_reconcile_at=clock_timestamp() WHERE id='{attempt}';")
        wait_until(lambda: psql(f"SELECT status FROM refunds WHERE payment_attempt_id='{attempt}';") == "SUCCEEDED",
                   message="expired late refund")
        self.assertEqual(psql(f"SELECT status FROM session_seats WHERE id='{SEATS[1]}';"), "AVAILABLE")
        self.assertEqual(psql(f"SELECT accepted_at IS NULL FROM payment_attempts WHERE id='{attempt}';"), "t")

    def test_duplicate_late_success_refunds_after_newer_attempt_paid(self):
        fake("/__admin__/configure", {"refundMode": "succeeded"})
        order, first_attempt = self.start("stripe-duplicate-late", SEATS[3])
        first_payment = payment_for_attempt(first_attempt)
        psql(f"""
            UPDATE payment_attempts SET started_at=clock_timestamp()-INTERVAL '20 seconds',
                processing_deadline=clock_timestamp()-INTERVAL '1 second'
            WHERE id='{first_attempt}';
        """)

        status, response = request_json(f"/orders/{order['id']}/pay", method="POST")
        self.assertEqual(status, 202)
        second_attempt = response["paymentAttempt"]["id"]
        self.assertNotEqual(second_attempt, first_attempt)
        second_payment = wait_until(lambda: payment_for_attempt(second_attempt),
                                    message="newer provider payment")
        fake("/__admin__/configure", {"paymentId": second_payment["id"],
                                      "paymentStatus": "succeeded"})
        psql(f"UPDATE payment_attempts SET next_reconcile_at=clock_timestamp() WHERE id='{second_attempt}';")
        wait_until(lambda: psql(f"SELECT status FROM orders WHERE id='{order['id']}';") == "PAID",
                   message="newer attempt paid")

        fake("/__admin__/configure", {"paymentId": first_payment["id"],
                                      "paymentStatus": "succeeded"})
        psql(f"UPDATE payment_attempts SET next_reconcile_at=clock_timestamp() WHERE id='{first_attempt}';")
        wait_until(lambda: psql(
            f"SELECT status FROM refunds WHERE payment_attempt_id='{first_attempt}';") == "SUCCEEDED",
            message="duplicate late success refund")
        self.assertEqual(psql(f"SELECT accepted_at IS NULL FROM payment_attempts WHERE id='{first_attempt}';"), "t")
        self.assertEqual(psql(f"SELECT accepted_at IS NOT NULL FROM payment_attempts WHERE id='{second_attempt}';"), "t")
        self.assertEqual(psql(f"SELECT COUNT(*) FROM refunds WHERE order_id='{order['id']}';"), "1")
        self.assertEqual(psql(f"SELECT COUNT(*) FROM user_notifications WHERE order_id='{order['id']}' AND type='PAYMENT_SUCCEEDED';"), "1")

    def test_webhook_inbox_database_failure_returns_5xx(self):
        order, attempt = self.start("stripe-inbox-failure", SEATS[2])
        payment = payment_for_attempt(attempt)
        psql("""
            CREATE OR REPLACE FUNCTION phase11_fail_inbox() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'forced inbox failure'; END $$;
            CREATE TRIGGER phase11_fail_inbox BEFORE INSERT ON payment_provider_events
            FOR EACH ROW EXECUTE FUNCTION phase11_fail_inbox();
        """)
        try:
            status, _ = signed_webhook("evt-inbox-failure", "payment_intent.processing", payment)
            self.assertGreaterEqual(status, 500)
        finally:
            psql("DROP TRIGGER IF EXISTS phase11_fail_inbox ON payment_provider_events; DROP FUNCTION IF EXISTS phase11_fail_inbox();")


if __name__ == "__main__":
    unittest.main(verbosity=2)
