# Phase19 完整报告

当前交付状态以 manifest.json 为准；等待独立复验，尚未 merge main。

## 身份与范围

生产基线 `2c680e78d532eace9e7f28862e7efb6ef2bdf4fb`；轮询实现提交 `fed3278`（完整 SHA 见 Git 提交记录）。后端生产源码、配置、旧 migration 均保持准确基线；新增测试提交不能冒充生产版本。重新 Release 构建的二进制 SHA256 仍为 `d9082f28bdf8d5bb8312cee40c9e6a79345b559554d4cbd2a301e742fae0bad5`。

冻结 r2 protocol manifest SHA256：`a5d6470272c1d126e03a78cb3d46f0edddedccc368141ec00e3a16bedd63a295`。容量 baseline manifest SHA256：`7c80f1909f93f3454868135c3dcea4a31c1cbac12261e9e42a23318d6a17aa08`；浏览器 baseline manifest SHA256：`5cd786d576b677954e7e40d1341dec989f72ada919d3e0160ac8b28f6af7ed42`。

所有原始时间为 UTC；本地为 Asia/Shanghai（UTC+8）。本地 Docker/WSL 16 逻辑核，宿主 Intel Core Ultra 7 255H、约 33.9 GB RAM；Docker/WSL 总内存 16548249600 bytes。API 2 CPU/1 GiB，PG、Redis 各 1 CPU/512 MiB，前端 0.5 CPU/128 MiB；用户批准单独 k6 2 CPU/4 GiB 身份后完全重新资格。完整镜像 digest、线程/连接池、FD/pids、版本和生成命令均在 protocol、逐点 identity 与 stage0 中。

**真实保护条件：事件策略 OFF，本地 Bulkhead 保持默认（Availability=16）**。503 不算成功吞吐。5000 用户/有效 Session、5 个场次各 5000 席/5 Zone；不在压力中做登录哈希。独立 10000 席验证不改变主容量数据集。

## 全局轮询 A/B

固定真实 Edge/Playwright，一窗口、一 Context、两原生标签页；每场景 60s visible / 91s hidden / 30s restored。HTTP 使用冻结的 75ms 受控响应，测前端生命周期，不代表真实渠道容量。计数为窗口内受治理 GET，包含明确用户动作和生命周期触发；setup 与其他 API 独立保留。

| 场景 | baseline → after GET | 减少 | hidden 新请求 baseline → after | 解码 body bytes baseline → after |
|---|---:|---:|---:|---:|
| events | 33 → 2 | 93.94% | 13 → 0 | 66 → 4 |
| panel | 32 → 3 | 90.62% | 12 → 0 | 64 → 6 |
| seat | 42 → 11 | 73.81% | 12 → 0 | 114758 → 114696 |
| payment | 61 → 13 | 78.69% | 24 → 0 | 8522 → 3386 |
| refund | 46 → 9 | 80.43% | 12 → 0 | 6491 → 3092 |
| submitting | 53 → 18 | 66.04% | 16 → 0 | 172643 → 171318 |
| logout | 0 → 0 | 两者均零 | 0 → 0 | 0 → 0 |

七场景治理 GET 合计 267 → 56（减少 79.03%）。after 全部通过 hidden 零新读取、单轮询器最大在途≤1、激活最多一次、logout 零认证周期请求、终态静默与无页面错误门禁。after manifest SHA256：`f365fd50495673f718d1c85bdf6b41daebaacd2b2e74d0370c377b3344a7014b`。

| 场景 | 首次恢复读取延迟 ms（业务: baseline → after） |
|---|---|
| events | notifications: 31 → 35 |
| logout |  |
| panel | notifications: 28 → 36 |
| payment | notifications: 21 → 31; payment: 118 → 119; order: 20 → 32 |
| refund | notifications: 35 → 29; order: 32 → 29 |
| seat | notifications: 79 → 43; availability: 36 → 54 |
| submitting | notifications: 36 → 28; availability: 23 → 29; checkout: None → 204; order: 10195 → 10252 |

