# Phase 10B-2 高规模特征测试报告

## 结论边界

本报告记录单机 Docker Desktop / WSL 2 环境中的高规模特征测试，不是生产容量承诺。测试分别改变数据基数、活跃认证会话池、请求到达率、业务流量和热点竞争人数；“100 万注册用户”不等于 100 万并发用户，也不等于 100 万 requests/s。

Phase 10B-2 没有修改 PostgreSQL/Redis pool、SQL、索引、Seat Map cache、admission、lock timeout、waiting room、MQ/outbox 或 Backend 实例数。所有候选改进停留在证据与建议层，等待 B-3 设计审查。

本轮最明确的新边界来自 5,000 座位的 Seat Map 响应：60 requests/s 的 15 秒 fixed run 可重复完成，但 100 requests/s 已出现持续 VU 积压和约 10 秒尾延迟；包含 60 Seat Map requests/s 的长窗口混合读在 8 分 46 秒时达到 1,000 个 Seat Map VU、4,940 dropped iterations、Backend 约 9.0 GiB working set，按停止条件中止。数据库连接仅为 6–7，Seat Map SQL 平均执行约 7.69 ms，因此现有证据不支持把它归因于 PostgreSQL pool 或行锁。

## 环境与方法

- SUT 与 k6 均运行在同一 Docker Desktop Linux/WSL 2 VM；Docker 可用内存约 15.41 GiB，k6 为 `grafana/k6:2.2.0`。
- 数据生成使用确定性 profile、单事务 set-based SQL；生成前估算行数与生成文件大小，生成后运行 14 项只读数据库不变量验证。
- arrival-rate workload 同时记录目标到达率、`dropped_iterations`、业务分类、k6/Backend/PostgreSQL/Redis 资源和 PostgreSQL Top SQL。`dropped_iterations` 可能来自 VU 配置或生成器边界，不能自动归因给 SUT。
- “highest tested stable” 只表示本机本次已测且满足到达率、零 dropped/system/unexpected、正确性验证和无持续积压的最高点；“first observed unstable” 是首个观察到的失稳点，不是理论极限。
- 所有延迟均为 k6 聚合 HTTP 请求延迟，除非表格明确写成 flow；多 endpoint workload 不能把它解释为完整业务端到端耗时。

## Data Cardinality

### Profile 语义

| profile | registered users | active auth sessions | events / sessions | physical seats | SessionSeat inventory |
|---|---:|---:|---:|---:|---:|
| baseline | 10,000 | 10,000（兼容旧 `users` 字段） | 2 / 20 | 1,000 | 20,000 |
| scale-100k | 100,000 | 20,000 | 2 / 20 | 5,000 | 100,000 |
| cardinality-1m | 1,000,000 | 5,000 | 2 / 20 | 1,000 | 20,000 |

`activeAuthSessions` 是可配置测试池，不代表生产活跃用户比例。`cardinality-1m` 不生成 100 万 raw token，也不把库存无条件放大到 100 万。

### 生成与存储

| profile | estimated rows | estimated generated files | generation time | actual generated files | database size | notable relation sizes |
|---|---:|---:|---:|---:|---:|---|
| scale-100k（首次装载） | 225,023 | 22,416,384 B | 3.719 s | 17,000,009 B | 112,466,967 B | `session_seats` table 47,865,856 B；两个主要 user unique/PK index 各 4,481,024 B |
| cardinality-1m | 1,026,023 | 5,016,384 B | 25.250 s | 3,770,009 B | 491,944,983 B | `app_users` table 397,844,480 B；PK 与 username unique index 各 81,354,752 B |

百万用户首次生成暴露了 `lpad(text, 6, '0')` 会截断第 1,000,000 个编号并与 `perf-user-100000` 冲突的问题。失败事务完整回滚，修复为动态宽度后重跑成功；该修复独立记录在 `14e80aa`。随后回载 scale-100k 时 PostgreSQL 关系文件保留了曾装载百万行后的空间，因此不能把回载后的 relation size 当成首次 scale-100k 的干净大小。

最终浏览器回归还暴露了 profile 替换只按 `perf-user-*` 清理业务行、却没有覆盖“非 perf 用户引用 perf inventory”的依赖闭包。原事务被外键拒绝并完整回滚；生成器现先建立 Reservation、Order、Checkout scope，再按外键依赖顺序清理其子记录。使用 Playwright 已结算订单作为真实前置状态重跑后，scale-100k 替换成功且 14 项不变量为零。

