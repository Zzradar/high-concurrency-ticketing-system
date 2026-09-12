# Phase18 final delivery

Implementation and local hard gates are complete; awaiting independent re-verification. Default mode remains OFF. Formal OFF comparison uses baseline SUT `ed51447154418e05ed9e4c49728f3eb114713db9` and clean after SUT `4dd48c177516caf950103ce3f7751cc0fb056029`. Subsequent delivery changes contain documentation, captured evidence and evidence tests only. OBSERVE/ENFORCED experiments are separate capabilities, never included in OFF improvement ratios.

[Implementation, API/configuration and limits](../../../docs/phase18_admission_overload_control.md), [comparison and eight protocol hashes](comparison.json), [delivery manifest](phase18-delivery.json), [after raw manifest](after/manifest.json), [capability evidence](capabilities/hardening/README.md).

## Frozen identity

| Manifest | SHA-256 |
|---|---|
| Stage0 delivery `manifest.json` (unchanged) | `19f394034d74e027a19e62f3e61f2ab82c9806b542604d666dc24d948640f338` |
| `baseline/manifest.json` (unchanged) | `c0891851436eb997e3414c4d2b6b5525a72c38b7fe635a9cb582e46d77b2e402` |
| `after/manifest.json` | `b1585c91e4cdb4e3aae915dc75552fb8ad2b591dd00fdf02d62af2716a7ac369` |

The new delivery manifest is distinct from both Stage0 manifests; its hash is reported with the delivery commit. Reviewed Stage0 evidence commit remains `fefa8c493e0046f6a4f6e3d60d5d7eeb167cf28e`, never the baseline SUT. The frozen runner retains its historical `STAGE0_VALID` label even in after/; the comparison and delivery manifest identify its actual role without rewriting raw evidence. Image digests, CPU/memory/pid/nofile limits, seed fingerprints, warm-up, request order, repetitions, all eight protocol files and browser identity passed equality gates. Each size has one first Layout, 20 ordinary, 20 conditional and one gzip request; Availability has one cold Snapshot plus 20 Snapshot and 20 Delta samples. No samples were rerun or removed to improve latency.

## OFF measurements

Milliseconds, p50 / p95, frozen nearest-rank statistic:

| Seats | Request | Before | After |
|---:|---|---:|---:|
| 5000 | Layout ordinary | 38.01 / 55.06 | 43.07 / 76.95 |
| 5000 | Layout conditional | 37.14 / 57.33 | 13.78 / 26.22 |
| 5000 | Snapshot | 15.10 / 31.23 | 29.91 / 32.52 |
| 5000 | Delta | 5.51 / 7.87 | 4.47 / 24.74 |
| 10000 | Layout ordinary | 78.18 / 115.96 | 82.63 / 93.26 |
| 10000 | Layout conditional | 76.03 / 92.22 | 14.73 / 26.06 |
| 10000 | Snapshot | 31.10 / 44.94 | 29.56 / 43.75 |
| 10000 | Delta | 4.90 / 24.20 | 14.58 / 23.38 |

All measured read error rates are zero. Results are mixed: 5000-seat ordinary Layout p95 rises 55.06→76.95 ms; 5000-seat Delta p95 rises 7.87→24.74 ms; 10000-seat Delta median rises 4.90→14.58 ms. This is not a claim that every latency improves.

Layout 200 payloads remain byte-identical: 499636 / 1009237 raw bytes, 28696 / 56831 actual gzip bytes. All 20 conditional after requests per size return 304 with zero body. Total trial Layout wire bytes fall 20513772→10521052 and 41435548→21250808. Full Layout SQL falls 42→22 calls, returned rows 210000→110000 / 420000→220000. However, 42 new one-row metadata visibility queries mean **total Layout SQL calls rise 42→64**, with total returned rows 110042 / 220042. These are `pg_stat_statements` returned rows, not physical scans or buffer-page counts; no physical scan reduction is claimed.

Snapshot/Delta payloads increase by 19 bytes for poll hints: 50536→50555 / 536→555 (5000), 102537→102556 / 537→556 (10000). Cold Availability still performs one full PostgreSQL initialization per size; Redis EVAL remains 124 in each Availability stage. The correctness boundary remains PostgreSQL, including DRAFT visibility and final stock ownership.

## Native browser and request timelines

The original Stage0 failure was caused by Playwright CDP default focus emulation keeping tabs visible. The reviewed fixture uses pinned official-channel-derived Edge launch arguments, headed Edge, CDP `noDefaults: true`, exactly **one BrowserContext, one real window and two real tabs**. The second is created by `context.newPage()`; `bringToFront()` performs visible→hidden→visible with hard Page Visibility assertions. No synthetic events, overridden properties, lifecycle freezing or timer suspension are used. Mock is disabled and fixture/API identities are captured.

Edge 152.0.4191.66, Playwright 1.63.0; executable `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`; binary SHA-256 `02aaed8823a4e4bae8f672c620c9356bddebd68651d5bfd141ed9e6576d5f03c`. Full arguments, browser/target/window relationships and per-request start/end/status are in raw browser JSON and the frozen environment file.

| Observation | Baseline | After |
|---|---:|---:|
| Native hidden epoch ms | 1789215545293 | 1789233293829 |
| Native restored epoch ms | 1789215555356 | 1789233303887 |
| Hidden duration ms | 10063 | 10058 |
| Request starts: visible / hidden / restored | 30 / 0 / 6 | 5 / 0 / 3 |
| Total requests / maximum network in-flight | 36 / 2 | 8 / 1 |
| First restored request delay ms | 4 | 19 |
| Restored authoritative Snapshot count | 0 | 1 |