本轮没有治理端点请求数或解码字节增加；Availability 请求数保持不变。恢复首读存在小幅退化：活动页通知 31→35ms、面板通知 28→36ms、选座 Availability 36→54ms、支付 order 20→32ms。它们是实际观察值，不能因请求减少而省略。

端点明细与每个场景全部 HTTP（含 setup）、可见性、最大在途、解码字节数在 report-tables.json。上述恢复延迟含业务依赖：submitting 的 order 首读约 10 秒发生于脚本终态操作，不是恢复即需读取订单的 SLA。随机退避和原生后台节流保留，因此不将单次时间差概括为固定收益。受控响应没有可靠压缩线流量，未宣称网络压缩字节改善。

| 场景 | 各业务 GET baseline → after |
|---|---|
| events | notifications: 33 → 2 |
| logout |  |
| panel | notifications: 32 → 3 |
| payment | notifications: 35 → 3; order: 14 → 6; payment: 12 → 4 |
| refund | notifications: 36 → 4; order: 10 → 5 |
| seat | availability: 9 → 9; notifications: 33 → 2 |
| submitting | availability: 10 → 10; checkout: 8 → 3; notifications: 34 → 4; order: 1 → 1 |

## Closed Model：actual VUs

| actual VUs / 观察 | 启动=业务完成=k6完成 | 观察 Delta req/s | 成功 HTTP req/s | 状态 |
|---|---:|---:|---:|---|
| closed-100 | 793 | 4.0333 | 4.0333 | 有效 |
| closed-500 | 3959 | 20.0750 | 20.0750 | 有效 |
| closed-1000 | 7928 | 40.1000 | 40.1000 | 有效 |
| closed-2000 | 15827 | 80.2083 | 80.2167 | 有效 |
| closed-2000-10m | 49530 | 72.2300 | 72.2317 | 有效 |

以上每档预热 30 秒，普通观察 120 秒，2000 最高稳定档另观察 600 秒。各 VU 独立用户、Zone、generation/cursor、最大在途 1；零 dropped/interrupted/系统错误，前后 verifier 零违规。只读场次无库存变化，cursorAdvances=0 是真实结果，不能当作混合写入传播证据。10 分钟点实际轮询间隔全点均值约 25.256s、p95 30.003s，HTTP connecting 中位/p95 为 0，符合连接复用；不把 2000 VU 换成 2000 req/s。

**首次观测不稳定为 3000 actual VUs**：发生器资格通过，但 SUT 预热出现 2 次 Snapshot 503，k6 门禁中止（exit99）；6633 started、3631 business completed、3633 k6 completed、3000 interrupted、0 dropped。后两类完成差值包含失败迭代。不是有效容量点，也不是理论容量上限。原始失败和 verifier 保留；未继续更高 SUT 档或 3000 的 10 分钟档。

## Open Model：固定到达的混合读写

| 档位 | 目标 Delta / 状态变化每秒 | 实际 Delta req/s | HTTP write req/s | 启动=完成（含 bootstrap） |
|---|---:|---:|---:|---:|
| open-precheck | 50 / 5 | 50.2667 | 4.2667 | 1562 |
| open-L1 | 100 / 10 | 100.1167 | 8.5667 | 6422 |
| open-L2 | 250 / 25 | 250.0417 | 21.4333 | 31277 |
| open-L3 | 500 / 50 | 500.0500 | 42.8500 | 62349 |

全部正式开放点零 dropped/interrupted/非预期错误。L1/L2/L3 预热单独为 200 个 VU 各自建立 Snapshot/cursor，主观察仍是 constant-arrival-rate。L3 名义 reader=60000，实际=60006；名义 writer=2142.857，实际=2143；bootstrap=200。冻结的边界规则允许每个流最后多一次到达，保留名义计划，不事后改 planned。L3 cursorAdvances=11684，不能用专用 Observer 替代这些真实独立 Reader。

