# Phase 8：支付、取消、超时竞争与自动退款设计

## 1. 问题场景

待支付订单可能同时遇到用户支付、用户取消和后台超时。支付渠道又是异步的：请求被
受理不等于成功，渠道结果可能失败、超时后迟到，甚至在订单已经取消、过期或被另一
次支付接纳后才返回成功。系统必须保留渠道事实，同时不能复活已经终结的订单或库存。

CheckoutSession 已在正式预订成功时进入 RESERVED。支付只是其关联 Order、Reservation
和 SessionSeat 的后续生命周期，不应把 CheckoutSession 扩展成 PAID、CANCELLED 或
EXPIRED。Redis 临时 Hold 也只服务 SELECTING 阶段，不能参与正式终态仲裁。

## 2. 采用方案

### 2.1 PaymentAttempt 独立表示异步支付

Order 保持 `PENDING_PAYMENT / PAID / CANCELLED / EXPIRED`，不增加
`PAYMENT_PROCESSING`。Order 与 PaymentAttempt 是一对多关系，Attempt 状态为
`PROCESSING / SUCCEEDED / FAILED / TIMED_OUT`。部分唯一索引保证同一 Order 最多一条
PROCESSING Attempt，因此重复点击支付会复用仍有效的处理记录，而不会启动并行扣款。

`POST /orders/{orderId}/pay` 在短事务中创建或复用 Attempt，提交后立即以 HTTP 202
返回 `order + paymentAttempt`。Drogon EventLoop 的非阻塞 timer 模拟渠道在 2～6 秒后
完成，默认约 1% 失败；HTTP 线程不等待模拟结果。前端约每 1 秒查询
`GET /payment-attempts/{id}`，最多主动观察约 15 秒。

### 2.2 截止时间、宽限与权威时钟

`Order.expires_at` 是允许开始支付的截止时间，不要求渠道必须在该时刻前完成。截止前
创建的 Attempt 获得 10 秒 `processing_grace_seconds`，其
`processing_deadline = started_at + grace`。Expiry Worker 锁定 Order 后再用
`clock_timestamp()` 取得数据库权威时间；仍处于合法 grace 的 PROCESSING Attempt 使
该轮正常跳过 Order，超过 deadline 则先将 Attempt 标为 TIMED_OUT，再继续过期订单。

TIMED_OUT 表示系统已经停止等待本次渠道结果，不等价于渠道最终失败。渠道之后仍可能
报告 SUCCESS，此时仍按迟到成功处理。

### 2.3 Order-first 终态仲裁

支付结果、主动取消和超时释放都先锁 Order，以它作为唯一终态仲裁点。需要访问全部
正式对象时遵循：

```text
Order
  └─ PaymentAttempt（需要时）
       └─ Reservation
            └─ SessionSeat（id ASC）
```

Worker 只在取得候选 Order 时使用 `FOR UPDATE SKIP LOCKED`；在线支付和取消等待同一行
锁。所有路径在锁后重新检查 Order 状态和数据库时间，Redis 不参与这些判断。

正常渠道成功且 Order 仍可接纳时，在一个 PostgreSQL Transaction 中完成：

```text
PaymentAttempt -> SUCCEEDED, accepted_at = now
Order          -> PAID
Reservation    -> CONFIRMED
SessionSeat    -> SOLD, current_reservation_id = NULL
Notification   -> PAYMENT_SUCCEEDED
```

渠道失败时 Attempt 进入 FAILED。只要 Order 仍有效，它保持 PENDING_PAYMENT，
Reservation 保持 ACTIVE，Seat 保持 HELD，用户可以重新发起新的 Attempt。

### 2.4 支付中取消与迟到成功

PROCESSING Attempt 不阻止主动取消，Cancel 按 Order-first 顺序把 PENDING_PAYMENT Order、
ACTIVE Reservation 和所属 HELD Seat 原子转换为 CANCELLED、CANCELLED、AVAILABLE。
取消不把仍在渠道处理的 Attempt 伪造成 FAILED；前端也会继续轮询该 Attempt。

若 PROCESSING 或已经 TIMED_OUT 的 Attempt 收到渠道 SUCCESS，而此时 Order 已
CANCELLED、EXPIRED，或已由另一 Attempt 支付，渠道
事实仍记录为 `SUCCEEDED`，但 `accepted_at = NULL`。该成功不会恢复 Order、Reservation
或 Seat，而是创建独立的全额成功 Refund。原因区分取消前支付未确认、过期前支付未
确认、重复迟到支付和其他未接纳支付。