Baseline's restored read was Delta; after performs an authoritative Snapshot. Browser Availability bytes consequently **increase 69296→104440**, despite fewer requests. Redis EVAL falls 108→24 but HGET rises 8304→12512. PG visibility reads fall 36→8; after also records 42 registry event queries (168 rows) and 42 session queries (294 rows). OFF registry refresh has a real PostgreSQL cost.

[Final frozen-source 91-second hidden capability](capabilities/final-hidden/manifest.json) separately passes: trusted native hidden 1789233544405→1789233635456 (91051 ms), zero hidden starts for three longest normal poll periods, maximum in-flight 1 and exactly one authoritative Snapshot on restore. Its changed duration is not mixed into formal A/B.

## Concurrency, resources and correctness

k6: both runs use 8 arrivals/s for 15 seconds, 4 preallocated / max 8 VUs, 121 actual requests, 242/242 checks, zero HTTP errors and zero dropped iterations. Median 2.263→2.280 ms, p95 3.291→3.148 ms. Redis EVAL remains 363 and PG visibility calls 121; after adds eight registry and eight session queries. The eight-user same-seat burst remains one created and seven expected SEAT_CONFLICT, zero infrastructure failures. Raw generic errorRate 0.875 counts expected HTTP 409 and is not an infrastructure error rate.

Both formal runs pass all 65 database invariants (Phase17 13, Phase15 8, Phase16/original 44), checking 15000 Redis seats. The additional after Phase18 verifier reports zero violations with OFF policyRows=0; its isolated database transport selects the actual protocol database `ticketing` and does not alter verifier predicates.

Resource samples: 46 before / 43 after, no collector errors. Observed process VmHWM 237556→225140 KiB, RSS 173976→161604 KiB, threads 155→163; sampled cgroup memory peak 183541760→170967040 bytes and pids 157→165. API limits stay 2 CPUs / 1 GiB / 256 pids; no OOM. Values are observed samples, not an exhaustive peak trace (VmHWM itself is a high-water field). PostgreSQL per-instance pool is four, aggregate eight for the two-API capability test. No max_connections increase was used. Real limit-one overload tests show fast 503, in-flight drain to zero, preserved inventory, admission cooldown and live financial/recovery routes; capability evidence records finite worker, pool, queue and memory limits.

## Tests and closed diagnostics

Release CTest 36/36; frontend Vitest 288/288 and production build; performance Python suite 245/245 including three delivery-only evidence tests (242/242 at source freeze). OFF compatibility suites 57/57; fresh/upgrade migrations Phase15 4, Phase17 8, Phase18 2; Phase17 authenticated/zone regression 5/5 on its separately instrumented build. Policy HTTP 7, admission HTTP 5, Layout HTTP 3, waiting-room Lua 7, token Lua 3 pass. FakeStripe Phase11 11, crash 11, buyer-refund 38 and actual paid-refund verifier positive/negative 3 pass. Native Waiting UI nine scenarios and ADMIN/OCC UI pass. Raw logs and per-suite source bindings are under capabilities/; older capability results keep their original source identities.

The generation defect is CLOSED: mode comparison had allowed Shadow state to survive formal activation. OFF=NONE, OBSERVE=SHADOW and PAUSED/ENFORCED=FORMAL now drive generation rotation. All 16 transitions, audit/transaction rollback, OCC conflict and concurrent updates are covered; old Shadow identities cannot become ADMITTED, read protected Availability or create new inventory operations. `3991e814b54c71e5be0032d26d809e71559ef372` is a historical failed checkpoint, not deployable. Other retained fixture/build diagnostics are CLOSED and excluded from formal evidence. No old migration, frozen baseline or pushed history was changed.

## Limits and reproduction

This is one matched OFF trial on a shared 16-CPU host, **not production SLA**. Other stages' containers were neither modified nor stopped. Preflight observed aggregate Docker CPU about 0.368 core; there is no dedicated CPU affinity and 2–4-second sampling can miss short peaks. Small k6/burst tests do not establish production saturation capacity. Multi-machine deployment, Redis Cluster/Sentinel and universal financial latency under arbitrary authentication floods are untested. Runtime policy propagation is approximately two seconds, stale cutoff 15 seconds, not a globally linearizable switch. Read-only authentication cache can delay disabled-account propagation; strict financial/inventory authentication remains. Extra strict Availability authentication for an existing Checkout remains, and shared authentication PG demand precedes business bulkheads. Fixed configured limits require production sizing; result-class poll metric is a last-hint gauge, not an interval histogram. See the implementation document for all operational bounds and failure behavior.

Reproduce the read-only comparison with `python performance/scripts/phase18_ab_gate.py`. Run `python -m unittest discover -s performance/tests -v` for evidence/contracts. Formal collection used unchanged `protocol/protocol.py` actions setup→start→measure→manifest, fresh prefix `phase18after1`, clean source above and build container `phase18-after-build`. Binary/profile/private environment are excluded from Git. A future binary/protocol/data/limit change invalidates A/B and requires a newly frozen comparable pair. Ordinary push only; no merge, PR, amend, rebase or force push. Dedicated after services on 18182/18183 remain available for independent review, with other stages untouched.
