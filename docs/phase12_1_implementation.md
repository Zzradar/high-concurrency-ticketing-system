# Phase 12-1 implementation record

## 2026-09-08: sold-seat ownership decision

User approved option 2. Preserve Phase 11's SOLD / current_reservation_id IS NULL
shape, payment acceptance path, existing payment assertions and Performance verifier.
No historical seat-owner backfill is introduced.

The real detail table is reservation_session_seats (called reservation_seats in
the decision). Refund completion locks Order -> Refund -> Reservation -> SessionSeat
(seat ID ascending). Before touching Reservation or Seat, verify PROCESSING, lease
token and the complete immutable refund/payment identity. For BUYER success require
the linked PAID Order and CONFIRMED Reservation, a nonempty distinct complete detail
set, and SOLD seats with NULL pointers. Each seat must have exactly one effective
CONFIRMED Reservation + PAID Order owner: the target pair. Cancelled/expired history
does not count. Conflicts roll back the entire transaction and produce an invariant
error. Conditional release must update exactly the detail count. Legal reservation
creation must lock/check these same inventory rows. A stale worker exits at the
refund fence before locking seats, including after resale.

Required evidence: normal NULL-pointer refund; wrong seat state rollback; duplicate
effective owner rollback; stale lease after resale; unchanged payment and Performance
assertions. Provider success alone cannot bypass any local invariant.

Baseline: main@2f1870eb33260266e52381ffbafae051a33c75ca; clean working tree.
Scope: backend only, Fake Stripe gate; no frontend, real Sandbox or push.
Final status (2026-09-09): Phase 12-1 backend implementation is complete and its
engineering gate has passed, as accepted by the user. The legacy-test compatibility
boundary recorded in f569cc6 is resolved by the separately approved test commit
41ff7f7. The implementation checkpoint f569cc6 is preserved without amendment or merge.
Frontend work and real Stripe Sandbox validation are outside Phase 12-1 scope.


## Implementation map

- Migration 009 adds explicit currency snapshots (no defaults), refund source/reason
  pairing, buyer/order partial uniqueness, order refunded_at shape and four refund
  notification types. Existing 001–008 migrations are untouched.
- RefundService locks the order, checks owner, reuses existing BUYER refunds before
  checking the database deadline, and commits a new obligation without HTTP.
  RefundRepository uses the real reservation_session_seats schema via OrderRepository.
  RefundController reuses AuthFilter/CSRF and rejects every nonempty request body.
- RefundLifecycleService fences the lease and complete payment/refund identity before
  Reservation/Seat access. BUYER success verifies the nonempty detail set, SOLD/NULL
  shape and unique effective PAID/CONFIRMED ownership under ordered seat locks.
  All terminal writes and notification share a transaction; refund/order timestamps
  share one clock_timestamp(). SYSTEM terminals never change ticket rights.
- StripePaymentProvider scans at most ten pages of 100 objects before creation,
  verifies payment/amount/currency/local-refund/order identity on List/Create/Retrieve,
  and never retries POST within the same failed round. The definitive-reject whitelist
  is intentionally empty: only identified failed/canceled objects become FAILED.
  Unknown errors remain retryable; operational/identity conflicts use five minutes.
- PaymentReconciliationWorker is reused, with existing 30-second leases and backoff.
  Refund Webhooks wake work but never bind the provider refund ID. Payment Webhooks
  and payment acceptance/seat-selling semantics are unchanged. PaymentService's only
  change is reading the saved currency, required by the Phase 12 design.
- Metrics use bounded labels. Prometheus includes four refund alert rules. The
  15-minute age and three-local-failures thresholds are provisional investigation
  thresholds, awaiting Phase 12-2 Sandbox/load measurements, not a business SLO.

## Official comparisons (checked 2026-09-08)

