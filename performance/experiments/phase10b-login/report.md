# Phase 10B-1 Login / Argon2 容量实验

## 范围与判定方法

本轮只调整 `PasswordHashExecutor` 工作线程数和队列容量，Argon2id 仍为 `m=65536 KiB, t=2, p=1`。每个点使用 k6 `constant-arrival-rate`、30 秒、220 个预分配 VU；下表的 Rate 是 Login iteration/s，也是 HTTP request/s。所有有效运行均为 `dropped=0` 且 `system_error=unexpected=0`。

“confirmed stable” 还要求目标到达率、无 `AUTH_BUSY`、Hash 队列不持续增长且运行后可回落、k6 未先饱和。“first observed unstable” 指本机当次实验首个观察到容量拒绝的点，不是生产 SLO 或理论上限。

## 内部可观测性

新增的可选 observer 使 Executor 仍可独立测试，Performance Metrics 负责映射下列低基数度指标：

- `ticketing_password_hash_queue_depth`：当前等待任务数；
- `ticketing_password_hash_active_workers`：正在执行 Hash 的 worker 数；
- `ticketing_password_hash_submissions_total{outcome="accepted|rejected"}`：接受与容量拒绝；
- `ticketing_password_hash_queue_wait_seconds`：从入队到开始执行；
- `ticketing_password_hash_execution_seconds`：Argon2 本身的执行时间，不是整个 HTTP latency。

指标不含 username、userId、password、hash、token、requestId 或 threadId label。独立 C++ unit test 覆盖 accepted/rejected、queue/active gauge、wait/execution 和真实 Hash verify。

## Control reproduction

| workers | queue | rate | repeat | success | AUTH_BUSY | HTTP p50/p95/p99 ms | max queue | end sample queue |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 64 | 15 | 1 | 451 | 0 | 100.3 / 105.7 / 110.1 | 0 | 0 |
| 2 | 64 | 15 | 2 | 450 | 0 | 100.3 / 105.8 / 110.2 | 0 | 0 |
| 2 | 64 | 30 | 1 | 681 | 220 | 3146.7 / 3222.8 / 3231.4 | 64 | 63 |
| 2 | 64 | 30 | 2 | 680 | 221 | 3158.1 / 3227.0 / 3240.9 | 63 | 63 |

15/s 的稳定行为和 30/s 的过载都重现 Phase10A，没有观察到新指标引起的明显偏移。典型 2-worker 15/s 的 Hash queue-wait p50/p95/p99 为 `0.5/0.9/1.0 ms`，execution 为 `77.8/176.4/235.3 ms`；30/s 时 queue-wait 上升到秒级，而 execution p95 仍约 192 ms，证明等待和 Hash 执行已分离测量。

## Worker sweep（queue=64）

| workers | 15/s | 20/s | 25/s | 30/s | discovery |
|---:|---|---|---|---|---|
| 2 | 451/0, p95 105.7 | 601/0, p95 104.3 | 693/58, p95 3187.1 | 680–681/220–221, p95 3222.8–3227.0 | 未继续升压 |
| 3 | 451/0, p95 103.3 | 600/0, p95 103.5 | 751/0, p95 106.9 | 901/0, p95 141.5 | 未高于 30/s，4-worker 已显示更大余量 |
| 4 | 451/0, p95 103.6 | 600/0, p95 103.1 | 751/0, p95 104.8 | 901/0, p95 106.1 | 35/s: 1050/0, p95 109.8；40/s: 1201/0, p95 194.9；45/s: 1263/87, p95 1705.3 |

单元格式为 `success/AUTH_BUSY` 和 HTTP p95 ms。worker=4、queue=64 的 40/s 候选点另外重复两次：

| run | success | AUTH_BUSY | p50/p95/p99 ms | max/end queue | Hash wait p50/p95/p99 ms | Hash exec p50/p95/p99 ms |
|---|---:|---:|---:|---:|---:|---:|
| `20260906T051358Z-login-steady-da7e` | 1201 | 0 | 109.5 / 131.2 / 142.8 | 1 / 0 | 7.1 / 44.8 / 251.5 | 87.9 / 227.9 / 245.6 |
| `20260906T051445Z-login-steady-b6f4` | 1200 | 0 | 154.5 / 207.4 / 221.1 | 3 / 1 | 43.3 / 133.1 / 226.6 | 108.6 / 235.9 / 247.2 |

两次均达到目标、无 dropped/拒绝/系统错误，队列没有持续单调增长。第二次末次 scrape 仍为 1，随后实时 gauge 回到 0。Backend CPU 峰值约 1.85/2.79 cores，k6 CPU 峰值仅 0.03/0.05 core，没有 generator-first 限制证据。

## Queue sweep（workers=4）

| queue | 40/s success/busy | 40/s p95/p99 ms | max queue | 45/s success/busy | 45/s p95/p99 ms | max queue |
|---:|---:|---:|---:|---:|---:|---:|
| 16 | 1200 / 0 | 374.3 / 389.2 | 8 | 1219 / 131 | 504.5 / 511.6 | 15 |
| 32 | 1201 / 0 | 131.8 / 143.7 | 0 | 1217 / 134 | 917.1 / 926.1 | 32 |
| 64 | 1200–1201 / 0 | 131.2–207.4 / 142.8–221.1 | 1–3 | 1263 / 87 | 1705.3 / 1725.8 | 62 |

