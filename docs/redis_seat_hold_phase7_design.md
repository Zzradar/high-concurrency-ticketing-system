# Phase 7：Redis 临时占座设计

## 1. 阶段目标与边界

问题：Phase 6 的 `selectedSeats` 和 CheckoutSession `seatIds` 只保存购买意图。两个用户
可以同时认为同一座位可选，直到正式 Confirm 才由 PostgreSQL 裁决，竞争反馈偏晚。

解决思路：Phase 7 在 `SELECTING` 阶段增加 Redis Hold，把一部分冲突提前到选座过程。
Redis Hold 与 PostgreSQL `SessionSeat.status = HELD` 是两个概念：前者可丢失、可过期，
后者是正式 Reservation 的库存状态。PostgreSQL 仍是 SessionSeat、Reservation 和
Order 的最终事实来源，Phase 3 正式事务仍负责最终防超卖和多座位原子性。

Phase 7 没有新增数据库 Schema 或 migration，也没有改变 CheckoutSession 的
`SELECTING / SUBMITTING / RESERVED / ABANDONED` 状态机。

每个场次座位使用一个 String key：

```text
Key    ticketing:seat-hold:{sessionId}:sessionSeatId
Value  checkoutSessionId|revision
Client seat_holds
```

`{sessionId}` 是同场次多 key 的 Redis Cluster hash tag。第一版不维护
`C1 -> held seat set` Redis 索引。

## 2. 为什么在选座阶段开始 Hold

问题：如果仍等到 Confirm 才第一次竞争座位，用户可能完成较长时间的选择后才知道
座位已被别人选择，正式 Reservation 入口也会承受更多注定失败的请求。

解决思路：第一次真实选座创建 CheckoutSession 时即申请首批 Hold，后续完整集合 PUT
同步调整 Hold。其他用户可以通过座位图更早看到临时不可选状态。纯浏览不创建 C1，
Redis Hold 也不赋予正式购买资格；Confirm 仍必须通过 PostgreSQL 最终裁决。

## 3. full-set 多座位更新

问题：C1 当前选择 A01、A02，准备换成 A01、A03，但 A03 已被 C2 Hold。如果先释放
A02 再尝试 A03，本次换座失败会让 C1 连原有 A02 也丢失。

解决思路是“先拿新增座位，再释放旧座位”。PUT 继续接收完整 seatIds 集合，并计算：

```text
old      = A01,A02
new      = A01,A03
retained = A01
added    = A03
removed  = A02
```

Redis Prepare 原子检查整个 new 集合。A03 属于 C2 时立即返回冲突，且不修改任何 key；
A02 不会被释放，PostgreSQL 的 seatIds 和 revision 也不变化。只有 Prepare 和 PostgreSQL
更新成功后，Finalize 才处理 removed。

空集合仍是合法 full-set PUT：无需 Prepare 新目标，PostgreSQL 成功提交空集合与新
revision 后，再 Finalize 原有全部座位。

## 4. 同一个 C1 的并发修改

问题：同一 CheckoutSession 的多个 Tab 可能使用相同旧版本同时 PUT，不同 Redis
命令本身不能决定哪个请求有资格更新服务端 checkpoint。

解决思路：继续使用 PostgreSQL CheckoutSession 行的 `SELECT ... FOR UPDATE` 串行化
同一 C1，并在锁内校验 `expectedRevision`。只有版本匹配的请求进入 Redis Prepare 和
PostgreSQL full-set 更新；成功 PUT（包括 same-set PUT）使 revision 原子加 1。过期
请求返回 `CHECKOUT_SESSION_VERSION_CONFLICT`。不为 C1 增加 Redis distributed lock。

## 5. revision fencing

问题：异步 cleanup 可能迟到。例如：

```text
rev3：A01,A02
rev4：A01,A03，rev4 Finalize 应释放 A02，但回调迟到
rev5：A01,A02,A03，用户又合法把 A02 加回来
Redis 当前 A02 = C1|5
```

如果 rev4 Finalize 只检查 owner 为 C1，就会错误删除 rev5 新获得的 A02。

