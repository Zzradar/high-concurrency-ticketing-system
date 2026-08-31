# 高并发票务预订系统 MVP 接口与数据模型对齐方案

## 1. 文档目的

本文用于统一当前 Vue 3 前端 Demo、现有 C++20 + Drogon + PostgreSQL
后端实现，以及后续 MVP 阶段之间的接口契约和数据模型边界。

本文主要依据：

- 当前前端实际代码整理出的《前端接口契约文档》
- 已确定的《高并发票务预订系统 MVP 技术方案》

目标不是重新设计前端，而是在各后续阶段实施前，把容易导致返工的关键约定先固定下来。

MVP 阶段遵循以下原则：

1. 前端负责展示、交互和本地临时选择状态。
2. 后端负责正式座位状态、Reservation、Order 和所有业务状态迁移。
3. PostgreSQL 是 MVP 阶段唯一正式数据源。
4. Redis、消息队列、WebSocket、多实例部署不进入当前核心 MVP 阶段。
5. 接口数量保持最小，以跑通完整预订闭环为目标。

## 2. MVP 接口范围与当前状态

接口状态必须区分“后端已经实现”和“当前前端已经实际调用”。

当前后端已经实现并完成 PostgreSQL、HTTP 与 Vite `/api` 读取链路验证：

```text
GET /events
GET /events/{eventId}
GET /events/{eventId}/sessions
GET /sessions/{sessionId}/seats
```

Phase 3 后端还已经实现并通过真实事务与并发测试：

```text
POST /reservations
```

当前 Vue 页面实际调用其中三个列表接口：

```text
GET /events
GET /events/{eventId}/sessions
GET /sessions/{sessionId}/seats
```

`GET /events/{eventId}` 已经是正式后端接口，但当前页面选择活动时仍复用
`GET /events` 返回的 `TicketEvent`，尚未调用活动详情接口。

后续阶段待实现：

```text
GET  /orders/{orderId}
POST /orders/{orderId}/pay
POST /orders/{orderId}/cancel
```

前端的 `expireOrderForDemo` 仅存在于 Mock 模式，不是正式后端接口。

## 3. JSON 命名规范

MVP 前后端 HTTP JSON 统一使用 camelCase。

例如：

```json
{
  "sessionId": "ses-concert-1001",
  "seatIds": [
    "ses-concert-1001-A01",
    "ses-concert-1001-A02"
  ]
}
```

当前前端 `POST /reservations` 已使用 `sessionId`、`seatIds`；Phase 3
后端继续接受这一 camelCase 请求体，不再引入 snake_case 变体。

后端响应统一使用：

```text
eventId
sessionId
seatIds
reservationId
totalAmount
expiresAt
createdAt
paidAt
```

## 4. API 响应格式

成功响应保持当前前端习惯，不增加统一的 `code/data/message` 外层包装。

列表接口直接返回数组，对象接口直接返回对象。

业务错误统一返回：

```json
{
  "code": "SEAT_CONFLICT",
  "message": "Selected seats are no longer available"
}
```

HTTP 状态码表达 HTTP 层错误类型；`code` 表达稳定业务错误类型。

当前只读后端已经使用：

```text
EVENT_NOT_FOUND
SESSION_NOT_FOUND
INTERNAL_ERROR
```

Phase 3 已确定继续使用：

```text
SEAT_CONFLICT
SESSION_NOT_FOUND
SESSION_NOT_AVAILABLE
IDEMPOTENCY_CONFLICT
INVALID_ARGUMENT
INTERNAL_ERROR
```

订单阶段还需要 `ORDER_NOT_FOUND`、`ORDER_NOT_PAYABLE`、
`ORDER_NOT_CANCELLABLE` 等错误语义。`Idempotency-Key` 缺失，以及同一个 Key
被用于不同 `sessionId / seatIds` 时返回 `409 IDEMPOTENCY_CONFLICT`。Session 存在
但不处于 `ON_SALE` 时返回 `409 SESSION_NOT_AVAILABLE`。

## 5. 时间规范

所有正式时间字段统一使用 ISO 8601，并带明确时区，推荐 UTC：

```text
2026-10-01T11:30:00Z
```

适用于：

```text
expiresAt
createdAt
paidAt
```

前端通过 `Date.parse(expiresAt)` 计算展示倒计时，但真正是否过期始终以后端数据库和订单状态为准。

场次中的 `date`、`time`、`weekday`、`gateTime` 在 MVP 中允许继续由后端返回格式化展示字符串，以减少前端改动。

## 6. 金额规范

数据库和 HTTP API 中所有正式金额统一使用整数“分”。

例如：

```text
128000
```

表示：

```text
¥1280.00
```

包括：

```text
price
priceFrom
totalAmount
```