三种队列在 45/s 都出现 `AUTH_BUSY`，说明 queue 不是 Hash throughput knob。更大队列只允许更多请求等待，并改变延迟/拒绝时机。在没有产品等待 SLO 的前提下，保留 64，不为了形成参数变更而强行缩短队列。

## 结论与 Apply 回归

正式配置选择 `password_hash_workers=4`、`password_hash_queue_capacity=64`，四份 runtime/performance 配置同步，Argon2id 参数不变。调整后的最高已测 confirmed stable 为 40 login/s，first observed unstable 为 45 login/s。与 2-worker 相比，无容量拒绝的已测到达率从 20/s 提升到 40/s；这不是宣称理论容量恰好翻倍。

Apply 后真实 Docker rebuild 完成 CMake configure、GNU C++20 编译和链接，CTest `20/20` 通过；Performance Stack 全部 healthy，`verify_observability.py` 通过。Public Read、Warm Auth Read 和 Checkout smoke 均为 3/3 success；正式配置下 40/s 为 1200/1200 success，45/s 为 1233 success + 118 `AUTH_BUSY`，两者都无 dropped/system/unexpected。紧接镜像全量编译后的 40/s apply run p95 上升到 809.3 ms，虽未拒绝，但显示 40/s 的本机余量有限；因此后续不应把 40/s 当成 SLO。

一次使用了不匹配基线 Hash 的测试密码，run `20260906T050929Z-login-steady-d5ed` 的 601 次响应全部被分类为 unexpected。该运行是操作输入错误，未进入容量矩阵，不用于任何容量结论。

## 外部资料核对

- [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html) 与 [RFC 9106](https://www.rfc-editor.org/rfc/rfc9106.html) 支持继续使用 Argon2id 及内存困难参数；本轮因此只改变并发 worker，没有为吞吐降低 m/t/p。
- [libsodium password hashing guidance](https://doc.libsodium.org/password_hashing) 明确密码 Hash 参数是 CPU/内存资源预算；本轮用 worker 上限和有界队列控制同时消耗，并分开测量 wait/execution。
- [Grafana k6 arrival-rate VU allocation](https://grafana.com/docs/k6/latest/using-k6/scenarios/concepts/arrival-rate-vu-allocation/) 说明 arrival-rate 需要足够的预分配 VU，不足时会产生 `dropped_iterations`；本轮所有有效运行均为 0，并同时核对 k6 CPU，避免把生成器限制归因给 SUT。
- [PostgreSQL `pg_stat_statements`](https://www.postgresql.org/docs/current/pgstatstatements.html)、[`pg_stat_activity`](https://www.postgresql.org/docs/current/monitoring-stats.html) 和 [`pg_locks`](https://www.postgresql.org/docs/current/monitoring-locks.html) 是后续 B-2 区分 SQL 基数度、连接占用与锁等待的一手依据。
- 成熟项目 [pretix Scaling Guide](https://docs.pretix.eu/self-hosting/scaling/) 将 correctness 置于吞吐之前，公开说明事件级锁场景约 500 orders/min/event、少锁场景曾 benchmark 约 1500 orders/min/event，并建议 10k+ tickets 短时售罄时提前做专项方案。这些是 pretix 自述且模型/硬件不同，不是本项目的目标数字。同一指南还展示 web 横向扩展和优先级 worker queue，本轮仅作后续设计参考，未实施。
- [Hi.Events](https://github.com/HiEventsDev/Hi.Events/tree/develop/misc/k6) 是活跃的开源售票项目，其 `misc/k6` 把 public event page 和 checkout flow 分开；本项目沿用这种“读与交易分离测量”方法，不复制 endpoint、threshold 或数据模型。其 CreateOrder 的 per-event advisory transaction lock 与异步后台任务只用于对照 B-2 热点与后台突发的分类方法。
- [Alighieri](https://github.com/wiresock/alighieri) 是新近开源 Rust 项目，其 Argon2id 验证和 semaphore/有界验证资源提供了“昂贵验证必须有界”的对照；它不是售票系统，也不是本轮数值的来源。对“Janus Argon2 bounded queue”的资料指称未提供唯一项目 URL，搜索到多个无关同名项目，因无法确定来源而没有把它当作设计证据。
- [aryahmph/concert-ticket](https://github.com/aryahmph/concert-ticket) README 自述在分离的 16-core App VM 和 8-core/32GB Load VM 上以 8500 concurrent users 获得约 9200 req/s。这是低活跃项目的自述，当前 `loadtest/main.js` 与 README 数值/场景不能保证直接复现，只支持“高压时分离 SUT 与 generator”的方法，不用于本项目容量对标。
- [Ticket-Blitz k6 race test](https://github.com/Abhics8/Ticket-Blitz) 公开展示单库存热点竞争的 k6 测试方法，但是项目自证、不是成熟基准。B-2 只借鉴“独立热点 wave + 权威库存校验”，不借用它的吞吐结论。

## 本轮未做

未改 PostgreSQL/Redis pool，未改 SQL/索引，未加 cache、admission、lock timeout、waiting room、MQ/outbox 或多 Backend。这些都等待 B-2 证据，不从 B-1 自动推导实施。
