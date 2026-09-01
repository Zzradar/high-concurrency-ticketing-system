# Phase 5 服务端购票会话落地设计

## 1. 问题与边界

CheckoutSession 是“某个用户针对某个具体 Session 的一轮连续购票过程”。它与一次确认的服务端幂等键、Reservation 和 Order 是四个不同身份。同一用户可在同一场次创建多个会话。

Phase 5 不做 Redis 临时占座，不给 CheckoutSession 增加短期过期时间或周期 Worker，不实现支付、取消或 Phase 6 前端恢复。购票会话的座位集只是购买意图；PostgreSQL `SessionSeat` 与 Phase 3 正式事务仍是库存最终权威。

## 2. 数据模型

`checkout_sessions` 包含 `id / user_id / session_id / status / active_confirm_idempotency_key / reservation_id / created_at / updated_at`。`reservation_id` 唯一并关联 Reservation；表中不存 `order_id` 和 `expires_at`。

`checkout_session_seats` 以 `(checkout_session_id, session_seat_id)` 为主键。复合外键同时保证 CheckoutSession 和 SessionSeat 的 `session_id` 一致。最多 6 个座位由 Service 校验。

## 3. selectedSeats 持久化

`POST /checkout-sessions` 要求 1～6 个不重复的 `session_seats.id`，并在小事务中校验用户、Session 与座位归属后写入首版完整集合。

`PUT /checkout-sessions/{id}/seats` 是完整集合替换，允许空数组。单个事务先用 `FOR UPDATE` 锁会话行，确认所有权与 `SELECTING`，完成新集合校验后删除旧关联并插入新关联。任一步失败都整体回滚。保存意图时不锁库存，也不要求座位当前为 AVAILABLE。

## 4. 状态机

```text
SELECTING --confirm--> SUBMITTING --正式成功--> RESERVED
    |                        |
    +--abandon--> ABANDONED  +--明确业务失败--> SELECTING
```

- `SELECTING`：可替换座位，可放弃；confirm 时必须有 1～6 个座位。
- `SUBMITTING`：座位与活动确认 Key 冻结，不允许 PUT 或 abandon。
- `RESERVED`：关联正式 Reservation，不通过会话操作删除 Reservation/Order。
- `ABANDONED`：终态，重复 abandon 稳定返回当前结果。

## 5. confirm 双层并发保护

Transaction A 锁 CheckoutSession 行。`SELECTING` 在锁内读取完整座位集，生成一把 `CHK-CONFIRM-*` 服务端 Key，写入 `SUBMITTING` 后提交。并发确认在获得同一行锁后看到 `SUBMITTING`，只能复用既有 Key 和冻结座位集。

Transaction A 之外调用 Phase 3 `ReservationService` 内部入口。Phase 3 保持原有的 `(user_id, idempotency_key)` 唯一仲裁、固定顺序 SessionSeat 行锁、多座位原子性、Reservation/关联/Order/HELD 同事务与 commit callback。

Phase 3 成功后，Transaction B 再锁会话行，验证 `SUBMITTING + 同一 Key`，写入 `RESERVED + reservation_id` 并在 commit callback 成功后返回。

## 6. 失败与恢复

Phase 3 明确返回座位冲突、场次不可售等“没有创建正式结果”的业务失败时，新事务锁会话行，将其恢复为 `SELECTING`、清除 Key，但保留座位意图。技术异常或结果未知不能证明正式失败，因此保持 `SUBMITTING + Key`。

恢复有三个入口：

1. 服务启动后执行一次有界被动对账，默认批量为 100，可通过 `checkout_session_reconciliation.batch_size` 配置；它只把已有正式 Reservation/Order 的 `SUBMITTING` 修复为 `RESERVED`。
2. GET 读到 `SUBMITTING` 时按 `(user_id, active key)` 按需对账；找不到结果时保持原状态。
3. 用户对 `SUBMITTING` 再次 confirm 时，复用原 Key 重新进入 Phase 3 幂等逻辑。

启动对账不重放 Phase 3，不创建新订单，也不是周期 Worker。

## 7. API

```text
POST /checkout-sessions
GET  /checkout-sessions/{id}
GET  /checkout-sessions?sessionId=...&recoverable=true
PUT  /checkout-sessions/{id}/seats
POST /checkout-sessions/{id}/confirm
POST /checkout-sessions/{id}/abandon
```

所有接口使用 `X-User-Id`，JSON 为 camelCase，成功响应不包统一 `data` 外层。创建返回 201，查询与状态操作返回 200，参数错误返回 400，资源不存在或不属于当前用户统一返回 404，状态或座位冲突返回 409。

`recoverable=true` 列表返回该用户该场次的全部 `SELECTING / SUBMITTING` 会话，不挑选“最新一个”；`ABANDONED` 与 `RESERVED` 不在进行中列表中，已知 id 仍可通过 GET 读取 `RESERVED` 及其 Reservation/Order。内部确认 Key 不输出到 HTTP DTO。

## 8. 舍弃与暂缓

本阶段明确舍弃“一用户/一场次只有一个会话”、用前端传入确认 Key、把购买意图当作 HELD、把 Phase 3 包进巨型外层事务，以及把所有失败都重置为 `SELECTING` 的方案。

Redis 临时占座留到 Phase 7；支付、取消和超时终态竞争留到 Phase 8；通用幂等记录与异步受理继续按后续接口数量和真实压测评估。Phase 6 前端只将 `checkoutSessionId` 作恢复线索，具体代码不在本 Phase 实现。
