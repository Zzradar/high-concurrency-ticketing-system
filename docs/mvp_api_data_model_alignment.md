# 高并发票务预订系统 MVP 接口与数据模型对齐方案

## 1. 文档目的

本文用于统一当前 Vue 3 前端 Demo 与后续 C++20 + Drogon + PostgreSQL 后端之间的接口契约和数据模型边界。

本文主要依据：

- 当前前端实际代码整理出的《前端接口契约文档》
- 已确定的《高并发票务预订系统 MVP 技术方案》

目标不是重新设计前端，而是在后端正式开发前，把容易导致返工的关键约定先固定下来。

MVP 阶段遵循以下原则：

1. 前端负责展示、交互和本地临时选择状态。
2. 后端负责正式座位状态、Reservation、Order 和所有业务状态迁移。
3. PostgreSQL 是 MVP 阶段唯一正式数据源。
4. Redis、消息队列、WebSocket、多实例部署暂不进入 MVP 第一阶段。
5. 接口数量保持最小，以跑通完整预订闭环为目标。

## 2. MVP 固定接口范围

当前前端实际需要 7 个后端接口，MVP 第一阶段不额外扩展接口。

```text
GET  /events
GET  /events/{eventId}/sessions
GET  /sessions/{sessionId}/seats
POST /reservations
GET  /orders/{orderId}
POST /orders/{orderId}/pay
POST /orders/{orderId}/cancel
```

当前前端没有使用 `GET /events/{eventId}`，因此 MVP 暂不实现。

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

当前前端 `POST /reservations` 使用 `session_id`、`seat_ids`，正式联调前修改为 `sessionId`、`seatIds`。

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

MVP 至少定义：

```text
SEAT_CONFLICT
SESSION_NOT_FOUND
ORDER_NOT_FOUND
ORDER_NOT_PAYABLE
ORDER_NOT_CANCELLABLE
ORDER_EXPIRED
INVALID_ARGUMENT
```

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

## 8. 前端对象与后端领域模型

前端对象不能直接一一映射为数据库表。

后端领域模型固定为：

```text
Event
  │
  ▼
Session
  │
  ▼
Seat
  │
  ▼
SessionSeat
  │
  ▼
Reservation
  │
  ▼
Order
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

前端第一阶段可以继续只保存 `order`。

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

## 15. POST /reservations 最终契约

请求：

```json
{
  "sessionId": "ses-concert-1001",
  "seatIds": [
    "session-seat-id-A01",
    "session-seat-id-A02"
  ]
}
```

用户身份由请求上下文提供，不放入请求体。

后端必须保证：

1. 所有 seatIds 均属于同一个 sessionId。
2. 选择数量符合 MVP 限制。
3. 所有座位仍为 AVAILABLE。
4. 多个座位整体成功或整体失败。
5. Reservation、Order、SessionSeat 状态在同一事务中完成。
6. totalAmount 由后端根据数据库价格计算，不能相信前端金额。

成功返回 ReservationResult：

```json
{
  "reservation": {
    "id": "RSV-10001",
    "userId": "U-1001",
    "sessionId": "ses-concert-1001",
    "seatIds": [
      "session-seat-id-A01",
      "session-seat-id-A02"
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
      "session-seat-id-A01",
      "session-seat-id-A02"
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

## 19. 前端联调前需要完成的小修改

正式开发后端前，前端只需要做少量契约收敛，不需要重构页面。

必须修改：

1. `POST /reservations` 请求字段统一为 `sessionId`、`seatIds`。
2. 正式金额统一按“分”处理，并增加统一金额格式化。
3. 真实 Axios 错误解析统一业务错误结构 `code + message`。
4. 请求统一携带 `X-User-Id: U-1001`。

建议顺手修复：

- 预订失败后错误提示可能被刷新座位流程清空。
- 支付结果未知时提示可能被订单刷新流程清空。

暂不修改：

- 不引入 Vue Router。
- 不保存 currentReservation。
- 不支持浏览器刷新后恢复订单详情。
- 不增加 GET /events/{eventId}。
- 不实现 WebSocket。
- 不修改现有页面结构。

## 20. 后端开发阶段划分

### 阶段一：工程和数据库骨架

完成：

```text
C++20
Drogon
PostgreSQL
CMake
Docker Compose
```

建立核心数据库 Schema 和 Seed 数据。

### 阶段二：只读接口

先完成：

```text
GET /events
GET /events/{eventId}/sessions
GET /sessions/{sessionId}/seats
```

关闭对应前端 Mock，完成第一次真实前后端联调。

### 阶段三：Reservation

单独设计和实现：

```text
POST /reservations
```

重点验证：

- 多座位原子预订。
- 并发竞争。
- 数据库事务。
- 统一锁顺序。
- 失败回滚。
- Reservation 与 Order 同时创建。

### 阶段四：支付和取消

实现：

```text
GET /orders/{orderId}
POST /orders/{orderId}/pay
POST /orders/{orderId}/cancel
```

建立完整订单状态机。

### 阶段五：超时释放

增加后台 Worker，处理：

```text
PENDING_PAYMENT
+
expires_at <= now
```

并执行：

```text
Order -> EXPIRED
Reservation -> EXPIRED
SessionSeat -> AVAILABLE
```

### 阶段六：并发正确性测试

重点验证：

1. 大量用户竞争一个座位只能成功一个。
2. 多座位交叉竞争不能部分成功。
3. 同一个座位不能属于两个有效 Reservation。
4. 支付和超时竞争不会产生非法状态。
5. 已支付座位不会重新 AVAILABLE。
6. 取消和超时能够可靠释放座位。

## 21. MVP 边界

MVP 第一阶段明确不加入：

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
