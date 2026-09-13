"""Reproduce the reviewed Phase19 baseline inventory from immutable Git objects."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = "2c680e78d532eace9e7f28862e7efb6ef2bdf4fb"
OUT = ROOT / "performance/experiments/phase19-global-polling-mixed-load"


def source(path: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(ROOT), "show", f"{BASE}:{path}"])


def inventory() -> dict:
    rows = [
        dict(id="notifications", file="frontend/src/App.vue", page="All authenticated pages",
             endpoints=["GET /notifications"], intervalMs=5000, maxDurationMs=None,
             serial=False, hiddenPause=False, retryAfter=False,
             terminal="Unauthenticated reads return locally; interval survives until unmount",
             risk="Timer, login, refreshMe and focus can overlap; late responses can restore old-user notifications"),
        dict(id="availability", file="frontend/src/pages/SeatSelectionPage.vue", page="Seat selection",
             endpoints=["GET /sessions/{sessionId}/seat-availability"], intervalMs="pollAfterMs; 500..30000; hasMore yields at 0",
             maxDurationMs=None, serial=True, hiddenPause=True, retryAfter=True,
             terminal="Unmount/session switch invalidates epoch; hidden drains existing work",
             risk="Existing adaptive policy; long Retry-After is capped at 30000 ms; shared identity lifecycle needs contract checks"),
        dict(id="admission", file="frontend/src/utils/admissionPolling.ts", page="Waiting room and active checkout lease",
             endpoints=["GET /events/{eventId}/admission", "POST /events/{eventId}/admission/heartbeat"],
             intervalMs="pollAfterMs with independent heartbeatAfterMs deadline", maxDurationMs=None,
             serial=True, hiddenPause=True, retryAfter=True,
             terminal="RESET_REQUIRED, SALES_ENDED, NOT_REQUIRED, stop/unmount",
             risk="Status and heartbeat share single flight; verify identity change and foreground contracts in consumers"),
        dict(id="refund", file="frontend/src/pages/OrderPage.vue", page="Order with PROCESSING buyer refund",
             endpoints=["GET /orders/{orderId}"], intervalMs=2000, maxDurationMs=None,
             serial=True, hiddenPause=True, retryAfter=False,
             terminal="Buyer refund no longer PROCESSING; route switch/unmount",
             risk="createRefund pollAfterMs unused; no error backoff; already has order-read coalescing and foreground handling"),
        dict(id="payment", file="frontend/src/pages/OrderPage.vue", page="Processing payment/recovery",
             endpoints=["GET /payment-attempts/{attemptId}", "GET /orders/{orderId}"], intervalMs=1000,
             maxDurationMs=15000, serial="Timer loop only; focus/manual attempt reads may overlap", hiddenPause=False, retryAfter=False,
             terminal="Attempt settles, order leaves PENDING_PAYMENT, route/unmount, 15s checked after response",
             risk="Timer continues hidden; no request time-inclusive hard deadline or error backoff"),
        dict(id="submitting", file="frontend/src/pages/SeatSelectionPage.vue", page="Unknown checkout confirmation result",
             endpoints=["GET /checkout-sessions/{checkoutId}"], intervalMs=2000, maxDurationMs=15000,
             serial="Timer loop only; focus/manual checkout reads may overlap", hiddenPause=False, retryAfter=False,
             terminal="Checkout leaves SUBMITTING, route/unmount invalidates next iteration, 15s checked after response",
             risk="Missing epoch check after awaited GET; stale response can adopt state or navigate; timeout handle not retained"),
        dict(id="sales-boundary", file="frontend/src/utils/salesWindow.ts", page="Event/session/seat sales countdown",
             endpoints=["Consumer-provided authoritative refresh once per state/boundary"], intervalMs=1000,
             maxDurationMs=None, serial="Not a recurring HTTP loop", hiddenPause=False, retryAfter=False,
             terminal="One refresh per visited state/boundary; unmount clears local timer",
             risk="Display timer with one-off boundary refresh; must not classify as HTTP every second"),
        dict(id="order-countdown", file="frontend/src/components/OrderSummary.vue", page="Order summary",
             endpoints=[], intervalMs=1000, maxDurationMs=None, serial="Not a recurring HTTP loop",
             hiddenPause=False, retryAfter=False, terminal="Unmount clears local timer",
             risk="Local expiry countdown; no recurring API request"),
    ]
    for row in rows:
        row["sourceSha256"] = hashlib.sha256(source(row["file"])).hexdigest()
    old = "performance/experiments/phase18-admission-overload/protocol/browser.mjs"
    return {"schemaVersion": 1, "baseCommit": BASE, "reviewKind": "static source inspection; runtime evidence separate",
            "pollers": rows, "phase18BrowserScope": {"file": old,
            "sourceSha256": hashlib.sha256(source(old)).hexdigest(),
            "filter": "/seat-availability", "provesGlobalPolling": False}}


def markdown(data: dict) -> str:
    lines = ["# Phase19 baseline polling inventory", "", f"Baseline: `{data['baseCommit']}`. Static inspection; runtime results are separate.", "",
             "| Poller | File / page | Endpoints | Interval / deadline | Serial / hidden / Retry-After | Terminal / risk |",
             "| --- | --- | --- | --- | --- | --- |"]
    for r in data["pollers"]:
        cells = [r["id"], r["file"] + " / " + r["page"], "; ".join(r["endpoints"]) or "None",
                 f"{r['intervalMs']} ms / {r['maxDurationMs']} ms",
                 f"{r['serial']} / {r['hiddenPause']} / {r['retryAfter']}", r["terminal"] + "; " + r["risk"]]
        lines.append("| " + " | ".join(str(c).replace("|", "/") for c in cells) + " |")
    lines += ["", "Phase18 browser request instrumentation filters `/seat-availability`; its evidence does not establish global polling behavior.",
              "", "The sales countdown can issue a one-off authoritative refresh at a boundary. Its 1s timer is not a 1 req/s polling loop. Preserve local countdown semantics.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    data = inventory()
    (OUT / "inventory.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    (OUT / "POLLING_INVENTORY.md").write_text(markdown(data), encoding="utf-8")
