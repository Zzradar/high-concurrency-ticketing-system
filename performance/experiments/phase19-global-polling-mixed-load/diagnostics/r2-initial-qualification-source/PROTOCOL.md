# Phase19 protocol revision 2 (freeze required before formal runs)

Production baseline is commit `2c680e78d532eace9e7f28862e7efb6ef2bdf4fb`.
Test-only commits do not change that production identity. The accepted protection
condition is **event policies OFF; process-local Bulkheads at default limits**.
503 is a separate rejected outcome, never successful throughput. Hotspot still
requires one winner and no 5xx. No backend business semantics are changed.

## Identity and isolation

Use `harness.py setup --private <FRESH_PRIVATE_DIR> --prefix phase19-baseline
--binary <VERIFIED_BASELINE_BINARY>` from `<PHASE19_WORKTREE>`. This creates only
prefix-owned networks, a fresh PostgreSQL volume and containers. Existing resources
are not reset. Record binary SHA256, production Git trees, image IDs/digests and
the complete protocol file hash map. The frontend must be built with
`VITE_USE_MOCK_API=false`. Browser runs hash every served build artifact.

The main fixture has 5000 authenticated users and five 5000-seat sessions, each
with five zones. Private session credentials are mounted read-only into k6 and
never copied into evidence. SharedArray contains the user and writer-seat pools.
Readers use their own generation/cursor. Writers use global VU IDs directly because
k6 does not guarantee scenario allocation order. Writer users start at index 3000,
their two-seat slots stay within the first 800 seats in Zone-0. Precise observer
seats occupy Zone-4 and use another user. Hotspots use a separate session and pool.

## Generator and resource qualification

`calibrate.py --vus N --seconds 60 --out <NEW_PRIVATE_POINT>` uses the same executed
`workload.js` and `policy.mjs`, inert shared credentials, 1000-seat zone Snapshot
bodies and Delta parsing. Both qualification and SUT runs export native lossless
k6 gzip JSONL to the same Windows bind-mounted output mechanism. Each VU idles 15 seconds before work. Qualify 100, 250,
500 and 1000 sequentially; 2000/3000 require a conservative memory check using the
new observed maximum marginal increment. Retain all failed attempts.

k6's initial identity is 2 CPUs, 2 GiB, 256 pids and nofile 16384. The user then
explicitly authorized a separate 2 CPU/4 GiB identity with complete requalification
before considering 2000 VU; select it explicitly with `--generator-memory-gib 4`.
Keep both identities' observations; never combine them as one resource tier.
API remains 2 CPUs/1 GiB;
PostgreSQL and Redis are each 1 CPU/512 MiB; frontend is 0.5 CPU/128 MiB.
Resource thresholds are encoded in `resource_gate.py`: cgroup memory 85%, FD 80%,
WSL available below 25%, sustained swap-out, OOM/restart, or generator CPU above
90% for three samples stop a point. Three consecutive memory samples with both
increments at least 5% of the container limit and the second increment no smaller
than the first also stop immediately, including startup. This defines significant
non-stabilizing growth independently of test outcome. Sampling includes RSS/HWM, cgroup memory,
threads/pids, CPU, FDs, TCP table entries and network bytes. PostgreSQL statement
statistics and Redis INFO are separate observations. CPU is not dedicated to the
test; background workloads and sub-sampling peaks remain limitations.

Never increase limits automatically after a safety stop. A new limit means a new
identity and qualification, not a repair of an invalid result. Estimates for
10000/20000/30000 use both OLS and maximum observed marginal memory, the larger
estimate plus 30%, and an independent SUT/host reserve. Absence of 3000-VU,
CPU/port and host-headroom qualification forbids a SAFE_TO_TRY conclusion.

## Real-SUT load points

`measure.py` rejects an existing output directory and, without `--diagnostic`,
requires an exact `protocol-sha256.json` match. Specify a fresh output per point.
Every point checks SQL invariants, drains Outbox, compares Redis display with
authoritative inventory, and preserves failure outcomes.

| Model | Arguments | Order and duration |
|---|---|---|
| Closed | `--mode closed --vus N --warmup 30 --seconds 120` | 100, 500, 1000, then safe qualified 2000 and 3000 |
| Highest stable Closed | same, `--seconds 600` | after selecting highest valid safe tier |
| Open precheck | `--mode open --read-rate 50 --transitions-rate 5 --warmup 0 --seconds 30` | before L1 |
| Open L1 | read 100, transitions 10, warmup 30, seconds 60 | before L2 |
| Open L2 | read 250, transitions 25, warmup 30, seconds 120 | before L3 |
| Open L3 | read 500, transitions 50, warmup 30, seconds 120 | stop escalation at first invalid/unsafe point |
| Journeys | `--mode journeys --vus 100 --journey-rate 20 --warmup 0 --seconds 250` | nominal 5000, report exact started/completed |
| Hotspot | `--mode hotspot --vus N --warmup 0 --seconds 40` | 100, 500, 1000, preceding correctness/qualification required |

Open uses ten independently paced constant-arrival streams and a distinct writer
scenario. Reader streams have fixed offsets of i * 1000 / read-rate milliseconds.
Reader/writer preallocation defaults to 100/100 with fixed maximum. For L1/L2/L3,
a separate per-VU bootstrap initializes all 200 VUs' own Snapshot and cursor at
50 initializations/s during the 30-second warmup. VU state persists when k6 reuses
the VU for the main scenarios; a missing own cursor fails the point. No cursor is
copied between users. Planned bootstrap count is separate from the unchanged
observe-window target (rate * seconds). The warmup must fit bootstrap plus five
seconds. Cold-start simultaneous admission capacity is outside this warmed open
model; failed r1 startup attempts remain diagnostics. Precheck has no bootstrap
warmup and establishes each own Snapshot at the low 50/s arrival rate.