| L3 写流程 | 完成数 | flows/s |
|---|---:|---:|
| hold-abandon | 1073 | 8.9417 |
| hold-adjust-abandon | 428 | 3.5667 |
| hold-confirm-cancel | 428 | 3.5667 |
| natural expiry | 214 | 1.7833 |

目标状态变化 50/s 由 5:2:2:1 流程、每流名义 2/4/4/2 次变化（均值 2.8）换算；实际 HTTP write 为 5142/120=42.85/s。全点（含 drain、清理和专用采样）正式生成/投影均 862，Redis 新增条目 5990，其中推导可见临时条目 5128；Zone-0 吞吐条目 5972，Zone-4 探针 18。这些全点计数不能除以 120 冒充观察窗口实际投影速率，也不是临时所有权变更的完整审计流。自然过期 TTL=15 秒仅隔离配置；过期确认后的 Checkout abandon 是独立清理请求。

## 查询与传播延迟（ms）

| L3 类别 | 样本 | p50 | p95 | p99 | max |
|---|---:|---:|---:|---:|---:|
| HTTP Delta 200 | 60006 | 1.538 | 2.441 | 5.436 | 29.727 |
| temporary | 6 | 2011.992 | 2022.060 | 2022.060 | 2022.060 |
| formal | 6 | 5003.309 | 5007.258 | 5007.258 | 5007.258 |
| convergence | 6 | 5006.390 | 5027.218 | 5027.218 | 5027.218 |

传播以同进程 monotonic 时钟计算“写响应完成→独立 Observer 首次看到目标状态”。不是 HTTP 延迟。临时 hold 保留 10 秒 dwell、至少两个读取机会；confirm 必须观察预确认 cursor 之后的新 Delta，不把缓存 HELD 误算为确认可见。Observer 按服务器 2s/5s 建议读取，因此结果包含轮询等待；不能把约 5 秒解读为内部投影执行耗时。每类仅 6 个样本，nearest-rank p95/p99 等于 max；尾分位不能宣称稳定 SLA。取消的 formal 与 convergence 共用同一观察，不是两笔独立写入。L2/L3 均零失配，后半探针含负载结束后的 drain，详细 UTC/monotonic 时间线保留。

## 累计旅程、热点与布局

累计旅程名义 5000（20/s×250s），实际 5001 started/completed，100 actual VUs 分配。3751 浏览、750 hold/release、400 confirm/read/cancel、100 grouped hotspot；50 组每组 2 人、严格 1 winner。零 dropped/interrupted，原始计数守恒。不能称为 5001 同时在线。

| 单席 wave contenders | winner / 409 | 起发 spread ms | 5xx / 控制探针失败 |
|---|---:|---:|---:|
| 100 | 1 / 99 | 4.542 | 0 / 0 |
| 500 | 1 / 499 | 68.459 | 0 / 0 |
| 1000 | 1 / 999 | 41.962 | 0 / 0 |

1000 人热点冲突 HTTP p50/p95/p99/max=288.832/627.027/640.696/645.286ms；唯一成功 46.870ms。公共、认证和无关场次探针均 200，但每类只有 2 个样本，不能推断长期无干扰。热点请求一波完成，名义 40 秒场景上限不是持续到达率；统计器用 40 秒算出的 25 req/s 不是该波瞬时吞吐。资源采样可能完全错过小于 1 秒的 wave，例如发生器采样 FD 7 不是 1000 用户只需 7 个连接。

10000 席另建场次：5 次完整 Layout 均 200、10000 席一致；5 Zone 各 2000 席 Snapshot 和后续空 Delta 均与 SQL 一致，mismatches=0。该结果不是 10000 VU 容量。

## 资源与瓶颈信号