两种新 profile 生成后均通过 14 项数据库不变量检查。

### 固定 Login rate 下的基数度对比

固定 `20 login/s`、30 秒，不同时改变 Login concurrency：

| registered users | Run ID | success / busy / dropped | HTTP p50 / p95 / p99 ms | username lookup mean SQL ms | shared hit / read |
|---:|---|---:|---:|---:|---:|
| 10,000 | `20260906T054753Z-login-steady-624a` | 601 / 0 / 0 | 88.08 / 102.11 / 107.60 | 0.06795 | 3,080 / 9 |
| 100,000 | `20260906T054843Z-login-steady-824b` | 601 / 0 / 0 | 92.84 / 102.91 / 107.20 | 0.06314 | 3,414 / 0 |
| 1,000,000 | `20260906T054949Z-login-steady-0f8b` | 601 / 0 / 0 | 93.91 / 104.27 / 109.58 | 0.06695 | 3,373 / 9 |

该中等到达率下没有观察到随用户基数增加而显著恶化的 Login 或 username lookup 信号。结论只覆盖索引查找和当前 Hash 配置，不代表百万并发。

## Arrival Rate 与 Business Throughput

### Public Read flash crowd

| load | result | aggregate HTTP p50 / p95 / p99 ms | verdict |
|---|---|---:|---|
| discovery 300→1,000/s | 11,494 success，0 dropped | 0.476 / 0.794 / 1.067 | healthy discovery |
| discovery 1,000→3,000/s | 34,969 success，0 dropped | 0.491 / 0.764 / 1.932 | healthy discovery |
| discovery 3,000→10,000/s | 114,697 success，0 dropped | 0.485 / 44.140 / 58.151 | completed |
| fixed 10,000/s，2,500 VU | 150,001 success，0 dropped | 0.528 / 47.496 / 83.847 | stable repeat 1 |
| fixed 10,000/s，2,500 VU | 149,827 success，174 dropped | 0.540 / 69.948 / 126.296 | generator/VU allocation limited |
| fixed 10,000/s，5,000 VU | 150,000 success，0 dropped | 0.539 / 74.985 / 97.929 | stable confirmation |

本机最高已测并两次成功完成的点为 10,000 public requests/s。一次 2,500-VU 重复运行由 k6 报告 VU 不足；增加预分配 VU 后相同到达率完成，因此把该次标为本地 generator configuration sensitivity，不标为 SUT first unstable。没有继续增加到达率，也没有使用独立外部 generator。

### Seat Map（每响应 5,000 个座位）

| hold density | load | repeats / result | aggregate HTTP p50 / p95 / p99 ms | verdict |
|---:|---:|---|---:|---|
| 0% | fixed 60/s | 901、901 success；0 dropped | 107.10–116.86 / 277.71–332.86 / 338.22–379.14 | highest confirmed stable |
| 90% | fixed 60/s | 900、900 success；0 dropped | 158.47–167.41 / 470.39–474.11 / 489.15–501.83 | highest confirmed stable |
| 0% | fixed 100/s | 1,500 success；0 dropped | 5,334.75 / 9,854.57 / 10,381.40 | first observed unstable |
| 90% | fixed 100/s | 1,500 success；0 dropped | 5,442.04 / 9,771.06 / 10,273.99 | first observed unstable |
| 0% | discovery 150→300/s | 1,373 success；2,375 dropped | 7,846.48 / 8,559.72 / 8,598.19 | stopped |
| 90% | discovery 150→300/s | 1,387 success；2,361 dropped | 7,894.91 / 8,479.73 / 8,506.68 | stopped |

100/s 虽无 HTTP 错误或 dropped，但 VU 持续升到约 630，结束后还需约 10 秒排空，故按持续积压与延迟漂移判为不稳定。90% 临时占用提高了 60/s 延迟，但 0% 与 90% 都在 100/s 失稳，不能把边界仅归因于 hold density。300/s discovery 已满足停止条件，未执行计划中的 600/s。

### Low-conflict Checkout

每个 Buyer 使用唯一 Seat；`buyers/s` 是业务流量，HTTP requests/s 约为其两倍：

