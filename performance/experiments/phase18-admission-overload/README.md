**Correction in progress:** the former final After SUT `4dd48c1` and its after/ results are invalidated by the ETag defect. All old raw bytes are preserved. [After status](AFTER_STATUS.json) is authoritative; a new complete after-v2 is required. Earlier completion statements below are historical.

**Phase18 delivery complete; awaiting independent re-verification.** See [final report](FINAL_REPORT.md), [after evidence](after/README.md), and [delivery manifest](phase18-delivery.json). The text below is the historical Stage0 report; statements about absent after evidence or test counts describe that earlier delivery only. Both Stage0 manifests and baseline raw evidence remain unchanged.

# Phase18 Stage0: exact baseline and browser fixture

Status: Stage0 complete; Phase18 business changes have not started. Only `baseline/` is eligible for a later A/B comparison. Everything in `diagnostics/`, and the previous external checkpoint, is excluded.

## Source and protocol

SUT: `ed51447154418e05ed9e4c49728f3eb114713db9`, clean, branch `phase18/admission-overload-control`, worktree `D:\Documents\vscode\high-concurrency-ticketing-system-phase18`. Both main and origin/main were checked after fetch. Production sources, migrations, and repository configurations were unchanged during measurement.

The protocol was developed outside the repository, frozen before fresh `phase18v3` data setup, and run there. `baseline/source.json` records the exact SHA-256 of every protocol file. Delivery copies must match those bytes; `.gitattributes` prevents newline conversion. `manifest.json` records environment, source, data, browser, scripts, images, limits, raw evidence indexes, and build provenance. A future after run must use the same protocol and browser binary and freshly seeded data. Container/profile directory names may differ; ports, network aliases, cgroup limits, config bytes, sequence, data, and measurement parameters must match.

Fresh Release C++20 build: isolated `phase18v2-build`, pinned toolchain image, `/sut/backend` source, `/phase18-build` output, `-DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=ON -DBUILD_SHARED_LIBS=OFF -DTICKETING_FETCH_DROGON=ON -DFETCHCONTENT_SOURCE_DIR_DROGON=/src/build/_deps/drogon-src`, parallel 2. CTest 34/34. The same newly built binary was used for the v3 measurement; no performance observations from the abandoned v2 setup were reused. Production frontend was rebuilt after `npm ci --no-audit --no-fund`, with `VITE_USE_MOCK_API=false`; Vitest 265/265. Measurement-statistics tests 4/4.

Runtime config derives from the tracked Phase14 observation config so server flow high-water and transaction acquisition histograms are available. Only isolated PostgreSQL credentials, application_name, and this fixture's allowed frontend Origin were changed in the external runtime config. PostgreSQL pool stays 4; Redis pools remain 2 + 2. No repo config changed. Actual PG snapshots show four API connections. Two CPUs limit the API; the auto thread setting still sees the host's 16 logical CPUs. This is recorded rather than described as capacity tuning.

## Browser root cause and topology

Old runner: Playwright 1.63.0, Edge channel `msedge`, headed, `chromium.launch` then one nonpersistent `browser.newContext`, then two `context.newPage` pages. It did not record real window IDs or browser build at run time. Edge currently identifies as 152.0.4191.66; that current observation is not retroactive proof of the previous run's exact version. The previous runner called `cover.bringToFront()` and immediately sampled `document.hidden` once; no visibility event recorder or bounded state wait existed. Its 40 post-JSON-response timestamps split 30 / 5 / 5 around attempted switch/restore markers. Request start/end and actual historical window topology cannot be reconstructed.

The new minimal `launchPersistentContext` probe used the official channel, headed mode, a fixed dedicated profile, one Context and two pages in the same verified window. Waiting for real hidden still failed. Local Playwright `coreBundle.js` enables `Emulation.setFocusEmulationEnabled(true)` on its main CDP session. Chromium's handler retains a capturer handle with `stay_hidden=false` in that session. Sending false on a separately attached CDP session cannot release the original session's handle. The failed new-session disable experiment is retained.