| L3 角色 | cgroup 峰值 MiB | 主进程 RSS 峰值 MiB | CPU 配额峰值 | FD 峰值 |
|---|---:|---:|---:|---:|
| generator | 131.16 | 152.42 | 26.41% | 207 |
| backend | 82.07 | 75.45 | 23.60% | 686 |
| postgres | 198.91 | 28.52 | 20.67% | 10 |
| redis | 22.89 | 18.64 | 36.71% | 16 |

2000 VU 长时发生器 RSS 峰值约 1033.32 MiB、FD 2007，cgroup 1022.12 MiB；后端 FD 峰值 2462。所有有效容量点无采样 OOM/restart/swap-out 或安全线触发。L3 PostgreSQL 41 个采样中连接最高 6、等待锁 0、deadlock/rollback 增量 0；Redis connected_clients 最高 7，blocked/rejected/evicted/error 增量均 0。pg_stat_statements、Redis INFO/commandstats 与队列/Bulkhead 指标原始序列已保存，未发现能据此确定理论瓶颈的持续饱和。

明确的瓶颈信号是 3000 VU 首次 Snapshot 启动峰值触发本地 Bulkhead 503，而不是发生器 4 GiB 用尽。主进程 RSS/FD 不等于全 cgroup（尤其 PostgreSQL 多进程）；采样 CPU 和瞬时连接存在漏峰。/metrics 由依赖 PromExporter 缓存 5 秒、后台异步刷新，连续 scrape 可交替旧值，不能将其当作精确实时峰值；外部容器采样与 SQL/Redis 观测独立。无生产 P95 SLA、未找到理论最大容量。

## 数万 VU：只估算，未执行

| actual VU 目标 | OLS GiB | 最大边际估计 GiB | 较大者 +30% GiB | 决定 |
|---|---:|---:|---:|---|
| 10000 | 4.74 | 5.02 | 6.53 | UNSAFE，未执行 |
| 20000 | 9.43 | 10.13 | 13.16 | UNSAFE，未执行 |
| 30000 | 14.12 | 15.23 | 19.80 | UNSAFE，未执行 |

还需独立保留 4 GiB SUT/系统余量；三档均超已批准 4 GiB 发生器 85% 安全线，宿主可用约 6.42 GiB 未满足 25% 余量，nofile=16384 也不能满足两倍预测峰值。3000 SUT 已不稳定。没有提高限额、降级为 online-equivalent 后宣称数万通过。旧 2 GiB 与旧 4 GiB 资格/预测保留，当前估算只用 r2 完整重新资格样本。

## 独立过载能力与金融回归

ENFORCED 与主容量分开。真实 Redis Token Bucket 账号/事件/操作维度与正 Retry-After 由最终回归验证；双 API/双调度器重复加入 16 次只产生一个排队位置，9 个唯一位置减 5 次离开为 4，maxActiveUsers=1 观察峰值 1。

32 请求饱和验证：16 次 200、16 次 SYSTEM_OVERLOADED 503，Availability 在途峰值 16，解除压力后 0；既有订单/Checkout 恢复 200，随后 20 次读取 200。独立新测试两轮购票洪峰 606/600 次，既有 Checkout/Order/Payment/Refund 恢复读取全部 200；支付真实内部 PROCESSING→PAID，退款 PROCESSING→SUCCEEDED，最后释放座位、金额一致、Outbox 排空、Redis=SQL。请求与恢复时间线见 overload-separated/recovery。

以上使用本地 Fake Provider 保持真实内部幂等、事务与 worker。没有向真实 Stripe 或 Sandbox 压测，也没有新增真实渠道实测；既有 Stripe 请求构造、验签、重复/迟到成功、分页与退款对账逻辑由现有 Fake 集成回归覆盖。不代表 Stripe 吞吐或生产支付 SLA。

## 最终回归

