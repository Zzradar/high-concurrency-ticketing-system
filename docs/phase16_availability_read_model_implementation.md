# Phase16 分区化、版本化增量 Availability 实施记录

## 基线与隔离

本轮从开始时最新的 `origin/main=9006ee822e557255e244364495fbe251a1a25b18` 创建 `phase16/availability-read-model`，工作树为 `D:/Documents/vscode/high-concurrency-ticketing-system-phase16`。原附件参考点之后存在 3 个小提交，已包含在此稳定基线。原 main 工作树不切分支、不改文件、不提交、不合并、不 rebase、不 cherry-pick、不 push；没有跟随实施期间移动的 main。最终提交 SHA、ahead/behind 与普通 push 结果由交付消息报告，避免文档自引用提交 SHA。

## 库存权威与事务事件

PG `session_seats` 仍是正式库存权威。既有 ReservationRepository Hold 与 OrderRepository 卖出、取消/过期释放、退款释放的锁序和事务不变。Redis 只服务读取和临时 Hold；正式 Confirm 仍竞争 PG 锁并校验库存，不凭页面颜色授予购票权益。

迁移 `backend/db/migrations/010_add_seat_availability_read_model.sql` 增加非负 bigint `formal_version`，默认 0。BEFORE UPDATE trigger 仅在 status IS DISTINCT FROM 旧值时 +1；AFTER trigger 在同一事务插入 `seat_availability_outbox`。库存和 outbox 同成同败，多席逐行生成事件，noop/INSERT 不生成事件。唯一 `(session_seat_id,formal_version)` 防重复。Outbox 不加外键，以免历史事件改变原有删除语义。

ProjectionWorker 合并 outbox repository/service 职责，单次 CTE 以 `FOR UPDATE SKIP LOCKED` 领取最多 100 行，5 s lease 与 token；Redis 应用后按 id+token 删除。Redis 故障不 ack，租约可重新领取；旧 token 不能删除新租约。初始化锁存在则 deferred 并释放本租约；无模型且无初始化锁时可以 ack，因为后续初始化必读最新 PG。真实故障测试发现并修复 LIMIT 的 PG 参数类型推断问题：显式 `$1::integer` 与绑定类型一致。

版本比较使用十进制字符串长度和字典序，避免 Redis Lua double 在 2^53 以上丢精度。仅更高版本更新；重复/乱序事件 stale，不生成第二条业务变化。public 状态未改变但 formal/version 或 owner 改变，仍生成事件，以便自身 Hold 覆盖语义正确变化。

## Redis 分层与原子边界

同一现有 `seat_holds` Redis 中按 `ticketing:seat-availability:{sessionId}` 命名。meta 保存 ready/generation；zones 保存静态顺序；seat-zone 与每区 seats SET 保存分区；formal HASH 保存 status|version；holds HASH 保存 owner|revision|expiresAt；hold-expiry ZSET 是到期候选索引；每区 summary 保存 total/available/held/sold，每区 changes Stream 保存变化。

原始 `ticketing:seat-hold:{sessionId}:seatId` 带 TTL key 保持原来所有权权威。formal HELD/SOLD 永远优先；formal AVAILABLE 时才考虑 Hold，持有人可见 AVAILABLE，其他用户和匿名可见 HELD。checkoutSessionId 标识 Hold owner，认证 userId 用于验证其归属，不能互相替代。

原 prepare/ensure/release/finalize/abort Lua 由同一 EVAL 包装，先验证所有原 key 类型与模型结构，再执行原操作并原子同步派生结构。模型损坏先失效化并维持原 Hold 语义，不能在原 Hold 已写入后因派生类型/数字错误留下部分更新。同 owner 刷新 TTL 不制造假 Delta，revision 与 expiresAt 更新；新 owner 即使公共状态仍 HELD，也发 Delta。

TTL 负责实际 Hold 有效性，ZSET 只定位可能过期的席位。读取前批量清理，每批 512，再次核对当前原 key/owner/revision/TTL；新 ensure 延长的 Hold 不会被旧候选删除。正式 HELD/SOLD 不因临时过期变 AVAILABLE。无需 Keyspace Notification，无 KEYS/SCAN 热路径。

## 初始化与故障恢复

