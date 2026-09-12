# Phase15 活动售票时间窗口实施记录

## 集成与基线

本轮正式输入为 `Phase15_活动售票时间窗口_Codex实施提示.txt`。按附件授权，先把已完成 Phase16 合并到 main，再在原独立分支实施 Phase15。

- 合并前 main：`89b888a0a8c833a4e85b013289ec678385de1e0d`。
- 合并前 Phase16：`ee01151f441ae3488258eabfcb817fe999d534d3`。
- merge commit / Phase15 开始点：`d1d1fd7170553df86c73cfa2313f09d57fa718a6`，已普通 push 到 origin/main。
- 独立工作树 `high-concurrency-ticketing-system-phase16`，分支 `phase16/availability-read-model`，开始时 clean，ff 到 merged main 后开发。
- main 集成门禁：Release/CTest 31、Vitest 188/build、性能工具 233、Phase16 source 4/API 7/migration 5/Redis 11/refund verifier 3，以及最终 verifier 零违规。原 main 新增的 cgroup 采样入口需要补齐一处测试 mock，包含在 merge commit 中。
- Phase15 的后续提交只发布到 Phase16 分支；不再合并 main、不创建 PR、不 force push。

## 数据库与公开读模型

Migration011 `011_add_event_sales_window.sql` 在 Event 添加两个 TIMESTAMPTZ 字段。先 nullable，按该 Event 最晚 Session 开演时间回填 ends；无 Session 则取 created_at + 1 秒。starts 取 created_at 与 ends - 1 秒较早值，然后添加 starts < ends CHECK 和 NOT NULL。保留 migration010 和已有索引；全部 initdb 挂载顺序更新为 011 migration、012 Demo seed、013 起校验。性能数据生成器显式写入覆盖全部未来场次的 Event 窗口。

公开 Event/Session 均有必需 `salesWindow={startsAt,endsAt,state,evaluatedAt}`，时间为 UTC Z。Session 有效 end 为 min(Event end, Session start_time)，Event 展示 end 为 min(Event end, MAX(Session start_time))。使用本条读取 SQL 的 statement_timestamp 分类；状态为 NOT_STARTED / OPEN / ENDED，与 Event/Session 的静态 status 分开。空有效窗口为 ENDED。正式入场要求静态 Event 和 Session 都 ON_SALE 且满足半开区间 `[startsAt, effectiveEnd)`。

## 正式预订与幂等顺序

SalesWindowRepository 的单条 SQL 使用 `WITH sales_clock AS MATERIALIZED (SELECT clock_timestamp() AS now)`；同一 SQL 的状态和 remainingMilliseconds 共用一个 DB 时刻。它在当前事务读取，不锁 Event/Session，不使用应用时钟。

Reservation 先查询已有幂等结果。初步 Gate 保存结果，随后尝试唯一键仲裁；如果 insert 冲突则 rollback 后重放已有结果，不能让初步 ENDED 覆盖成功幂等请求。只有新 winner 处理初步状态拒绝。锁定并校验全部 SessionSeat、检查金额溢出后，再读取一次新 DB 时刻，最终 Gate 通过才写正式占座/Reservation/Order。等待 Seat 锁跨截止的请求整单回滚，formal_version 和 outbox 不变。错误为 HTTP409 SALES_NOT_STARTED / SALES_ENDED。

## Checkout 与 Hold

- create：Gate 在座位准备与 Redis 写入前，剩余 TTL 传给 prepare。
- replace：空集合继续允许释放；非空集合先 Gate，拒绝时不增加 revision、不续期 Hold。
- SELECTING confirm：先 Gate 再 ensure；时间拒绝在当前持有 Checkout 行锁的事务中转 ABANDONED，COMMIT 成功后 best-effort release。
- SUBMITTING confirm：先沿用已有 active_confirm_idempotency_key 进入正式幂等恢复，不提前用窗口拒绝。若正式 Reservation 返回时间错误，则单独事务重新锁定 Checkout，核对 status 与原 key，再改 ABANDONED 并释放。若已被并发恢复成 RESERVED，返回已有结果。
- RESERVED confirm：返回原订单，完全不查询 Gate。
- Hold prepare/ensure 接收 int64 毫秒，defaultTtlMilliseconds 为经过既有正数/INT_MAX 校验的 ttl_seconds 乘 1000；实际传入 min(300000, remainingMilliseconds)。非正值不写 Redis，Lua SET PX / PEXPIRE。正式订单的 15 分钟支付截止独立保留。
- Phase16 的派生 Hold、ZSET expiry 和区域摘要仍由原 wrapper 根据实际 PTTL 同步；没有第二套销售时间过期逻辑，没有停售全场 SCAN/KEYS。

真实崩溃测试单独启动专用容器并设置 `PHASE15_FAULT_AFTER_FORMAL_COMMIT=1`，在新正式结果提交后、Checkout setReserved 前 exit(88)，随后正常容器在 ENDED 恢复原订单。该测试开关默认未设置；正常配置与性能镜像环境均未启用。

## 前端与 Mock

Event/Session 类型要求 salesWindow；卡片同时显示静态业务状态、开售/截止和倒计时。展示时钟按 evaluatedAt 校准，仅作倒计时；是否可购只使用服务端 OPEN 加静态可售。到边界只发起一次相应读取，不逐秒 HTTP。失败可通过焦点/手动刷新重试。

选座页在 NOT_STARTED/ENDED 可加载 Layout 与一个 Zone Snapshot；不安排周期 Delta。OPEN 保留 Phase16 的 2 秒正常刷新、5 秒 degraded 刷新、hidden/focus、hasMore 排空、single-flight 和过期响应 fence。服务端 ENDED 后清除周期定时器；SUBMITTING 恢复和已有订单入口保留。