解决思路：Hold value 保存 `checkoutSessionId|revision`。Finalize 只删除 owner 相同且
`holdRevision <= targetRevision` 的 key，因此 rev4 cleanup 看到 `C1|5` 时跳过。
Abort 的条件更严格：只有 value 精确等于 `C1|targetRevision` 才删除 added；同一 owner
的更高版本也不能删除。所有判断和 DEL 都在 Lua 内完成，避免 GET/DEL 的 TOCTOU 竞态。

## 6. Prepare / PostgreSQL / Finalize 编排

问题：Redis 和 PostgreSQL 没有分布式事务，换座过程必须在局部失败和不确定回调下
仍保住已有资源，并避免旧补偿伤害新版本。

解决思路：以 `old=A01,A02`、`new=A01,A03` 为例，实际顺序是：

1. PostgreSQL 锁 C1，校验 SELECTING 与 expectedRevision，并读取 old。
2. Redis Prepare 把 added key 排在 retained 前，在一段 Lua 中先预检全部 new key；只有
   全部不存在或属于当前 C1 才进入写入阶段。added 总是写成 `C1|targetRevision`；
   retained 缺失时补成 `C1|baseRevision`，已属于 C1 时保留 revision 并刷新 TTL。
   该步骤只获取 A03、检查/续期 A01，不释放 A02。
3. Redis 明确冲突时回滚，所有 Hold 与 PostgreSQL checkpoint 保持原样。
4. Redis unavailable 时记录降级语义，继续 PostgreSQL Phase 6 流程。
5. PostgreSQL 整体替换 selectedSeats，并把 revision 加 1。
6. PostgreSQL commit 成功后，Finalize 才释放 removed A02。
7. PostgreSQL 后续失败或 commit 失败时，Abort 只撤销本次 `C1|targetRevision` 的 A03。

Prepare 即使返回 unavailable，也可能已经在 Redis 执行但响应丢失。因此 PostgreSQL
失败路径仍尝试 exact-revision Abort。Abort/Finalize 失败不反转 PostgreSQL 结果，
残留由 TTL 清理。这是带补偿和 fencing 的编排，不是 Redis + PostgreSQL 强一致事务。

Create 流程先生成稳定 `CHK-*` ID，在 PostgreSQL 完成用户、场次和座位归属校验后，
以 revision 0 Prepare 全部初始座位；成功或 unavailable 后才 INSERT C1 与关联座位。
明确冲突不创建 C1，后续 PostgreSQL 失败只 Abort 精确的 `C1|0`。

## 7. TTL

问题：浏览器关闭、网络中断或进程崩溃时，客户端不一定能显式释放软占座。

解决思路：每个 Hold 默认 TTL 为 300 秒，通过
`custom_config.checkout_seat_hold.ttl_seconds` 配置。成功 create/PUT 会建立或刷新
相关 Hold。第一版不做 heartbeat，因此只停留页面不会无限续期。

Hold TTL 到期不会删除 CheckoutSession 或其购买意图，也不会让 CheckoutSession 进入
EXPIRED；后续 PUT/Confirm 可以重新尝试取得 Hold。这个 300 秒 TTL 与 Order 正式
15 分钟支付超时是两套独立生命周期。

## 8. Redis unavailable

问题：Redis 连接失败、超时或响应无法解析时，系统无法确定临时操作是否执行；如果
把技术故障当成业务冲突，会无谓阻断合法购买。

解决思路：SeatHoldService 区分 `Applied / Conflict / Unavailable`。只有明确发现其他
C1 owner 才是 Conflict；Unavailable 降级到 Phase 6，允许保存 CheckoutSession 意图，
正式 Confirm 继续由 PostgreSQL 防超卖。Redis 不能让 PostgreSQL 本应失败的请求成功。

Redis `/data` 在 Compose 中使用 tmpfs，不保存正式数据。第一版不引入分布式事务、
Redis 分布式锁或 Redis 主动对账 Worker；临时残留依靠 TTL 自愈。

## 9. Confirm

问题：C1 的 Hold 可能已经自然过期或随 Redis 重启丢失，也可能被另一个 C1 取得；
同时 SUBMITTING 重试可能对应一个已经成功的正式 Reservation。