先原子获取 15 s init token；只有持有者查询全量 PG formal/version/zone。其他请求通过现有 EventLoop 每 20 ms 等待，最多 1000 ms 后返回 `503 SEAT_AVAILABILITY_INITIALIZING`，不会形成全场查询 herd。PG 返回拥有自身内存的行数据，经现有 SeatMapComputeExecutor 编码，再提交 init Lua。

初始化脚本先验证全部载荷和原 Hold key，再清理旧派生数据。发布时重新读取当前原 Hold 与 PTTL，因此 PG 快照之后发生的临时变化仍被导入。每区写 baseline Stream 事件；完成全量构建后最后写 ready/generation，删除匹配 token。过期旧 token 不能发布。锁期间 projector 保留事件；快照后发生的正式写入在发布后按更高 version 投影，不会遗漏。

整体 Redis 不可用时使用 PG 目标 Zone 查询及全场分组 Summary，尽力叠加原 Hold；返回 degraded Snapshot，generation/cursor=null、reset=true。它不保证临时 Hold 精度，仍保证 PG 正式库存不被临时状态覆盖。客户端保留静态布局并减慢轮询。Redis 恢复/清空后重新初始化 generation，旧游标 reset。

真实停机测试证明 Checkout Confirm 仍成功提交 PG HELD 与 outbox。停机时未完成的临时 finalize 清理可能保留原 Hold 至 TTL；若之后正式库存释放，页面仍可能暂显临时 HELD。保留原 300 s TTL 语义，未通过缩短生产 TTL 掩盖该边界。测试按原 owner 显式清理自身 fixture。

## Snapshot / Delta 协议与执行路径

无 zone 的 `/sessions/{id}/seat-availability` 保留 `{sessionId,seats}` 旧协议和原服务路径。带 zone 首次返回该区完整 Snapshot 与所有 Zone 公共 Summary。后续带 generation+since 返回 Delta；since 必须为规范 uint64-uint64 Stream ID，两个参数必须成对。

读取脚本在一次原子操作中取得 summary、seat formal/owner 和实际 cursor。Delta 扫描 `(since,+]` 最多 limit+1（默认1000），按 seat 去重并返回当前状态。hasMore=true 时 cursor 是实际消费末尾事件，不跳到 stream tail；无变化保持输入 cursor。generation 不符或游标早于实际保留首事件时返回 reset Snapshot。Stream `MAXLEN ~10000` 是近似上限，允许 Redis 节点粒度超量；真实 12000 事件测试验证裁剪与精确 reset。

C++ Redis callback 仅复制 owned string/vector，JSON/overlay 放入共享 4-worker/16-queue SeatMapComputeExecutor。容量满明确 `503 SEAT_MAP_BUSY`；不新增线程池、不无限排队、不跨 callback 持有 RedisResult。ProjectionWorker 使用弱引用 EventLoop runAfter；多次故障 stop/start 与最终 Release 验证未观察到 shutdown hang。

CheckoutOwnershipCache 保存不可变 userId/sessionId，TTL600。认证后查缓存，两个字段均匹配才授予 own；不匹配直接无 own。miss/格式错误/Redis 命令失败回 PG findByIdForUser 后 best-effort fill，不公开 owner/userId。

## 前端状态机

SeatSelectionPage 持有 activeZone、完整静态 layout、已加载 statusBySeatId、每区 loaded/generation/cursor/degraded，以及服务器公共 Summary。Layout 后选第一个真实区，仅请求该区 Snapshot；取消“全区完整动态网格”。跨区已选座位保留，RecoverableCheckoutPanel 标签来自静态 layout。

Snapshot 完整替换目标区；Delta 校验 seat 属区与去重后 patch，保留其他区状态。上下文 user/checkout 改变时清理所有旧游标，立即刷新当前区与选中席所在区 Snapshot。路由、区切换、卸载和 context epoch 丢弃过期响应；每区请求串行，hasMore 立即继续。

正常使用递归 setTimeout 2 s，degraded 5 s；hidden 暂停，visible/focus 恢复。确认、冲突恢复、支付与退款后的显式刷新复用此协议。Mock 保存真实每区变化与 cursor/generation，不用空数组伪装 Delta。

## 配置与部署