The validated fix launches the exact executable and arguments resolved by the official Edge channel, changing only pipe transport to a loopback ephemeral CDP port, and connects with the official `connectOverCDP({noDefaults:true})`. This prevents the default focus override on the original connection. It does not modify document properties, synthesize events, freeze lifecycle, pause timers, or treat focus/blur as visibility. No arbitrary flags were added. Playwright source/package files were not patched. The executable path is `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`; exact hash, version, full arguments and launch provenance are recorded.

Topology: one headed Edge process/profile, one BrowserContext, one real window, two tabs. The initial page is the seat page; `context.newPage()` creates the neutral tab. CDP target/window reads verify identical `windowId`. Native `bringToFront` transitions passed three cycles on static pages. The formal run injects the recorder before navigation and records trusted visibilitychange events, focus/blur, Date.now, performance.now, and visibility-state performance entries. Browser telemetry includes start, headers, finish, status, bytes, and in-flight high-water for every Availability request.

Sources accessed 2026-09-12: [Playwright noDefaults API](https://playwright.dev/docs/api/class-browsertype#browser-type-connect-over-cdp), [Chromium EmulationHandler implementation](https://raw.githubusercontent.com/chromium/chromium/main/content/browser/devtools/protocol/emulation_handler.cc), [CDP window identity](https://chromedevtools.github.io/devtools-protocol/tot/Browser/#method-getWindowForTarget). The session-handle explanation is supported by source and the successful noDefaults control; it is not an inference from focus/blur alone.

Bundled Chromium failure was separately traced to native Windows error 14001 and SideBySide event 33: assembly 153.0.8010.12 could not be resolved in the existing installation. A separate official Playwright revision 1243 download could launch Chrome/153.0.8010.12 successfully (same chrome.exe hash); its default Playwright visibility probe still exhibited the focus-override issue. No OS policy or existing installation was changed. Chromium diagnostics are not part of the formal Edge baseline, and no Edge/Chromium A/B mixing is allowed.

## Formal results

All rows are a single predeclared trial. Cold means first fixture request on a fresh API, not a flushed host page cache. Quantiles use nearest rank; raw samples are retained.

| Seats | Layout ordinary p50 / p95 ms | Conditional p50 / p95 ms | Raw bytes | gzip wire bytes | Snapshot p50 / p95 ms | Empty Delta p50 / p95 ms |
|---:|---:|---:|---:|---:|---:|---:|
| 5000 | 38.01 / 55.06 | 37.14 / 57.33 | 499636 | 28696 | 15.10 / 31.23 | 5.51 / 7.87 |
| 10000 | 78.18 / 115.96 | 76.03 / 92.22 | 1009237 | 56831 | 31.10 / 44.94 | 4.90 / 24.20 |

Each size uses 1 first layout GET, 20 ordinary GETs, 20 conditional probes, and 1 actual gzip request. All 42 per size return 200; no baseline ETag or 304 is invented. First layout latency: 61.07 / 102.72 ms. Full-layout SQL: 42 calls / 210000 rows at 5000 seats; 42 / 420000 at 10000. JSON hash is stable across plain requests. Offline gzip bytes are explicitly separate from actual wire gzip. Snapshot/Delta cover Zone 0, respectively 1000 / 2000 members, plus one cold snapshot and twenty samples of each mode per size.

Browser native timeline: hidden at epoch-ms 1789215545293; restored at 1789215555356. The hidden interval is 10063 ms. Request starts classify 30 visible / 0 hidden / 6 restored, using native event timestamps rather than later assertion-observation times. There are 36 HTTP 200 responses: 1 snapshot and 35 empty deltas; no error. First authoritative request starts 4 ms after the native restored event. PG visibility SELECT increases by 36, preserving DRAFT isolation. Frontend responses carry `X-Phase18-Fixture: stage0-v2`; isolated nginx logs identify the new v3 API upstream, not an old service. The production build explicitly disables Mock.

Network-observed maximum Availability in-flight is **2**, from about 1 ms overlap between two same-Zone requests on restore. This raw baseline fact is retained. Server seat_read high-water is 1; these two observability boundaries are distinct and are not substituted for each other. The baseline is not failed for lacking an after-phase property; the after gate must independently establish single in-flight behavior.

k6: constant arrival 8/s for 15 seconds, 4 preallocated / maximum 8 VUs, 121 actual HTTP requests (including the scheduling boundary), 242/242 checks, zero failed HTTP requests and zero dropped iterations; p50 2.263 ms, p95 3.291 ms. Offered settings and actual counts must both be compared in a later after run; a different actual count must be disclosed and cannot be silently treated as an identical sample set.

Eight-user single-seat burst: 1 created, 7 SEAT_CONFLICT, zero timeout/server errors. The generic raw summary's `errorRate=0.875` means HTTP >=400, not an infrastructure failure rate. Reservation server in-flight high-water is 8. Transaction acquisition reports 8 successes, zero timeout/error, 0.000165 s total acquisition time. This is a small bounded correctness experiment, not saturation or production capacity proof.

Database/Redis verifier: Phase17 13 checks, Phase15 8 checks, Phase16/original 44 checks, all zero violations; 15000 Redis seats checked. There are 46 process/container/PG-wait resource samples, with no collector error. Raw per-stage metrics and query/call/row deltas remain the authority.

## Reproduction and limitations

`protocol/protocol.py` takes `setup`, `start`, `measure`, `manifest`, `stop`, plus `--root`, `--out`, `--prefix`, and `--build-container`. Use a fresh output, prefix, browser profile, and newly built SUT. Never point it at historical containers. Run `python -m unittest discover -s protocol -p 'test_*.py' -v` before setup. Then run the actions in order with the same arguments. The source-script hash guard rejects a changed protocol after setup. The runner must finish while the SUT remains clean; evidence is copied afterward. A/B scripts must remain identical, or both sides must be recollected.

This run shares a host with pre-existing historical containers. They were neither stopped nor modified. Each new service has independent cgroup limits and networking, but there is no dedicated CPU affinity. No uncontrolled host failure was observed, yet measurements cannot establish a dedicated-host SLA. Resource sampling is approximately 2–4 seconds and may miss short resource peaks; server request high-water is exact within its instrumentation boundary. PG observer queries are present in raw statistics and must be separated from business query signatures. Transaction timing covers existing instrumented paths, not every possible database wait. No global cache flush, large-load qualification, before/after improvement ratio, or Phase18 admission effect is claimed.

The real-browser recorder uses public CDP noDefaults behavior and a pinned browser executable; if Edge updates, binary/version guards fail and both sides must use a newly fixed environment. Browser profiles, cookies, binary/build directories and credentials are excluded from Git. Raw JSON captures only selected HTTP metadata, never Cookie/Authorization. Existing checkpoint and failed protocol attempts remain diagnostics. `after/` is intentionally empty because no Phase18 business implementation has been measured.

## Delivery validation

Complete performance Python suite: 240/240 passed, including the seven new evidence gates. Command: python -m unittest discover -s performance/tests -v. Protocol statistics suite: 4/4 passed. Frontend Vitest: 265/265 passed. Release CTest: 34/34 passed. Diagnostics failures are retained negative/preflight results, not failed formal gates. Stage0 measured no Phase18 business changes; after evidence is absent. All v2/v3 containers created for this continuation were stopped; data, logs, and images were retained. Main worktree remains clean. Only performance evidence and its tests are included in this commit.

Raw terminal output contains original CMake/k6 trailing padding. Scoped Git attributes preserve CRLF and permit that captured log padding so its original SHA-256 remains verifiable; source and JSON whitespace checks remain enabled. No raw output was trimmed to make a check pass.