| 测试 | 实际通过数 |
|---|---:|
| phase18_admission_http_test | 5 |
| phase18_off_regression | 57 |
| phase18_policy_http_test | 7 |
| phase18_public_contract_test | 2 |
| phase18_schema_test | 2 |
| phase18_token_bucket_test | 3 |
| phase18_waiting_room_test | 7 |
| phase18_traffic_http_test | 2 |
| phase18_availability_fault_test | 1 |
| phase18_checkout_crash_test | 1 |
| phase18_inventory_fault_test | 1 |
| phase18_layout_http_test | 3 |
| phase18_layout_resolution_http_test | 1 |
| phase18_layout_revision_http_test | 7 |
| phase18_metrics_http_test | 1 |
| phase18_verifier_test | 1 |
| phase11_crash_window_integration_test | 11 |
| phase11_stripe_integration_test | 11 |
| phase12_buyer_refund_integration_test | 38 |
| phase18_multi_instance_test | 1 |
| phase18_refund_verifier_fixture | 3 |
| ctest | 36 |
| vitest | 328 |
| performance_python | 321 |
| protocol_node | 2 |
| phase19_overload_recovery_test | 1 |

Release C++20、HTTP frontend production build 通过；Vitest 为 42 个文件。前后各 7 正式浏览器场景另计；完整日志与源文件哈希见 final-regressions/manifest.json。未扩大为生产 Stripe 实测。

## 失败保留、协议修复与限制

- 初期 Stage0 的缺测试上下文、统计扩展、旧容器名与资格采样失败保留在 diagnostics，修正夹具后完整门禁通过。
- r1 L2 启动期 64 次 503，Windows 未压缩原始 JSONL 写回阻塞导致缺 summary。缺 summary 的计数不能解释为零实际流量。整组 r1 原字节移存，r2 重新资格、重新冻结、重跑完整 baseline，不与 r1 拼接。
- r2 候选的读流偏移、ramping 计数不守恒、初始同时 Snapshot 资格触发三点内存增长门禁都保留。最终采用与真实 closed 一致的 30 秒启动 spread 和原生 gzip 指标导出，未放宽错误/内存门禁。
- 前端提案阶段的旧固定周期测试、丢失 Admission 登录跳转和身份/激活边界修正有日志；最终实际工作树 328 项通过。Git 补丁只有换行差异，完整规范化文本哈希核验留存。
- 最终 Traffic 回归最初峰值 1，首轮等待后第二次 scrape 又得 0；查明 5 秒导出缓存后断言同一收敛样本，从重启 API 通过，未更改生产 Bulkhead 或任何后端业务语义。
- 单机、固定种子、有限观察窗与少量传播/控制样本；没有后端优化 A/B，因此不声称后端吞吐提升。闭合只读、开放混合、累计旅程、热点和保护能力不能相加。

## 交付、复跑与追溯

实现分类：前端 policy/SingleFlight、通知/Order/SeatSelection/auth；测试与独立夹具；Phase19 原始聚合/时间线；设计/README/简历证据。旧 Phase16/17/18 证据树和 migration 原字节保持。

从 protocol/PROTOCOL.md 复跑命令开始，每点必须新的私有输出目录。正式身份、命令参数在 identity.json；大体积 native k6 gzip JSONL 在每点 archive-manifest.json 记录 `<PRIVATE_TEMP>/phase19-r2-baseline-<point>/k6-points.jsonl.gz`、SHA256 与 bytes。用户 Session、Cookie、CSRF、provider secret 不提交。

最终 manifest 绑定 protocol、baseline、after、回归与生产 tree；EVIDENCE_SHA256.json 索引全部 Phase19 文件（排除自身和 __pycache__）。`phase19_delivery_audit.py` 只读核对字节与门禁。Git 最终 SHA/全部提交记录及普通 push 同步状态随交付返回；仅清理本阶段明确名称容器/网络，证据与卷保留。不创建 PR、不合并 main。

最终日志脱敏补充：12 个测试日志的正斜杠临时路径或 Python 安装路径替换为占位符，原私有日志与 SHA 保留，路径变换映射见 diagnostics/log-path-redaction.json。未修改指标值、结果或退役 r1 正式证据。