| buyers/s | flows / HTTP requests | aggregate HTTP p50 / p95 / p99 ms | result |
|---:|---:|---:|---|
| 40 | 401 / 802 | 5.12 / 7.64 / 9.63 | pass |
| 80 | 801 / 1,602 | 4.99 / 8.41 / 10.46 | pass |
| 160 | 1,600 / 3,200 | 5.54 / 10.26 / 11.38 | pass |

最高已测为 160 buyers/s，未观察到 first unstable；按计划停止，没有为寻找崩溃点继续升压。

### Payment

| workload | business rate | flows / HTTP requests | aggregate HTTP p50 / p95 / p99 ms | correctness |
|---|---:|---:|---:|---|
| Payment Start | 20 starts/s | 201 / 201 | 4.23 / 5.90 / 8.67 | pass |
| Payment Start | 40 starts/s | 400 / 400 | 3.53 / 5.01 / 7.67 | pass |
| Payment Lifecycle | 10 flows/s | 100 / 539 | 1.25 / 5.09 / 6.74 | settled；0 post-settlement processing |
| Payment Lifecycle | 20 flows/s | 201 / 1,066 | 1.15 / 4.45 / 5.92 | settled；0 post-settlement processing |

Lifecycle 保留真实 2–6 秒 callback 和 polling；表中的毫秒值只是 pay-start 与 poll 请求的聚合 HTTP latency，不是端到端支付完成时长。最高已测分别为 40 starts/s 和 20 lifecycle flows/s，均未观察到 first unstable。

### Mixed scale

| workload | multiplier / rates | result | aggregate HTTP p50 / p95 / p99 ms | verdict |
|---|---|---|---:|---|
| mixed read | 2×：public 200/s、auth 200/s、seat 150/s | 7,844 success，408 dropped | 1.04 / 14,853.24 / 16,605.85 | first observed unstable |
| mixed transactional | 2×：checkout 20/s、payment 6/s | 261 flows，728 HTTP | 3.77 / 7.48 / 10.63 | pass |
| mixed transactional | 4×：checkout 40/s、payment 12/s | 520 flows，1,452 HTTP | 3.12 / 7.24 / 10.17 | pass |
| mixed transactional | 8×：checkout 80/s、payment 24/s | 1,042 flows，2,889 HTTP | 2.56 / 7.63 / 9.79 | pass |

Mixed Read 2× 的 Seat Map scenario 达到 1,000 VU 并持续积压，因此按停止条件没有执行 4×/8×。Mixed Transactional 8× 仍通过，未观察到 first unstable。

## Contention Level

### Continuous formal contention

每 group 争用一个唯一 Seat，并要求严格一个 winner：

| contenders / seat | group rate | attempt rate | winner / conflict | aggregate HTTP p95 / p99 ms | result |
|---:|---:|---:|---:|---:|---|
| 4 | 40/s | 160/s | 401 / 1,203 | 5.10 / 6.12 | pass |
| 4 | 80/s | 320/s | 800 / 2,400 | 4.99 / 6.00 | pass |
| 4 | 160/s | 640/s | 1,601 / 4,803 | 5.66 / 9.98 | pass |
| 20 | 10/s | 200/s | 100 / 1,900 | 11.49 / 12.33 | pass |
| 20 | 20/s | 400/s | 200 / 3,800 | 10.89 / 11.76 | pass |
| 20 | 40/s | 800/s | 401 / 7,619 | 10.86 / 12.62 | pass |

所有运行均为 0 dropped/system/unexpected，且每 Seat 恰好一个 winner；数据库验证为 0 violations。最高已测为 4 contenders 下 160 groups/s、20 contenders 下 40 groups/s，没有继续寻找 first unstable。

### Flash hot-seat wave

Wave 是短窗口 burst，不声称纳秒级同步；低速 public/auth control probe 与 wave 并行：

| path | contenders | winner / conflict | start spread | aggregate HTTP p95 / p99 ms |
|---|---:|---:|---:|---:|
| PostgreSQL formal | 100 | 1 / 99 | 9 ms | 32.71 / 34.05 |
| PostgreSQL formal | 500 | 1 / 499 | 61 ms | 114.32 / 121.66 |
| PostgreSQL formal | 1,000 | 1 / 999 | 71 ms | 283.48 / 296.44 |
| Redis temporary hold | 100 | 1 / 99 | 12 ms | 19.23 / 20.26 |
| Redis temporary hold | 500 | 1 / 499 | 62 ms | 84.03 / 90.18 |
| Redis temporary hold | 1,000 | 1 / 999 | 69 ms | 261.85 / 270.92 |