五个 config*.json 统一：init_lock_seconds=15、init_wait_milliseconds=1000、stream_maxlen=10000、delta_scan_limit=1000、expiry_cleanup_batch=512、checkout_owner_cache_ttl_seconds=600；projection batch_size=100、interval_seconds=0.5、lease_seconds=5。启动校验严格正数和范围。PG pool4、seat_holds pool2、compute4/16、Hold300 均未增加。

四个新建数据库 Compose 入口在 demo seed 前挂载迁移010。已有数据库必须通过既有迁移流程先执行010，再部署后端；新增挂载不会自动升级旧 volume。Lua 编译时嵌入，不依赖工作目录读取源脚本。CMake 普通门禁不需要 Docker，外部测试用 `TICKETING_PHASE16_EXTERNAL_TESTS` 显式启用。

低基数指标为 ticketing_availability_events_total(operation,outcome)、ticketing_availability_duration_seconds(operation)、ticketing_availability_returned_seats(operation)，覆盖 init、sync、reset、expiry、projection；继续使用既有 SeatMapComputeExecutor 指标。标签没有 session、zone、seat 或 owner。

本轮没有 SSE/WebSocket/MQ/CDC；2 s 有界增量轮询满足当前协议，不引入额外连接生命周期或消息基础设施。所有派生数据可从 PG 与仍有效 Hold 重建。

## 已执行门禁

- C++20 Release + BUILD_TESTING=ON，完整 CTest 31/31。
- frontend Vitest 188/188，frontend build 成功；新增 Playwright 专用目录从 Vitest 发现中排除。
- performance unit suite 211/211（原有207项加4项证据回归）。冻结的 Phase14 targets Git blob 未改；`.gitattributes` 固定该文件 LF，消除 Windows CRLF 与已冻结 SHA256 的冲突，未改预期值或放宽断言。
- 真实迁移 5/5：版本/noop/多席/rollback/unique/trigger失败回滚、双 worker SKIP LOCKED、旧租约 ack。
- 真实 Redis 11/11：完整 init、Hold 操作、版本重复乱序、超大版本、TTL 竞态、owner变化、损坏模型、paging/trim。
- 真实 API 7/7：旧协议、分区协议、400/404/503、init等待、腐坏重建、ownership、去重/paging/trim、warm无全场查询。
- 真实浏览器 2/2：5000静态+1000动态、Zone切换/跨区选择、A/B Hold和release、自然短TTL、Confirm、simulation付款、取消和买家全额退款，无reload。
- 故障与初始化：apply后ack前退出86、PG后publish前退出87、Redis停机/恢复/FLUSH、PG rollback；真实5000行快照发布屏障，Hold更新与outbox不漏；Redis停机Confirm成功。
- 原 Phase14 verify_run 对真实新建并过期订单通过；PG/Redis校验器所有违规为0。

原 verify.sql 对 Phase12 已成功 BUYER 全额退款的 CANCELLED 订单仍要求 PAID，真实浏览器门禁暴露该误报。只增加完整匹配的成功买家退款闭环例外（accepted SUCCEEDED payment、金额/币种、SUCCEEDED BUYER refund、refunded_at、终态），不放宽原非法状态；3个真实事务测试证明正确退款通过、缺退款和金额错误继续失败。

详细指标、逐档资源、原始日志、复现命令见 [性能报告](../performance/experiments/phase16-availability/README.md)。真实 Stripe 外部渠道测试未重新执行；本轮保留其原有基础回归，真实支付/退款 UI 使用 simulation，不声称验证生产资金渠道。

## 性能与已知边界

5000席冷请求48个/并发24仅一次全量PG初始化；单次冷初始化80.32 ms，PG7.35 ms、Lua50.343 ms。200/s、20s空Delta p50/p95/p99=1.264/1.982/3.571 ms、546 bytes、0错误/0dropped/0compute reject、0库存/ownership热查询；1-seat Delta p95=2.060 ms。legacy全场p95=53.526 ms、260046 bytes。

同负载整区Snapshot p95=681.112 ms、164拒绝、737dropped，Redis接近单核饱和并触发26次degraded；这是首次观察到的失稳档。没有扩容线程/连接或掩盖结果。短窗口、共享主机、单场次证据不构成最大容量或SLA；尚未验证多场次冷启动风暴、Redis Cluster或长期稳定性。