关键原子边界已经由真实实现确认：未接纳 SUCCESS 的 PaymentAttempt 更新、Refund
INSERT 和当前 `AUTO_REFUND_COMPLETED` UserNotification 使用同一个 PostgreSQL
Transaction。任一 SQL 或 COMMIT 失败时整体回滚，不会留下“Attempt 已成功但 Refund
不存在”的半状态。`refunds.payment_attempt_id UNIQUE` 保证重复 callback 不能重复退款，
通知的唯一 dedupe key 保证当前事务内通知幂等。

### 2.5 用户通知与前端交互

UserNotification 保存支付成功、订单取消、订单过期和自动退款结果。接口按用户隔离：
`GET /notifications` 返回当前用户列表，`POST /notifications/{id}/read` 通过只更新当前
用户记录并以 `COALESCE` 写入 `read_at` 保持幂等。

前端将 `paymentStarting`、`paymentPolling`、`cancelling` 与 Phase 6 CheckoutSession
polling 完全隔离。支付处理中 Pay 按钮禁用，但 Cancel 仍可用；取消后继续观察 Attempt，
未接纳的 SUCCEEDED 到达时刷新通知。右上角 Bell 展示未读数，App 启动、窗口 focus 和
每 5 秒低频刷新通知。

## 3. 最终状态矩阵

| 场景 | PaymentAttempt | Order | Reservation | SessionSeat | Refund |
| --- | --- | --- | --- | --- | --- |
| 正常支付 | SUCCEEDED，accepted | PAID | CONFIRMED | SOLD | 无 |
| 支付失败且仍有效 | FAILED | PENDING_PAYMENT | ACTIVE | HELD | 无 |
| 取消后 late success | SUCCEEDED，unaccepted | CANCELLED | CANCELLED | AVAILABLE | 全额成功 |
| 超时后 late success | SUCCEEDED，unaccepted | EXPIRED | EXPIRED | AVAILABLE | 全额成功 |
| 另一 Attempt 已支付后的 duplicate late success | SUCCEEDED，unaccepted | PAID | CONFIRMED | SOLD | 全额成功 |

无论哪种支付结果，CheckoutSession 均保持 RESERVED。

## 4. 为什么这样设计

- Order 不承载渠道处理中间态，使支付、取消和超时仍围绕有限的正式终态竞争。
- PaymentAttempt 一对多保留每次渠道交互事实，并允许明确失败后在订单期限内重试。
- `accepted_at` 把“渠道确实成功”与“这次成功被订单接纳”分开，避免用 Order 状态篡改
  渠道历史。
- Order-first 行锁让本来不可能同时获胜的终态串行仲裁；固定后续锁顺序减少死锁风险。
- processing grace 保护截止前已开始的支付，又用有限 deadline 避免 PROCESSING 永久
  阻塞库存回收。
- 独立 Refund 不需要给 Order 增加 REFUNDED；同事务和数据库唯一约束共同封闭自动补偿
  的原子性与幂等缺口。
- 通知提供跨页面、取消后迟到结果等异步反馈，而不让通知可用性决定正式状态。

## 5. 进程重启行为与当前限制

当前模拟渠道结果只由进程内 EventLoop timer 驱动。后端在 timer 触发前重启时，timer
丢失且启动阶段不会恢复它；数据库中的 PaymentAttempt 继续保持 PROCESSING。Expiry
Worker 在 processing deadline 前跳过该 Order，到达 deadline 后将 Attempt 置为
TIMED_OUT，并正常关闭已经过期的 Order、Reservation 和 Seat，从而保证数据库最终
收敛，但不会凭空推断渠道成功。

因此，本地模拟 timer 不是正式可靠消息源。未来真实第三方支付应通过 provider callback
或主动查单恢复 PROCESSING 结果。

## 6. 舍弃或暂缓方案

- 不给 Order 增加 PAYMENT_PROCESSING 或 REFUNDED。
- 不让 Cancel 把 PROCESSING Attempt 改成 FAILED。
- 不因 late SUCCESS 复活 CANCELLED / EXPIRED Order。
- 不由 Redis 决定 PAID、CANCELLED、EXPIRED 或 Refund。
- 不在本阶段增加 timer 恢复 Worker、消息队列、outbox、退款重试或人工退款流程。
- 不支持正常 PAID 订单的主动退票与退款。
- 不接入真实第三方支付渠道；当前自动 Refund 是 MVP 内部的全额成功补偿记录。