六轮均为 0 dropped/system/unexpected，权威库存验证通过。1,000 人 wave 时，formal 的 control auth/public Backend p95 约 2.2/1.9–3.6 ms，PostgreSQL 连接为 6–7；temporary hold 的 control auth/public p95 约 2.1–2.3/1.8–2.1 ms。采样窗口内没有看到热点竞争显著拖慢无关读请求。

## 30-minute local observation

30 秒 preflight（public 100/s、auth 100/s、Seat Map 60/s）完成 7,803 次请求，0 dropped/system/unexpected，聚合 HTTP p50/p95/p99 为 `1.10/571.08/793.53 ms`。

同参数的 30 分钟 soak-mode 运行没有完成，也不算 endurance pass。运行至 8 分 46 秒时主动中止，保留的 k6 summary 为：

- 139,877 completed HTTP requests，4,940 dropped iterations；
- 聚合 HTTP p50/p95/p99 为 `1.22/23,661.51/32,113.70 ms`；
- Seat Map scenario 达到 `1,000/1,000` VU，public/auth 只需约 0–2 VU；
- Backend working set 从约 234.5 MiB 增至约 9,200 MiB；k6 约 1,637.6 MiB 起步、峰值约 2,976.2 MiB；
- PostgreSQL 连接为 6–7；停止时四个 Backend 数据库连接均 idle，无未授予锁；
- Redis `used_memory` 约 603 MiB，其中普通 client buffer 约 591 MiB，recent max output buffer 约 502 MiB；
- Seat Map SQL 28,711 calls、143,555,000 rows，mean 7.686 ms、6 shared reads；
- 中止后数据库 14 项业务不变量全部通过，但因 1,000 个请求仍在途，可观测性检查按预期失败；只重启 Performance Backend 后 working set 回到约 5.4 MiB、in-flight 回到 0，完整可观测性检查通过。

这些事实说明积压与大响应/异步输出路径相关，但还不足以断言存在传统意义的永久内存泄漏。由于触发 Docker VM 内存风险和 verifier stop condition，本轮没有为了凑满 30 分钟而绕过或降低负载。

## Workload 总结

| workload | Phase 10A stable | B-2 highest tested stable | first observed unstable | generator limit | correctness / primary signal |
|---|---|---|---|---|---|
| Public Read | 300 req/s | 10,000 req/s | 未找到 | 一次 2,500-VU repeat dropped；5,000 VU confirmation pass | 0 errors；本地 VU 配置敏感 |
| Seat Map | 150 req/s（1,000 seats） | 60 req/s（5,000 seats，0%/90%） | 100 req/s；长窗口 60/s 也积压 | 否 | 大 payload、Backend/Redis output buffer 与 VU 积压；非 DB pool 信号 |
| Login cardinality | 15 login/s（B-1 后 40/s） | 20/s @ 1m rows（隔离基数测试） | 未找到 | 否 | index lookup 未随基数显著恶化 |
| Formal contention | 20 groups/s × 4 | 160 groups/s × 4；40 groups/s × 20 | 未找到 | 否 | exact one winner；低连接占用 |
| Formal hot wave | 未执行 | 1,000 contenders | 未找到 | 否 | 1/999，start spread 71 ms |
| Temporary hot wave | 未执行 | 1,000 contenders | 未找到 | 否 | 1/999，start spread 69 ms |
| Checkout | 20 buyers/s | 160 buyers/s | 未找到 | 否 | unique Seat，0 errors |
| Payment Start | 10 starts/s | 40 starts/s | 未找到 | 否 | 0 errors |
| Payment Lifecycle | 5 flows/s | 20 flows/s | 未找到 | 否 | 真实 callback/settlement，0 post-settlement processing |
| Mixed Read | 100/100/75 req/s | 30 秒 preflight 100/100/60 | 2×；长窗口 100/100/60 | Seat Map VU 饱和是并发需求结果 | Seat Map 主导积压 |
| Mixed Transactional | 10 checkout + 3 payment/s | 80 checkout + 24 payment/s | 未找到 | 否 | verifier pass |

