# Phase19 baseline polling inventory

Baseline: `2c680e78d532eace9e7f28862e7efb6ef2bdf4fb`. Static inspection; runtime results are separate.

| Poller | File / page | Endpoints | Interval / deadline | Serial / hidden / Retry-After | Terminal / risk |
| --- | --- | --- | --- | --- | --- |
| notifications | frontend/src/App.vue / All authenticated pages | GET /notifications | 5000 ms / None ms | False / False / False | Unauthenticated reads return locally; interval survives until unmount; Timer, login, refreshMe and focus can overlap; late responses can restore old-user notifications |
| availability | frontend/src/pages/SeatSelectionPage.vue / Seat selection | GET /sessions/{sessionId}/seat-availability | pollAfterMs; 500..30000; hasMore yields at 0 ms / None ms | True / True / True | Unmount/session switch invalidates epoch; hidden drains existing work; Existing adaptive policy; long Retry-After is capped at 30000 ms; shared identity lifecycle needs contract checks |
| admission | frontend/src/utils/admissionPolling.ts / Waiting room and active checkout lease | GET /events/{eventId}/admission; POST /events/{eventId}/admission/heartbeat | pollAfterMs with independent heartbeatAfterMs deadline ms / None ms | True / True / True | RESET_REQUIRED, SALES_ENDED, NOT_REQUIRED, stop/unmount; Status and heartbeat share single flight; verify identity change and foreground contracts in consumers |
| refund | frontend/src/pages/OrderPage.vue / Order with PROCESSING buyer refund | GET /orders/{orderId} | 2000 ms / None ms | True / True / False | Buyer refund no longer PROCESSING; route switch/unmount; createRefund pollAfterMs unused; no error backoff; already has order-read coalescing and foreground handling |
| payment | frontend/src/pages/OrderPage.vue / Processing payment/recovery | GET /payment-attempts/{attemptId}; GET /orders/{orderId} | 1000 ms / 15000 ms | Timer loop only; focus/manual attempt reads may overlap / False / False | Attempt settles, order leaves PENDING_PAYMENT, route/unmount, 15s checked after response; Timer continues hidden; no request time-inclusive hard deadline or error backoff |
| submitting | frontend/src/pages/SeatSelectionPage.vue / Unknown checkout confirmation result | GET /checkout-sessions/{checkoutId} | 2000 ms / 15000 ms | Timer loop only; focus/manual checkout reads may overlap / False / False | Checkout leaves SUBMITTING, route/unmount invalidates next iteration, 15s checked after response; Missing epoch check after awaited GET; stale response can adopt state or navigate; timeout handle not retained |
| sales-boundary | frontend/src/utils/salesWindow.ts / Event/session/seat sales countdown | Consumer-provided authoritative refresh once per state/boundary | 1000 ms / None ms | Not a recurring HTTP loop / False / False | One refresh per visited state/boundary; unmount clears local timer; Display timer with one-off boundary refresh; must not classify as HTTP every second |
| order-countdown | frontend/src/components/OrderSummary.vue / Order summary | None | 1000 ms / None ms | Not a recurring HTTP loop / False / False | Unmount clears local timer; Local expiry countdown; no recurring API request |

Phase18 browser request instrumentation filters `/seat-availability`; its evidence does not establish global polling behavior.

The sales countdown can issue a one-off authoritative refresh at a boundary. Its 1s timer is not a 1 req/s polling loop. Preserve local countdown semantics.