SALES_NOT_STARTED/SALES_ENDED 被归为确定业务失败：刷新一次 Session、best-effort abandon 当前 SELECTING、清 locator/选择，保留座位图，不进入未知结果轮询。只有网络/未知异常或 5xx 类响应继续同一会话恢复。Mock 提供 setMockSalesClock/setMockSalesWindow，真实计算半开区间并覆盖新 Reservation、create、非空 replace 和 confirm；RESERVED 重放以及支付/退款规则保留。

## 验证与观测

详见 `performance/experiments/phase15-sales-window/` 与各 phase15 测试。真实 PG 覆盖旧010升级、新库初始化、无Session回填、CHECK/NOT NULL、有效end、精确边界、Seat锁等待跨截止和并发同key；真实 HTTP/Redis 覆盖 Checkout 所有状态路径、短 TTL、自然过期和恢复。Playwright 三条真实流程已通过，包括停售后支付、SELECTING 拒绝和 SUBMITTING 原结果恢复。

Gate 次数由真实 pg_stat_statements 测得，1 座与 6 座一致：create 1、非空 replace 1、SELECTING confirm 3（Checkout 一次，Reservation preliminary/final 各一次）、直接 Reservation 2、成功 RESERVED/Reservation replay 0。最终 Gate 每请求一次，不是每座位一次。

新增 `ticketing_sales_window_rejections_total{entrypoint,reason}`，entrypoint 仅 checkout_create / checkout_replace / checkout_confirm / reservation_create，reason 仅 not_started / ended。只在返回外部错误的 Controller 计数；真实指标测试证实内部 Reservation 不重复计数。

Phase15 verifier 检查窗口、Checkout key/结果形状、幂等重复、订单金额和有效权利；复用原 Phase16 与原 verify.sql，检查 5,060 个已初始化 Redis 座位，全部零违规。RESERVED 保留原确认 key 是既有 schema 契约，verifier 按此校验。

最终门禁：Release构建通过；CTest32/32；Vitest196/196与生产构建通过；性能工具233/233；Phase15外部20/20（migration4、read2、Reservation4、Checkout7、crash1、observation2）；模拟支付6/6；Phase11/12共60/60（首轮59通过，恢复原行缓冲配置后唯一日志超时项重跑通过）；Playwright3/3；Phase16 API7/7、Redis11/11；代表性性能6/6。最终精确测试数量和日志索引见本目录下 `../performance/experiments/phase15-sales-window/gates.json`（路径相对仓库 docs）。

## 性能对比与边界

合并基线和 Phase15 二进制分别使用独立 `phase14-phase15-baseline` / `phase14-phase15-current` 项目，原 Phase14 G0/U1/U2 smoke 模型、同一数据快照，20 active users、每 Session 100 座；PG4、Redis Hold2、Compute4/Queue16 保持不变。两组6轮全部 functionalSmoke/correctness通过，没有停止条件、投递错误或死锁。G0 是 no-op 生成器校验，不是后端容量结论。

完整请求延迟从主 shard 原始点重新计算，未平均 percentile。资源峰值覆盖预热/负载/恢复采样；CPU100%表示一核；Gate执行耗时来自 PostgreSQL差量，不包含网络和连接获取等待。

| 负载 | 版本 | HTTP/s | p50 ms | p95 ms | p99 ms | 后端CPU峰值% | 内存峰值MiB |
|---|---|---:|---:|---:|---:|---:|---:|
| G0 | baseline | 21.39 | 0.330 | 0.974 | 1.871 | 8.22 | 32.49 |
| G0 | current | 21.09 | 0.306 | 0.559 | 0.586 | 0.45 | 22.79 |
| U1 | baseline | 47.76 | 1.466 | 5.256 | 9.684 | 18.12 | 25.06 |
| U1 | current | 47.30 | 1.381 | 4.328 | 9.449 | 11.97 | 27.16 |
| U2 | baseline | 48.16 | 1.510 | 5.189 | 11.166 | 15.17 | 38.57 |
| U2 | current | 48.17 | 1.379 | 4.526 | 9.532 | 7.27 | 26.39 |

U1/U2 新实现各观测到85次Gate，PG平均执行约0.022/0.029ms；采样中的Event/Session全局锁、PG锁等待、事务获取waiter、Compute队列峰值和死锁均未出现。原Phase16 API测试还验证连续20次热Delta没有新增全量SessionSeat读取。

该短负载只说明本机工程回归未见明显性能退化。Docker主机共享，未建立正式双机隔离；不能从小样本、不同CPU采样峰值或较低p95推导生产SLA/容量提升。真实API浏览器模式验证功能边界；Mock只是本地替身。

初次性能准备发现工程编译镜像缺少curl，尚未施加负载；健康检查改用相同HTTP健康与数据库断言的Python探针后运行。历史Phase14 memory输入在Windows checkout转CRLF导致原字节哈希失败，新增.gitattributes固定LF，使原SHA与断言保持不变。Vitest排除新的phase15-e2e目录，三条浏览器测试由Playwright独立执行；没有降低原测试断言。

验收测试修正：Redis TTL与派生expiry以同一Lua调用读取，排除Docker CLI往返时间；PromExporter拒绝计数等待其短期HTTP缓存发布后仍严格断言每入口增量为1；场次卡片显式设置可选布尔eventAvailable默认true，并通过本机时钟偏移至2030年的组件测试证明校准与服务端状态门禁。