## B-3 以后候选（未实施）

当前证据优先指向 Seat Map 路径，而不是数据库 pool：

1. 拆解 5,000-seat 响应的数据库读取、对象构造、Redis hold overlay、JSON 序列化和 socket backpressure 成本，验证大响应在 Backend 与 Redis client buffer 中的占用。
2. 在不改变库存正确性的前提下，评估 Seat Map 静态/动态数据拆分、缓存或受控分页/增量获取；先做设计与对照实验，不直接套用“高并发标配”。
3. 若继续探索 Public Read 超过 10,000/s，应分离 generator 主机并记录双方硬件/网络；本轮不从一次 VU 配置不足推导 SUT 极限。
4. PostgreSQL pool、formal admission/lock timeout、waiting room、MQ/outbox 和多 Backend 当前没有对应瓶颈证据，不进入自动实施。

## 外部资料核对

- [Grafana k6 arrival-rate VU allocation](https://grafana.com/docs/k6/latest/using-k6/scenarios/concepts/arrival-rate-vu-allocation/) 说明 arrival-rate 需要足够 VU；本轮据此把一次 Public Read dropped 判为 VU 配置限制，并结合更大 VU 的确认运行，避免误报 SUT 边界。
- PostgreSQL 官方 [`pg_stat_statements`](https://www.postgresql.org/docs/current/pgstatstatements.html)、[`pg_stat_activity`](https://www.postgresql.org/docs/current/monitoring-stats.html) 和 [`pg_locks`](https://www.postgresql.org/docs/current/monitoring-locks.html) 用于区分 SQL 基数度、连接占用和锁等待。
- 成熟项目 [pretix Scaling Guide](https://docs.pretix.eu/self-hosting/scaling/) 自述：需要事件级锁的场景约 500 orders/min/event、少锁场景曾 benchmark 约 1,500 orders/min/event，并对短时间售出 10k+ tickets 建议专项方案；同页还讨论 rate limiting/queue、web 横向扩展和优先级 worker queue。[pretix locking](https://docs.pretix.eu/dev/development/implementation/locking.html) 解释其正确性优先的锁策略。这些数字来自不同硬件和领域模型，只作分类参考，不是本项目目标。
- 活跃开源项目 [Hi.Events](https://github.com/HiEventsDev/Hi.Events) 的 `misc/k6` 将 public page 与 checkout 分开测量，CreateOrder 使用 per-event advisory transaction lock，并将部分工作放入异步后台任务；本项目只借鉴“读、预订、后台突发分别测量”的方法，不复制其 endpoint 或阈值。
- [aryahmph/concert-ticket](https://github.com/aryahmph/concert-ticket) README 自述在分离的 App/Load VM 上以数千并发获得高吞吐，但当前 loadtest script 与 README 数字不能保证直接复现；这里只支持“高压时分离 generator”的方法论，不用于容量对标。
- [Ticket-Blitz](https://github.com/Abhics8/Ticket-Blitz) 展示 1,000 VU 单资源竞争测试，是项目自证且非成熟基准；本轮仅采用“独立热点 wave + 权威库存验证”的实验结构。

## 可追溯 Run ID

- cardinality：`624a`、`824b`、`0f8b`；
- formal wave：`7910`、`95f4`、`4869`；temporary wave：`fcae`、`883e`、`dd6d`；
- Public Read：`9219`、`b941`、`4120`、`7a6a`、`e606`、`484c`；
- Seat Map：`6a73`、`3f7d`、`688e`、`1531`、`9879`、`6238`、`90dd`、`b300`；
- formal continuous：`07ff`、`d65f`、`7684`、`655e`、`7bbb`、`e73a`；
- Checkout：`7d43`、`6dc7`、`60f9`；Payment：`a019`、`d025`、`e35c`、`2c6c`；
- Mixed：`782e`、`a3f4`、`875a`、`c7ed`、`69bc`；中止的 30 分钟观察：`3d28`。

Raw artifacts 位于 Git ignored 的 `performance/results/<run_id>/`。已完成运行都有 summary、manifest、Prometheus、PostgreSQL、Redis 和日志证据；中止的 `3d28` 没有 runner 最终 manifest，但保留 k6 summary/console 及手工收集的 Prometheus、PostgreSQL、Redis 和环境快照。