- [pretix order lifecycle](https://docs.pretix.eu/dev/api/guides/order_lifecycle.html)
  and [provider interface](https://docs.pretix.eu/dev/development/api/payment.html):
  independent refund object and provider completion responsibilities.
- [Vendure payment service](https://raw.githubusercontent.com/vendure-ecommerce/vendure/master/packages/core/src/service/services/payment.service.ts)
  and [payment handler](https://raw.githubusercontent.com/vendure-ecommerce/vendure/master/packages/core/src/config/payment/payment-method-handler.ts):
  refunds relate to payments, provider capabilities stay in the adapter.
- [Saleor refunds](https://docs.saleor.io/developer/payments/refunds): existing
  transaction identity, business amount and remaining charged amount checks.
- [Solidus refund](https://raw.githubusercontent.com/solidusio/solidus/main/core/app/models/spree/refund.rb):
  payment-associated refund and gateway separation. The supplied cancellation.rb URL
  could not be retrieved; it is not claimed as verified evidence.
- Stripe [create](https://docs.stripe.com/api/refunds/create),
  [retrieve](https://docs.stripe.com/api/refunds/retrieve),
  [list](https://docs.stripe.com/api/refunds/list),
  [idempotency](https://docs.stripe.com/api/idempotent_requests),
  [errors](https://docs.stripe.com/error-low-level): currency is inherited on create;
  idempotency retention is finite; indeterminate results require recovery.

No external framework, partial-refund policy, admin approval, event bus or MQ is adopted.

## Database upgrade

Fresh databases: Compose mounts 001–009 before the demo seed and verifiers. The
PostgreSQL entrypoint runs these only on an empty data directory. Tests use a separate
phase12-approved project for the final gate; existing application and Performance
volumes were not upgraded or deleted.

Existing volumes: back up first, stop application writers in a maintenance window,
confirm the actual historical payment currency from trusted channel records, then run
in the SAME psql session (ON_ERROR_STOP enabled):

```sql
SET ticketing.legacy_payment_currency = 'cny'; -- example only; verify actual history
\i /path/to/009_add_buyer_full_refund.sql
```

Do not infer history from today's STRIPE_CURRENCY. If currencies were mixed, do not
run this single-currency migration: prepare and review a per-attempt authoritative
mapping instead. Currency syntax validation cannot establish historical truth.
Migration DDL/backfill is transactional. Deploy the new binary only with schema 009;
rolling back the binary also requires a planned schema/data rollback, not merely
removing the Compose mount. No seat-owner backfill is required by option 2.

## Validation commands

Local Docker access is required. Runtime tests use fake-only keys:

```powershell
$env:COMPOSE_FILE=(Resolve-Path backend/tests/compose.phase12.yml).Path
$env:COMPOSE_PROJECT_NAME='phase12-gate'
$env:TICKETING_BASE_URL='http://127.0.0.1:18094'
$env:FAKE_STRIPE_URL='http://127.0.0.1:18085'
$env:TICKETING_PAYMENT_PROVIDER='stripe'
$env:STRIPE_SECRET_KEY='sk_test_phase12_fake'
$env:STRIPE_WEBHOOK_SECRET='whsec_phase11_test'
$env:STRIPE_API_BASE_URL='http://fake-stripe:18081'
python backend/tests/phase12_migration_test.py
python backend/tests/phase12_source_contract_test.py
python backend/tests/phase12_buyer_refund_integration_test.py
python backend/tests/phase11_stripe_integration_test.py
python backend/tests/phase11_crash_window_integration_test.py
```

The migration suite expects the isolated phase12-db PostgreSQL container (ticketing
user/database). It creates random schemas and removes only those schemas. The commands
above describe the checked-in phase12-gate Compose defaults and image
phase12-backend:local; build that image with `docker build -t phase12-backend:local backend`.
For simulation suites, recreate the backend with TICKETING_PAYMENT_PROVIDER=simulation
and TICKETING_PAYMENT_FORCE_OUTCOME=SUCCESS (or FAILURE for the failure suite), then
wait for health before testing.

## Approved compatibility changes

The user approved a finite exception for eight existing test/fixture files. Commit
41ff7f7 applies those changes independently of f569cc6. No production code, Fake Stripe
implementation, payment SOLD/NULL assertion or Performance verifier was changed during
this compatibility work.

| Existing file | Applied change |
| --- | --- |
| phase3_schema_contract_test.py | Expected seed/verify mount suffixes 008/009 → 010/011 |
| phase5_schema_contract_test.py | Expected seed/verify suffixes shifted by two |
| phase8_schema_contract_test.py | Expected seed/verify suffixes shifted by two |
| phase9_auth_schema_contract_test.py | Expected seed/verify suffixes shifted by two |
| performance_metrics_source_contract_test.py | Add the five required refund metric names to the exact expected set |
| order_lifecycle_integration_test.py | Add explicit cny to two synthetic payment-attempt inserts |
| db/tests/003_verify_payment_schema.sql | Add explicit synthetic currency to existing attempt/refund fixtures |
| phase11_stripe_integration_test.py | Require exactly one refund POST and recovery List Refunds queries for the original PaymentIntent |

The response-loss test reads Fake Stripe's actual `refundLists` field. Each entry is
the query-parameter dictionary produced by parse_qs, with `payment_intent` represented
as a list of strings. The test counts entries whose value equals `[payment["id"]]`
and requires at least two: the initially empty provider's pre-create scan, followed
by recovery scanning after the first create response is lost. It simultaneously proves:

- Fake Stripe contains exactly one Refund object.
- POST /v1/refunds was called exactly once for the local refund.
- Recovery includes GET /v1/refunds filtered by the original PaymentIntent.
- The local Refund reaches SUCCEEDED and the original Order remains CANCELLED.

[phase12_1_test_compatibility.patch](phase12_1_test_compatibility.patch) is retained as
the historical proposal from f569cc6, not a patch to reapply. The committed test file
includes the additional refundLists assertion requested after that proposal was reviewed.

## Final validation evidence (2026-09-09)

All results below are from the completed validation run accepted by the user. Repository
closeout records these results without rerunning the full gate or changing test results.

| Check | Final result |
| --- | --- |
| Normal Dockerfile build and CTest | Passed; 28/28 tests; image phase12-backend:verified |
| Fresh PostgreSQL volume initialization | Passed; migrations 001–009, demo seed and all SQL verifiers executed |
| Phase 12 migration suite | 4/4 passed |
| Phase 12 source contracts (host) | 5/5 passed |
| Original Performance observability contract | 1/1 passed |
| Phase 11 Stripe integration | 11/11 passed, including the strengthened lost-response recovery test |
| Phase 12 buyer refund integration | 38/38 passed in one run |
| Phase 11 crash-window integration | 11/11 passed |
| Original simulation payment integration | 6/6 passed, including SOLD/NULL ownership assertions |
| Order lifecycle integration | 2/2 passed |
| Simulation payment failure integration | 1/1 passed |
| Refund smoke tests with metrics enabled | 3/3 passed |
| Live /metrics | All five refund metrics present; four counters had positive values; no order/refund/user ID labels on refund metrics |
| Prometheus promtool | Four refund alert rules valid |
| Compatibility diff validation | git diff --check passed; changes confined to the approved eight files |

The final run used the normal Dockerfile, including its CTest step, to produce
phase12-backend:verified. A separate phase12-approved environment used API port 18096,
Fake Stripe port 18097 and the new volume phase12-approved_phase12_postgres_data.
PostgreSQL's entrypoint actually executed migrations 001–009, 010_demo_seed.sql and
011–016 verifier mounts through 016_verify_buyer_refunds.sql, then reported successful
initialization. This final result is based on a fresh database, not the earlier
checkpoint's already-initialized database. Existing application and Performance volumes
were neither upgraded nor deleted.

Migration tests cover transactional refusal of missing/invalid historical currency,
valid explicit history, timestamp/state combinations, source/reason pairing, uniqueness,
currency shape and notification types. The unchanged Performance SQL verifier passed
on a normal PAID/CONFIRMED/SOLD/NULL fixture and detected a deliberately non-NULL sold
pointer. It retains Phase 11 assumptions about paid_at and accepted attempts, so it is
not a buyer-refunded-data verifier; new 006_verify_buyer_refunds.sql covers Phase 12.

Buyer integration covers atomic success, concurrent requests, ownership/privacy,
deadline/reuse, pending/requires_action/failed rights preservation, duplicate effective
ownership, wrong seat shape, rollback faults at every terminal write, stale workers
after resale, process crashes, lost responses, expired idempotency history, scan
ambiguity and pagination faults, identity mismatches, webhook wake-only behavior and
HTTP error classification. The live metrics smoke run exercised successful refunds,
local invariant failures and provider identity conflicts.

Detailed build, bootstrap and integration logs, the metrics scrape and the local
validation report remain in ignored backend/build outputs; large logs are not committed.
This document contains the durable validation summary.

Phase 12-1 backend engineering gate: PASSED. Frontend implementation and real Stripe
Sandbox validation are outside Phase 12-1 scope and were not performed. This completion
record does not claim production deployment. Repository closeout uses separate test
and documentation commits; f569cc6 remains intact and no push is performed.
