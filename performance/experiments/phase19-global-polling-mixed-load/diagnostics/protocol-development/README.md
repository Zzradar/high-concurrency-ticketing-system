# Unfrozen protocol development

These points validate tools against the unchanged Phase18 production binary.
They are **not formal capacity results or a browser A/B**. No protocol freeze
has occurred and no frontend production changes have been made.

The user accepted the accurate protection condition: event policies OFF with
process-local Bulkheads at their existing defaults. HTTP 503 is never counted
as successful throughput.

| Point | Result | Explanation |
|---|---|---|
| open-smoke-r1 | invalid | k6 global VU allocation is not ordered by scenario; writer mapping and Redis INFO text parsing were incorrect |
| open-smoke-r2 | invalid | Checkout has no EXPIRED state; temporary ownership expiry must be checked through Availability |
| open-smoke-r3 | diagnostic passed | 528 started/completed; zero dropped/interrupted; 30 initialized VUs; verifiers passed |
| hotspot-smoke-100-r1 | diagnostic passed | 100 requests, exactly one winner, 99 explicit conflicts; control probes passed; winner abandoned and verifier passed |
| propagation-smoke-r1 | invalid | formal reservation also displays HELD, not RESERVED |
| propagation-smoke-r2 | diagnostic passed | six observations; formal confirm requires a new Delta entry after the pre-confirm cursor, not cached HELD |

Temporary holds expire through Redis TTL and the existing read-model cleanup
path. The checkout is subsequently abandoned for fixture cleanup; this cleanup
request is separately named and is not another inventory transition.

Propagation uses one process's `time.perf_counter`. A 10-second dwell covers
at least two actual planned reads. Cancel's formal and convergence categories
describe the same observation and must not be added as independent writes.

Raw k6 point files remain at `<PRIVATE_TEMP>/<point>/k6-points.jsonl`; each
result records its SHA256 and byte length. Raw authentication fixture files
are private and are not included. UTC timestamps are original; local display
timezone is Asia/Shanghai (UTC+8).

Final-workload generator qualification, protocol freeze, formal capacity,
5000 journeys, 1000 contenders and browser A/B are still pending.