禁止使用浮点数保存正式金额。

前端需要统一将金额除以 100 后展示。

MVP 默认币种为 CNY。

## 7. 用户身份

MVP 暂不实现完整登录、JWT 和用户系统。

当前前端固定使用 `U-1001`，建议通过请求头传递：

```text
X-User-Id: U-1001
```

后端从 Header 获取当前用户。

用户身份不放在 `POST /reservations` 请求体中，以避免业务请求任意指定其他用户身份。

Phase 3 后端 `POST /reservations` 已要求：

```text
Idempotency-Key: <unique logical reservation request key>
```

该 Header 标识“一次逻辑预订操作”，与 `X-User-Id` 共同确定请求幂等范围。
当前前端代码尚未生成或发送 `Idempotency-Key`；这是后续前端联调需要补齐的
契约，不能描述为已经落地的前端事实。

## 8. 前端对象与后端领域模型

前端对象不能直接一一映射为数据库表。

后端核心关系固定为：

```text
Event
  │
  ▼
Session
  │
  ▼
SessionSeat
  │
  ▼
Reservation
  │
  ▼
Order

Seat（物理座位） ─────► SessionSeat（场次库存）
```

其中 `SessionSeat` 是后端核心领域对象，前端无需直接感知。

## 9. Event 对齐

前端 TicketEvent 当前包含：

```text
id
name
description
city
venue
dateRange
status
cover
sessionCount
category
```

后端 Event 数据库主要保存真正业务字段，例如：

```text
id
name
description
city
venue
status
category
cover_url
created_at
```

`sessionCount` 可由 Session 数量聚合得到。

`dateRange` 可由 Session 时间范围计算；MVP 若为了降低实现成本，也可以暂时作为展示字段保存。

后端通过 DTO 组装成前端需要的 TicketEvent，不要求数据库字段与前端对象完全一致。

## 10. Session 对齐

前端 TicketSession 当前包含：

```text
id
eventId
date
time
weekday
venue
gateTime
status
priceFrom
availability
```

后端 Session 主要保存：

```text
id
event_id
venue
start_time
gate_time
status
```

`date`、`time`、`weekday` 可由 `start_time` 派生。

`priceFrom` 可根据该场次最低座位价格计算。

`availability` 属于展示字段，不作为核心业务状态。

## 11. Seat 与 SessionSeat 对齐

Seat 表示物理座位，例如“上海体育场 A01”。

主要保存：

```text
id
venue_id
row_no
seat_no
seat_label
zone
```

Seat 本身没有 `AVAILABLE / HELD / SOLD` 状态。

SessionSeat 表示某个具体场次中的某个具体座位，是系统真正的售票库存单位。

主要保存：

```text
id
session_id
seat_id
status
price
current_reservation_id
```

并保证：

```text
(session_id, seat_id)
```

唯一。

状态：

```text
AVAILABLE
HELD
SOLD
```

前端当前的 Seat DTO 实际是后端将物理 Seat 信息与 SessionSeat 状态、价格组合后的接口对象。

例如：

```json
{
  "id": "session-seat-id",
  "sessionId": "ses-concert-1001",
  "label": "A01",
  "row": "A",
  "number": 1,
  "status": "AVAILABLE",
  "zone": "星光区",
  "price": 128000
}
```

## 12. SELECTED 状态边界

`SELECTED` 永远不是后端状态。

后端正式座位状态只有：

```text
AVAILABLE
HELD
SOLD
```

用户点击 AVAILABLE 座位后，只修改浏览器本地 `selectedSeatIds`。

只有用户点击“提交预订”，且 `POST /reservations` 成功后，相应 SessionSeat 才正式从 AVAILABLE 进入 HELD。

## 13. Reservation 对齐

Reservation 表示一次临时资源占用。

后端主要保存：

```text
id
user_id
session_id
status
expires_at
created_at
```

并通过关联表记录该 Reservation 包含哪些 SessionSeat。

Phase 3 通过 `002_add_reservation_idempotency.sql` 新增：

```text
idempotency_key TEXT NULL
CHECK (idempotency_key IS NULL OR char_length(idempotency_key) BETWEEN 1 AND 128)
UNIQUE (user_id, idempotency_key)
```

`reservations.id` 继续作为单列主键；`user_id + idempotency_key` 是联合唯一约束，
不是联合主键。其业务含义是同一用户使用同一幂等键最多创建一条 Reservation，
不同用户可以使用相同 Key，同一用户也可以用不同 Key 发起不同预订。

已经验证过的 `001_initial_schema.sql` 不修改。现有 Seed Reservation 并非由真实
HTTP 请求创建，其 `idempotency_key` 保持 NULL；真实 POST 请求必须提供 1～128
字符的非空 Key。现有 `001` migration 与 Seed 不修改。