解决思路：只有 SELECTING 在 freezeConfirm 前执行 Ensure：

- 自己的 Hold 存在：刷新 TTL；
- Hold 不存在：以当前 C1 和 revision 补建；
- 其他 owner：返回 `SEAT_TEMPORARILY_HELD`，不进入 SUBMITTING，也不持久化确认 K1；
- Redis unavailable：继续冻结 C1，并调用 Phase 3 PostgreSQL 正式确认。

当前代码会在 Ensure 前生成一个仅存在于本次内存状态中的候选 `CHK-CONFIRM-*`，但只有
Ensure 通过后才写入 SUBMITTING 并持久化；临时冲突不会留下可重试 K1。SUBMITTING
重试复用已保存 K1，不重新依赖 Redis Hold，因为正式 Reservation 可能已经成功。

正式 Reservation 成功并把 CheckoutSession 提交为 RESERVED 后，终态 Release 按
owner 删除 C1 Hold。GET/恢复路径把已知正式结果 reconcile 为 RESERVED 后也执行相同
best-effort cleanup。启动时批量 reconciliation 当前只返回修复数量，没有逐 C1 清理；
该崩溃恢复残留由 TTL 自愈。

## 10. Abandon 与正式业务失败

问题：C1 进入不能继续 PUT 的终态，或正式 Reservation 明确失败并返回 SELECTING 时，
旧 Hold 若继续存在会无谓阻塞其他用户；迟到 release 又不能删除后续新获得的 Hold。

解决思路：ABANDON 仍只允许 SELECTING。事务锁住 C1、读取 seatIds 并提交 ABANDONED
后，按 owner best-effort Release；Redis cleanup 失败不改变 ABANDONED 结果。

Phase 3 明确返回 `SEAT_CONFLICT` 等业务失败时，新事务重新锁住仍为 SUBMITTING 且 K1
匹配的 C1。在行锁仍阻止新 PUT 时先按 owner Release，再重置为 SELECTING 并清除 K1；
这样旧 release 不会晚于新的合法 PUT。Redis unavailable 时仍继续 PostgreSQL reset，
cleanup 失败不改变正式业务失败结果。

## 11. Seat map

问题：座位图必须让其他用户看到 live Hold，同时不能把当前 C1 自己已选的座位显示成
不可选，也不能让 Redis 覆盖 PostgreSQL 正式状态。

解决思路：`GET /sessions/{sessionId}/seats` 接受可选 `checkoutSessionId`，后端先查询
PostgreSQL，再用一次批量 Redis 读取叠加 owner：

- PG HELD/SOLD：始终保持正式状态；
- PG AVAILABLE + 其他 C1 Hold：响应中表现为 HELD；
- PG AVAILABLE + 当前 C1 Hold：仍为 AVAILABLE，由本地 selectedSeatIds 显示已选；
- 不传 C1：任何 live Hold 都按其他会话处理；
- Redis 读取失败：接口仍成功，返回纯 PostgreSQL seat map。

`checkoutSessionId` 是显示上下文，不是授权边界；写操作仍由 Redis Lua 与 PostgreSQL
重新校验。

## 12. 舍弃与暂缓方案

以下方案已舍弃：

- 等到 Confirm 才第一次 Hold；
- 用逐座 ADD/REMOVE 替代 full-set 更新；
- PostgreSQL 先释放旧座位或写入新 selectedSeats，再尝试取得 Redis Hold；
- 为 C1 增加 Redis 分布式锁；
- Redis 与 PostgreSQL 分布式事务；
- 因自己的 Redis Hold 不存在就绝对禁止 Confirm。

以下方案暂缓：

- heartbeat；
- 独立 operation token；
- Redis 主动对账 Worker；
- WebSocket/SSE 实时推送；
- 座位图缓存。

第一版明确不维护 `C1 -> held seat set` Redis 索引。create、replace、confirm 和 abandon
均能从 PostgreSQL 锁内状态或当前流程拿到 seatIds；额外索引会在单座位 TTL 到期后
产生陈旧成员，当前没有引入它的必要。
