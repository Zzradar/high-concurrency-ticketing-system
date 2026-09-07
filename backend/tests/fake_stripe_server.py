#!/usr/bin/env python3
"""Deterministic, dependency-free Stripe REST test double for Phase11."""

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote


class Store:
    def __init__(self):
        self.lock = threading.Lock()
        self.payments = {}
        self.refunds = {}
        self.payment_keys = {}
        self.refund_keys = {}
        self.create_payment_calls = []
        self.create_refund_calls = []
        self.payment_mode = "processing"
        self.refund_mode = "succeeded"
        self.fail_once = set()

    def reset(self):
        self.__init__()


STORE = Store()


def form_value(values, key, default=""):
    return values.get(key, [default])[0]


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def log_request_line(self):
        print(f"{self.command} {self.path}", flush=True)

    def json_response(self, status, value):
        data = json.dumps(value, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_json(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")

    def read_form(self):
        data = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode()
        return parse_qs(data, keep_blank_values=True)

    def do_GET(self):
        self.log_request_line()
        if self.path == "/__admin__/state":
            with STORE.lock:
                self.json_response(200, {
                    "payments": list(STORE.payments.values()),
                    "refunds": list(STORE.refunds.values()),
                    "paymentKeys": dict(STORE.payment_keys),
                    "refundKeys": dict(STORE.refund_keys),
                    "createPaymentCalls": list(STORE.create_payment_calls),
                    "createRefundCalls": list(STORE.create_refund_calls),
                })
            return
        if self.path.startswith("/v1/payment_intents/"):
            object_id = unquote(self.path.rsplit("/", 1)[-1])
            with STORE.lock:
                value = STORE.payments.get(object_id)
            return self.json_response(200 if value else 404, value or {"error": {"type": "invalid_request_error"}})
        if self.path.startswith("/v1/refunds/"):
            object_id = unquote(self.path.rsplit("/", 1)[-1])
            with STORE.lock:
                value = STORE.refunds.get(object_id)
            return self.json_response(200 if value else 404, value or {"error": {"type": "invalid_request_error"}})
        self.json_response(404, {"error": {"type": "not_found"}})

    def do_POST(self):
        self.log_request_line()
        if self.path == "/__admin__/reset":
            with STORE.lock:
                STORE.payments.clear(); STORE.refunds.clear()
                STORE.payment_keys.clear(); STORE.refund_keys.clear()
                STORE.create_payment_calls.clear(); STORE.create_refund_calls.clear()
                STORE.payment_mode = "processing"; STORE.refund_mode = "succeeded"
                STORE.fail_once.clear()
            return self.json_response(200, {"ok": True})
        if self.path == "/__admin__/configure":
            config = self.read_json()
            with STORE.lock:
                if "paymentMode" in config: STORE.payment_mode = config["paymentMode"]
                if "refundMode" in config: STORE.refund_mode = config["refundMode"]
                if "paymentId" in config and "paymentStatus" in config:
                    STORE.payments[config["paymentId"]]["status"] = config["paymentStatus"]
                    if config["paymentStatus"] == "requires_payment_method":
                        STORE.payments[config["paymentId"]]["last_payment_error"] = {"code": "card_declined"}
                if "refundId" in config and "refundStatus" in config:
                    STORE.refunds[config["refundId"]]["status"] = config["refundStatus"]
                    if config["refundStatus"] == "failed":
                        STORE.refunds[config["refundId"]]["failure_reason"] = "declined"
            return self.json_response(200, {"ok": True})
        if self.path == "/v1/payment_intents":
            values = self.read_form()
            key = self.headers.get("Idempotency-Key", "")
            with STORE.lock:
                STORE.create_payment_calls.append(key)
                object_id = STORE.payment_keys.get(key)
                if not object_id:
                    object_id = "pi_fake_" + str(len(STORE.payments) + 1)
                    STORE.payment_keys[key] = object_id
                    STORE.payments[object_id] = {
                        "id": object_id, "object": "payment_intent",
                        "status": "processing", "amount": int(form_value(values, "amount", "0")),
                        "currency": form_value(values, "currency"),
                        "client_secret": object_id + "_secret_test",
                        "metadata": {
                            "local_payment_attempt_id": form_value(values, "metadata[local_payment_attempt_id]"),
                            "order_id": form_value(values, "metadata[order_id]"),
                        }, "last_payment_error": None,
                    }
                value = dict(STORE.payments[object_id])
                mode = STORE.payment_mode
                first_failure = (mode, key) not in STORE.fail_once
                if first_failure: STORE.fail_once.add((mode, key))
            if mode == "response_lost_once" and first_failure:
                self.connection.shutdown(1); self.connection.close(); return
            if mode == "429_once" and first_failure:
                return self.json_response(429, {"error": {"type": "rate_limit_error"}})
            if mode == "500_once" and first_failure:
                return self.json_response(500, {"error": {"type": "api_error"}})
            if mode in ("succeeded", "requires_payment_method"):
                with STORE.lock:
                    STORE.payments[object_id]["status"] = mode
                    if mode == "requires_payment_method":
                        STORE.payments[object_id]["last_payment_error"] = {"code": "card_declined"}
                    value = dict(STORE.payments[object_id])
            return self.json_response(200, value)
        if self.path == "/v1/refunds":
            values = self.read_form()
            key = self.headers.get("Idempotency-Key", "")
            with STORE.lock:
                STORE.create_refund_calls.append(key)
                object_id = STORE.refund_keys.get(key)
                if not object_id:
                    object_id = "re_fake_" + str(len(STORE.refunds) + 1)
                    STORE.refund_keys[key] = object_id
                    STORE.refunds[object_id] = {
                        "id": object_id, "object": "refund", "status": STORE.refund_mode,
                        "payment_intent": form_value(values, "payment_intent"),
                        "amount": int(form_value(values, "amount", "0")),
                        "metadata": {"local_refund_id": form_value(values, "metadata[local_refund_id]"),
                                     "order_id": form_value(values, "metadata[order_id]")},
                    }
                    if STORE.refund_mode == "failed":
                        STORE.refunds[object_id]["failure_reason"] = "declined"
                value = dict(STORE.refunds[object_id]); mode = STORE.refund_mode
                first_failure = ("refund_" + mode, key) not in STORE.fail_once
                if first_failure: STORE.fail_once.add(("refund_" + mode, key))
            if mode == "response_lost_once" and first_failure:
                self.connection.shutdown(1); self.connection.close(); return
            return self.json_response(200, value)
        self.json_response(404, {"error": {"type": "not_found"}})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=18081)
    args = parser.parse_args()
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()