状态：

```text
ACTIVE
CONFIRMED
CANCELLED
EXPIRED
```

虽然当前 App 没有保存 currentReservation，但 `POST /reservations` 仍返回：

```json
{
  "reservation": {},
  "order": {}
}
```

当前 App 可以继续只保存 `order`；后端仍按 `ReservationResult` 返回完整的
`reservation + order`。

## 14. Order 对齐

后端 Order 主要保存：

```text
id
user_id
reservation_id
status
total_amount
expires_at
created_at
paid_at
```

状态：

```text
PENDING_PAYMENT
PAID
CANCELLED
EXPIRED
```

主要状态对应关系：

```text
Order PENDING_PAYMENT
Reservation ACTIVE
SessionSeat HELD
```

支付成功：

```text
Order PAID
Reservation CONFIRMED
SessionSeat SOLD
```

主动取消：

```text
Order CANCELLED
Reservation CANCELLED
SessionSeat AVAILABLE
```

超时：

```text
Order EXPIRED
Reservation EXPIRED
SessionSeat AVAILABLE
```

这些变化必须由后端事务统一完成。

## 15. POST /reservations Phase 3 契约

Headers：

```text
X-User-Id: U-1001
Idempotency-Key: <unique logical reservation request key>
```

Body：

```json
{
  "sessionId": "ses-concert-1001",
  "seatIds": [
    "ses-concert-1001-A01",
    "ses-concert-1001-A02"
  ]
}
```

用户身份由 `X-User-Id` 提供，不放入请求体；请求体也不包含价格或前端计算的
金额。`seatIds` 表示 `session_seats.id`，不是物理 `seats.id`。

`Idempotency-Key` 表示一次逻辑预订操作。相同用户、相同 Key、相同
`sessionId / seatIds` 的重试必须返回第一次创建的同一 Reservation 和 Order，
不能再创建第二份业务数据。用户主动重新选择座位并发起新预订时必须使用新 Key。

如果同一 Key 后续对应不同的 `sessionId` 或规范化后的 `seatIds`，后端必须返回
`409 IDEMPOTENCY_CONFLICT`，不能创建新订单。MVP 可以通过 `reservations.session_id` 与
`reservation_session_seats` 恢复首次请求的业务内容，不要求额外保存完整请求正文；
座位数组先按 `SessionSeat.id` 升序排序，因此相同集合的不同输入顺序属于同一请求。

Fast path 未命中后，事务先验证用户和 Session，再执行
`INSERT Reservation ... ON CONFLICT (user_id, idempotency_key) DO NOTHING RETURNING`。
只有返回 1 行的事务才继续锁 SessionSeat；返回 0 行时显式回滚并读取胜出事务的
完整结果。这样相同 Key 的并发重试在进入座位竞争前完成仲裁，不会退化为
`SEAT_CONFLICT`。

后端必须保证：

1. `X-User-Id` 和 `Idempotency-Key` 存在，`sessionId` 非空。
2. `seatIds` 数量为 1～6 且不重复。
3. 用户存在；Session 存在并且 `status = ON_SALE`，否则分别返回
   `INVALID_ARGUMENT`、`SESSION_NOT_FOUND` 或 `SESSION_NOT_AVAILABLE`。
4. 实际取得的 SessionSeat 数量等于请求数量，且全部属于 `sessionId`。
5. 锁定后的全部 SessionSeat 仍为 AVAILABLE。
6. 多个座位整体成功或整体失败。
7. Reservation、SessionSeat、关联表和 Order 在同一事务中创建或更新。
8. `totalAmount` 由数据库价格快照计算，不能相信前端金额。

成功返回 ReservationResult：

```json
{
  "reservation": {
    "id": "RSV-10001",
    "userId": "U-1001",
    "sessionId": "ses-concert-1001",
    "seatIds": [
      "ses-concert-1001-A01",
      "ses-concert-1001-A02"
    ],
    "status": "ACTIVE",
    "expiresAt": "2026-10-01T11:45:00Z",
    "createdAt": "2026-10-01T11:30:00Z"
  },
  "order": {
    "id": "TKT-10001",
    "reservationId": "RSV-10001",
    "eventId": "evt-concert-2026",
    "sessionId": "ses-concert-1001",
    "seatIds": [
      "ses-concert-1001-A01",
      "ses-concert-1001-A02"
    ],
    "status": "PENDING_PAYMENT",
    "totalAmount": 256000,
    "expiresAt": "2026-10-01T11:45:00Z",
    "createdAt": "2026-10-01T11:30:00Z"
  }
}
```

## 16. GET /orders/{orderId} 契约

返回完整 TicketOrder，至少包含：