Initial snapshots and hasMore catch-up are extra HTTP requests, reported
separately from target Delta iterations. k6 may schedule one additional boundary
iteration per arrival stream; retain nominal planned and actual started, business
completed, k6 completed, interrupted and dropped. Missing summary yields unavailable
counts, never invented zero traffic. Errors or dropped iterations abort via k6
thresholds with a one-second evaluation delay; partial observations remain invalid.

Writer mix is 5 abandon, 2 adjust/abandon, 2 confirm/cancel and 1 natural-expiry flow
per ten flows. Nominal state transitions per flow are 2/4/4/2, mean 2.8. Therefore
writer arrival rate is target transitions times 5 per 14 seconds. HTTP write counts
are distinct. TTL is 15 seconds in isolated config; natural expiry is validated
through Availability after TTL, then the still-SELECTING Checkout is abandoned as
separately named cleanup. Production Checkout has no EXPIRED status.

Formal version deltas from PostgreSQL and Redis are compared. Redis Stream
`entries-added`, not current XLEN, survives stream trimming and counts projected
entries. Subtract accepted formal-version increments to derive visible temporary
entries. This is not an audit of every transient ownership mutation. Preserve
per-session/zone increments: Zone-0 is throughput; Zone-4 is the precise observer.
Counters cover the entire point and drain/cleanup, not an inferred observe-only
rate. Per-phase k6 HTTP/flow rates come from actual tagged points.

Journeys contain 75% browse, 15% hold/release, 8% confirm/read/cancel and 2% grouped
hotspot. Exactly one winner is required for each observed group. Wave requests use
a five-second common start target and preserve actual start/end spread. Public,
authenticated and unrelated sentinel probes run alongside the wave. 409 and 429
are explicit expected business outcomes, never successful purchases. Winner
Checkouts are abandoned only after capture, with cleanup and final verifier saved.

## Propagation

Use `--propagation-cycles 1` for precheck and `--propagation-cycles 3` for L2/L3,
with regular independent readers still active. `propagation.py` uses a single
process's `time.perf_counter` for successful write response and first observed
target state. Its own Snapshot/cursor continues across flows; server hints govern
reads. Each 10-second dwell must include two actual planned reads. Since temporary
and formal reservation both display HELD, formal confirm requires a **new Delta
entry after the drained pre-confirm cursor**, not the cached HELD state. Temporary,
formal and final-convergence categories remain distinct; cancel/formal and
cancel/convergence refer to one observation, not two writes. Mismatches are not
converted into latency samples. The resource gate cancels further observer reads
and cleans up its exact active Checkout/Order. Resource collection continues during
the propagation drain after k6 completes.

`layout_probe.py` separately creates a uniquely prefixed 10000-seat fixture and
compares all five Snapshot zones with SQL, then checks independent empty Deltas.
It does not change the 5000-seat capacity datasets.

## Browser A/B

`browser.mjs <PHASE19_WORKTREE> <LOCAL_FRONTEND_BASE> <NEW_PRIVATE_OUTPUT>
<scene> <baseline|after> formal` uses the fixed Edge binary and Playwright version
in `browser-environment.json`. One context, one native window and two tabs are
asserted. Native trusted visibility events and XHR send-time visibility are
recorded; document.hidden, timer APIs and clocks are not replaced. The inherited
Windows occlusion flag prevents another desktop window from hiding both tabs;
the tested boundary is actual tab activation, not minimizing the entire window.

Scenes: events, panel, seat, payment, refund, submitting, logout. Each formal scene
is 60s visible, 91s hidden and 30s restored. Processing is entered five seconds
before hiding so the 15-second recovery deadline crosses hidden time. At restored
10 seconds the controlled fixture reaches terminal state; payment/submitting use
the existing manual authoritative recovery button. Terminal response and subsequent
silence are required. Native background timer throttling remains enabled.

Browser HTTP responses come from versioned `browser-fixture.mjs`, including
5000-seat static geometry and a deterministic 75ms response delay. These tests
isolate frontend lifecycle behavior; they do not claim provider capacity or real
SUT propagation latency. All periodic API families are captured, including
notifications. Exact triggers are known for scripted user actions; other initiations
are explicitly labeled periodic-or-lifecycle, not guessed as a specific timer.
Decoded response bytes are measured; compressed wire bytes are unavailable for
controlled responses and are not invented. Baseline may fail hidden/single-flight
governance; after must satisfy all hard assertions. Setup HTTP calls are retained
and distinguishable from timed phases.

## Evidence and reporting

Raw UTC timestamps are preserved; local timezone is Asia/Shanghai (UTC+8).
Quantiles use nearest rank, with count/p50/p95/p99/max. Response 503 has a separate
latency population and is excluded from successful throughput. No production SLA
is assumed. `report_tables.py` renders the frozen aggregates without reclassifying outcomes.
Raw k6 gzip JSONL and browser profiles remain private; retain SHA256 and byte
length for large raw data. Never promote `--diagnostic` points to formal results.
Freeze or change the complete protocol before baseline; any formal protocol repair
requires a new freeze and a new complete baseline group.

Native gzip output reference: https://grafana.com/docs/k6/latest/results-output/real-time/json/