```text
id
reservationId
eventId
sessionId
seatIds
status
totalAmount
expiresAt
createdAt
paidAt
```

当前不要求 Order API 返回完整活动、场次和座位展开对象。

浏览器刷新后恢复完整订单页面属于后续前端增强，不阻塞 MVP。

## 17. 支付和取消契约

### 支付

```text
POST /orders/{orderId}/pay
```

无请求体。

成功后返回更新后的 TicketOrder。

后端在同一事务中执行：

```text
Order -> PAID
Reservation -> CONFIRMED
SessionSeat -> SOLD
```

如果订单已经 PAID，可按幂等语义直接返回当前 PAID Order。

如果订单已经 CANCELLED 或 EXPIRED，返回：

```text
ORDER_NOT_PAYABLE
```

### 取消

```text
POST /orders/{orderId}/cancel
```

无请求体。

成功后返回更新后的 TicketOrder。

后端在同一事务中执行：

```text
Order -> CANCELLED
Reservation -> CANCELLED
SessionSeat -> AVAILABLE
```

如果订单已经 PAID 或 EXPIRED，返回：

```text
ORDER_NOT_CANCELLABLE
```

## 18. 每单最多选择座位数

当前前端限制最多选择 6 个座位。

MVP 后端必须使用相同限制，不能只依赖前端校验。

固定：

```text
MAX_SEATS_PER_RESERVATION = 6
```

超出时返回：

```text
INVALID_ARGUMENT
```

## 19. 当前前端事实与 Phase 3 联调差异

当前前端已经完成：

1. `POST /reservations` 请求体使用 `sessionId`、`seatIds`。
2. `price`、`priceFrom`、`totalAmount` 按整数“分”处理并统一格式化。
3. Axios 按 `code + message` 解析业务错误。
4. 请求统一携带 `X-User-Id: U-1001`。
5. 预订失败刷新座位、支付结果未知刷新订单时会保留原错误提示。

当前前端尚未生成或发送 `Idempotency-Key`。Phase 3 联调前需要为每次新的逻辑
预订操作生成新 Key，并在网络重试时复用同一 Key；不能修改本文去声称这项能力
已经存在于当前代码。

继续暂缓：Vue Router、保存 `currentReservation`、刷新浏览器后恢复订单详情、
WebSocket 和页面结构重构。`GET /events/{eventId}` 后端已实现，但当前页面仍不调用。

## 20. 后端开发阶段划分

### Phase 1：工程与数据库基础（已完成）

C++20、Drogon、CMake、Docker Compose、PostgreSQL Schema 和稳定 Demo Seed
已经建立并通过真实初始化与运行验证。

### Phase 2：四个只读接口（已完成）

```text
GET /events
GET /events/{eventId}
GET /events/{eventId}/sessions
GET /sessions/{sessionId}/seats
```

已经完成 PostgreSQL 真实查询、C++/Docker/HTTP 集成测试和 Vite `/api` 真实读取链路。

### Phase 3：Reservation（后端已完成）

```text
POST /reservations
```

已完成请求幂等、多座位固定顺序原子锁座、Reservation / Order 同事务创建、
价格快照、失败回滚和真实并发正确性测试。当前前端尚未发送 `Idempotency-Key`，
所以前端真实 POST 联调仍留到后续阶段。

### Phase 4：订单查询与超时释放（待实现）

```text
GET /orders/{orderId}
后台过期释放 Worker
```

### Phase 5：支付与取消（待实现）

```text
POST /orders/{orderId}/pay
POST /orders/{orderId}/cancel
```

重点处理支付、取消、超时对同一订单的状态竞争。

### Phase 6：完整可靠性验证（待实现）

覆盖完整并发、故障、提交结果不确定、Worker 批处理和服务重启恢复测试。

### Phase 7：可选高并发增强（暂缓）

根据实际瓶颈选择 Redis 页面软占用与缓存、WebSocket、多实例和消息队列；
这些能力不能替代 PostgreSQL 的正式库存并发控制。

## 21. 当前阶段边界

核心 MVP 当前不加入：

```text
Redis
Kafka
RabbitMQ
WebSocket
Nginx 多实例
Prometheus
Grafana
Kubernetes
真实支付平台
退款
优惠券
完整认证系统
```

## 22. 最终对齐原则

整个 MVP 统一遵循：

```text
前端：
展示
交互
本地点选
倒计时展示

        ↓ HTTP

后端：
正式状态判断
Reservation
Order
支付
取消
超时处理

        ↓

PostgreSQL：
最终业务事实
事务
并发控制
数据完整性
```

特别需要始终保持：

```text
SELECTED
```

只是浏览器本地选择；

```text
HELD
```

才代表后端已经成功创建正式临时预订。
