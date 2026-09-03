# 高并发票务预订系统 MVP 技术方案

## 1. 技术方案目标

本阶段目标不是一次性完成完整高并发票务平台，而是先实现一个业务闭环完整、并发语义正确、后续可自然演进的 MVP。

MVP 重点解决以下问题：

1. 一个场次下的具体座位如何建模和查询。
2. 多个用户并发预订同一座位时，如何保证不会重复售卖。
3. 用户一次选择多个座位时，如何保证全部成功或全部失败。
4. 锁座后如何进入待支付状态，并支持支付、取消和超时释放。
5. 服务重启后，如何继续处理已经超时但尚未释放的订单。
6. 如何通过并发测试验证系统的核心业务不变量。

本阶段不追求复杂微服务架构，也不引入消息队列和实时推送。Phase 7 已增加 Redis
临时占座，但核心原则不变：正式库存仍由关系数据库事务保证正确。

---

## 2. 技术栈

### 2.1 后端语言

使用 **C++20**。

选择 C++ 的主要原因是：

- 能发挥现有 C++ 后端基础，同时避免再次把项目做成单纯的底层组件项目。
- 本项目核心问题集中在并发、事务、资源状态和后续性能优化，C++ 可以很好承载这些场景。
- MVP 业务范围可控，因此 C++ 相比 Java 带来的业务开发效率劣势可以接受。
- 后续可以自然扩展到多实例、缓存、实时通信和性能压测，形成较有辨识度的 C++ 业务后端项目。

### 2.2 Web 框架

使用 **Drogon**。

Drogon 负责：

- HTTP 服务。
- REST API 路由。
- 请求参数解析。
- JSON 响应。
- 异步请求处理。
- 数据库连接能力。
- 后续 WebSocket 扩展。

MVP 不自行实现 HTTP Server、Reactor、线程池等基础设施，避免把时间再次花在底层框架建设上。

### 2.3 数据库

使用 **PostgreSQL**。

PostgreSQL 是 MVP 中最重要的基础设施，负责保存全部正式业务状态，包括：

- 活动。
- 场次。
- 物理座位。
- 场次座位。
- 预订。
- 订单。
- 订单与座位关联关系。

同时，PostgreSQL 负责保证核心业务正确性：

- 数据库事务保证多座位整体成功或整体失败。
- 行级竞争控制保证同一个座位不能被两个有效预订同时占用。
- 唯一约束作为最终数据完整性保护。
- 条件更新保证订单状态迁移不会被并发流程相互覆盖。

MVP 阶段数据库是唯一正式数据源。

### 2.4 构建与依赖管理

使用：

- **CMake**：项目构建。
- **Docker Compose**：本地启动 PostgreSQL、Redis 和后端服务。
- **GoogleTest**：核心业务逻辑和并发场景测试。
- Drogon 自带日志能力或 **spdlog**：运行日志。

---

## 3. 总体架构

MVP 采用模块化单体结构。

```text
Client
  │
  ▼
Drogon HTTP Server
  │
  ├── Event Module
  ├── Session Module
  ├── Seat Module
  ├── Reservation Module
  ├── Checkout Session Module ── Redis 临时占座
  └── Order Module
          │
          ▼
      PostgreSQL（正式业务事实）

Background Worker
  │
  └── 扫描超时订单并释放座位
```

MVP 不拆微服务。

原因是当前最重要的问题是验证预订模型和并发正确性，而不是服务治理。模块化单体既能保持清晰的业务边界，也能减少服务发现、远程调用、分布式事务和部署带来的额外复杂度。

### 3.1 当前实施状态

本文同时记录已落地事实与后续设计，两者不能混为一谈：

```text
Phase 1  工程骨架 + PostgreSQL Schema + Seed                 已完成
Phase 2  四个只读接口 + PostgreSQL 查询 + Vite /api 链路    已完成
Phase 3  POST /reservations + 幂等 + 原子锁座                已完成
Phase 4  GET /orders/{orderId} + 超时释放 Worker             已完成
Phase 5  服务端 Checkout Session（购票会话）                已完成
Phase 6  前端购票会话恢复与独立多会话                        已完成
Phase 7  Redis 临时占座                                      已完成
Phase 8  支付 + 取消 + 支付/取消/超时状态竞争                待实现
Phase 9  按压测决定限流/排队/异步受理/操作查询               暂缓
```

当前后端已经实现并验证：

```text
GET /events
GET /events/{eventId}
GET /events/{eventId}/sessions
GET /sessions/{sessionId}/seats
POST /reservations
GET /orders/{orderId}
POST /checkout-sessions
GET /checkout-sessions/{id}
GET /checkout-sessions?sessionId=...&recoverable=true
PUT /checkout-sessions/{id}/seats
POST /checkout-sessions/{id}/confirm
POST /checkout-sessions/{id}/abandon
```

当前 Vue 页面实际调用活动列表、活动场次列表、场次座位图和全部 CheckoutSession 接口，
尚未调用已经存在的 `GET /events/{eventId}`。Phase 3 后端预订能力与 Phase 4 订单查询、超时释放 Worker
已经完成；Phase 7 的 Redis 临时占座和带 CheckoutSession 上下文的座位图也已完成；
支付和取消能力仍未实现。

---

## 4. 核心领域模型

### 4.1 Event

表示一个活动，例如演唱会、电影或体育赛事。

主要字段：

- id
- name
- description
- status
- created_at

### 4.2 Session

表示一个活动下的具体场次。

主要字段：

- id
- event_id
- venue_name
- start_time
- status

一个 Event 可以对应多个 Session。

### 4.3 Seat

表示场馆中的物理座位。

主要字段：

- id
- venue_id
- row_no
- seat_no
- seat_label

Seat 本身不保存“已售”状态。

### 4.4 SessionSeat

表示某个具体场次中的一个具体座位，是系统真正的库存单位。

主要字段：

- id
- session_id
- seat_id
- status
- current_reservation_id

状态：

- AVAILABLE：可预订
- HELD：临时锁定
- SOLD：已售

需要保证：

- `(session_id, seat_id)` 唯一。

这样同一个物理座位可以在不同场次重复出售，但在同一场次只对应一个库存单元。

### 4.5 Reservation

表示一次临时座位预订。

主要字段：

- id
- user_id
- session_id
- status
- expires_at
- created_at

状态：

- ACTIVE
- CONFIRMED
- CANCELLED
- EXPIRED

Reservation 与多个 SessionSeat 关联。

Phase 3 通过 `002_add_reservation_idempotency.sql` 为 Reservation 增加可空的
`idempotency_key TEXT`、1～128 字符检查，以及
`(user_id, idempotency_key)` 联合唯一约束。
`reservations.id` 仍是主键；联合唯一约束只是限制同一用户的同一逻辑请求最多
创建一条 Reservation，不会把两个字段改成主键。已验证的
`001_initial_schema.sql` 与现有 Seed 不修改，Seed Reservation 未来允许没有幂等键。
真实 `POST /reservations` 必须提供非空幂等键；旧 Seed 行继续使用 NULL。

### 4.6 Order

表示用户锁座成功后生成的订单。

主要字段：

- id
- user_id
- reservation_id
- status
- total_amount
- expires_at
- created_at
- paid_at

状态：

- PENDING_PAYMENT
- PAID
- CANCELLED
- EXPIRED

MVP 阶段支付采用模拟接口，不接第三方支付平台。

### 4.7 CheckoutSession 与 CheckoutSessionSeat

Phase 5 的 `checkout_sessions` 保存用户针对一个 Session 的本轮购买流程，状态为
`SELECTING / SUBMITTING / RESERVED / ABANDONED`。它保存服务端确认键和可空的
`reservation_id`，不保存 `order_id` 或短期 `expires_at`。

`checkout_session_seats` 保存当前完整购买意图。关联必须与购票会话属于同一
Session，且每个座位在一个会话中只出现一次。这些行不代表 `HELD`；正式库存状态仍只由 Phase 3 事务修改。

`checkout_sessions.revision` 是座位完整集合版本，初始为 0。每次成功 PUT（包括相同集合）
在行锁事务中原子加 1；请求必须携带 `expectedRevision`。锁后版本不一致返回
`409 CHECKOUT_SESSION_VERSION_CONFLICT`，且不修改座位关联。状态迁移和对账不增加 revision。

Phase 7 复用 revision 作为 Redis Hold 的 fencing version。Redis Hold 只代表
`SELECTING` 阶段的短期竞争，不把 `checkout_session_seats` 或 PostgreSQL
`session_seats` 改成正式 `HELD`；正式 Reservation 仍由 Phase 3 事务创建。

---

## 5. 核心业务流程

### 5.1 查看活动和场次

用户查询活动列表，然后进入活动详情，选择具体场次。

这一阶段为普通查询操作，不涉及复杂并发控制。

### 5.2 查看座位图

用户查询某个 Session 的所有 SessionSeat。

返回：

- 座位编号。
- 座位状态。
- 是否可选择。

基础座位状态直接从 PostgreSQL 查询。Phase 7 再批量读取 Redis live Hold：PostgreSQL
已经是 HELD/SOLD 时保持正式状态；PostgreSQL AVAILABLE 且被其他 CheckoutSession
临时占座时在响应中表现为 HELD；当前 CheckoutSession 自己的 Hold 仍表现为 AVAILABLE。
Redis 读取失败时退化为纯 PostgreSQL 座位图，不影响接口成功。当前不引入 Redis
座位图缓存或 WebSocket。

### 5.3 提交座位预订

Phase 3 的 `POST /reservations` 接收 `X-User-Id`、`Idempotency-Key`，以及只包含
`sessionId / seatIds` 的请求体。`seatIds` 是 `session_seats.id`，不是物理
`seats.id`；请求不携带用户 ID、价格或总金额。

第一层先做不需要数据库锁的结构校验：

```text
X-User-Id 存在
Idempotency-Key 存在
sessionId 非空
seatIds 数量为 1～6
seatIds 不重复
```

之后可以按 `(user_id, idempotency_key)` 查询已完成结果。已经存在且业务请求一致
时，返回原来的 Reservation + Order；同一 Key 对应不同 `sessionId / seatIds`
时返回 `409 IDEMPOTENCY_CONFLICT`。

新请求的全部数据库步骤必须使用同一个 Drogon Transaction 对象：

1. 验证用户存在，再查询 Session，确认存在且 `status = ON_SALE`，但不锁 Session 行。
2. 先用 `INSERT Reservation ... ON CONFLICT (user_id, idempotency_key) DO NOTHING RETURNING ...` 取得唯一幂等执行资格。
3. INSERT 返回 0 行时回滚当前事务，通过普通 DbClient 读取胜出事务的完整结果；请求一致返回 200，不一致返回 `IDEMPOTENCY_CONFLICT`。
4. 只有 INSERT 返回 1 行的执行者，才按 `SessionSeat.id` 升序取得目标 `session_seats` 的行级更新锁。
5. 基于锁定后的最新数据确认取得数量等于请求数量、全部属于指定 Session、状态全部为 AVAILABLE，并读取正式价格。
6. 将全部 SessionSeat 从 AVAILABLE 更新为 HELD，并写入 `current_reservation_id`。
7. 写入 `reservation_session_seats`，把锁座时价格保存为 `reserved_price` 快照。
8. 以全部 `reserved_price` 之和创建 PENDING_PAYMENT Order，并复用同一个 `expires_at`。
9. 提交事务；确认 COMMIT 成功后才返回 `ReservationResult`。

这些 SQL 不是多个 HTTP 请求，也不能分别通过普通连接池客户端执行。最后一条
INSERT 成功不代表整个事务已成功；任一步失败或 COMMIT 失败都必须回滚，不能向
客户端返回成功。实际 Drogon 1.9.13 使用 `newTransactionAsync` 创建事务，
`setCommitCallback` 接收最终提交结果；Transaction 没有公开 `commit()`，最后一个
引用释放时析构并提交。实现只在所有 SQL 成功后设置 commit callback，再清空共享
状态中的 Transaction 引用，既触发实际 COMMIT，也打断 shared_ptr 环。

数据库行锁与 HELD 是不同概念：行锁只在事务执行期间存在并在提交/回滚后释放；
HELD 是可持续约 15 分钟的正式业务状态。事务提交后行锁已经释放，但座位继续保持
HELD，直到支付、取消或超时释放流程改变业务状态。

---

## 6. 并发预订方案

### 6.1 请求幂等与座位竞争是两个问题

请求幂等处理同一次逻辑操作因网络超时、响应丢失、客户端重试或重复点击而被多次
发送的问题。例如第一次请求已经成功但客户端未收到响应，使用同一
`Idempotency-Key` 重试时不能再创建第二份 Reservation / Order。

座位竞争处理不同合法请求争抢同一库存的问题。例如：

```text
用户甲：A01 + A02
用户乙：A02 + A03
```

两者本来就是不同业务操作，幂等键不能解决对 A02 的竞争；该问题必须由
PostgreSQL 事务和 SessionSeat 行锁解决。

### 6.2 幂等的应用层快速路径与数据库最终保护

应用层可以先查询 `(user_id, idempotency_key)`，快速返回已经完成的相同请求。
但不能只依赖“先 SELECT、再 INSERT”，因为两个并发重试都可能查询到不存在，
随后同时插入。

最终保护和并发仲裁是 PostgreSQL 的 `(user_id, idempotency_key)` 联合唯一约束：

```text
U-1001 + key-A  合法
U-1001 + key-B  合法
U-2001 + key-A  合法
再次插入 U-1001 + key-A  被唯一约束拒绝
```

新事务必须先执行 `INSERT ... ON CONFLICT DO NOTHING RETURNING`。返回 1 行的事务获得
唯一执行资格后才锁座；返回 0 行的事务不锁座、不创建 Order，显式回滚后读取胜出
事务已经提交的 Reservation + Order。相同请求返回原结果；同一个 Key 对应不同
`sessionId / sorted seatIds` 时返回 `409 IDEMPOTENCY_CONFLICT`。不采用先锁座、最后
INSERT 再捕获唯一异常的主流程，也不引入进程内 mutex、advisory lock、Redis lock
或 Serializable 隔离级别完成同一件事。

### 6.3 多座位主方案选择

只使用带 `status = 'AVAILABLE'` 条件的 UPDATE 并检查受影响行数，是主流且正确的
并发写法，尤其适合单个库存数字或简单单资源竞争，不应被描述为错误方案。

当前一次预订最多包含 6 个具体座位，还必须校验 Session 归属、读取价格、保存价格
快照、创建 Reservation 与 Order，并保证全部成功或全部失败。因此 Phase 3 不把
“仅依靠条件更新”作为主要方案，而选择：

```text
SELECT ... FOR UPDATE（或等价行级更新锁）
→ 读取锁定后的最新状态与价格
→ 全部校验通过
→ 统一更新
```

只要一个座位不存在、属于其他 Session 或已经不是 AVAILABLE，整个事务失败，
禁止部分座位成功。

### 6.4 锁定对象和固定顺序

竞争对象是 `session_seats`，不是物理 `seats`。所有请求都按
`SessionSeat.id` 升序取得行锁，不能沿用客户端随机提交顺序。例如客户端传入
A03、A01、A02，实际锁定顺序仍为 A01、A02、A03。

固定顺序降低多座位事务循环等待和死锁概率。PostgreSQL 能检测死锁，但死锁检测
不应成为正常业务并发策略。

### 6.5 当前不锁整个 Session

Session 当前只用于确认存在并且 `status = ON_SALE`。MVP 尚无管理员并发关售接口，
因此每次预订不获取 Session 行锁。热门场次的所有请求都指向同一 Session；如果购买
互不冲突座位的用户也先锁同一行，会人为形成场次级串行瓶颈。

当前只锁真正竞争的 SessionSeat。以后增加管理员实时关售时，再单独设计“关售与
正在创建 Reservation”的并发关系。

### 6.6 价格、过期时间与完整状态提交

价格只相信锁定后的 `session_seats.price`。该值写入
`reservation_session_seats.reserved_price` 后成为订单价格快照，后续库存价格变化
不会影响已有订单；`orders.total_amount` 等于全部快照价格之和。

Reservation 与 Order 使用数据库当前时间一次计算出的同一个 15 分钟截止时间。
正式是否过期以后端数据库时间为准，浏览器倒计时只用于展示。

成功事务必须一起提交：

```text
Reservation ACTIVE
SessionSeat AVAILABLE → HELD，并指向 Reservation
reservation_session_seats 保存关联和 reserved_price
Order PENDING_PAYMENT
```

禁止先提交 Reservation 再创建 Order，否则可能形成座位已经 HELD 但没有订单的
孤立状态。现有 `(session_id, seat_id)` 唯一约束、Reservation 与 Order 一对一约束、
外键和状态检查继续作为应用逻辑之外的最终数据保护。

---

## 7. 订单状态管理

订单状态采用明确状态机。

允许的主要状态转换：

```text
PENDING_PAYMENT
  ├── PAID
  ├── CANCELLED
  └── EXPIRED
```

已经进入以下状态的订单：

```text
PAID
CANCELLED
EXPIRED
```

不能再次被修改成其他终态。

状态迁移必须通过数据库并发控制完成。例如支付操作只能处理：

```text
当前状态仍然是 PENDING_PAYMENT 的订单
```

这样可以防止支付、取消和超时流程相互覆盖。Phase 4 已建立长期锁顺序：先锁
Order，再锁 Reservation，最后按 `SessionSeat.id` 升序锁 SessionSeat。未来支付和
取消实现必须沿用该顺序，并以 Order 作为终态竞争的第一仲裁点。

支付接口必须自行使用数据库时间判断 `current_time >= expires_at`，不能依赖 Worker
已经先把订单改成 EXPIRED 才识别过期。`expires_at` 是时间上的正式业务事实，Worker
负责最终把关联状态清理一致。

---

## 8. 模拟支付

MVP 提供模拟支付接口。

用户调用支付接口后：

1. 开启数据库事务。
2. 检查订单当前状态是否仍为 PENDING_PAYMENT。
3. 检查订单是否尚未过期。
4. 将 Order 更新为 PAID。
5. 将 Reservation 更新为 CONFIRMED。
6. 将对应 SessionSeat 从 HELD 更新为 SOLD。
7. 提交事务。

支付操作必须保证订单状态、Reservation 状态和座位状态同时成功修改。

---

## 9. 主动取消

用户可以取消尚未支付的订单。

取消过程在一个数据库事务中完成：

1. Order：PENDING_PAYMENT → CANCELLED。
2. Reservation：ACTIVE → CANCELLED。
3. 对应 SessionSeat：HELD → AVAILABLE。
4. 清空座位与 Reservation 的关联。

已经 PAID 的订单不能通过 MVP 普通取消接口取消。

退款属于后续版本能力。

---

## 10. 超时订单处理（Phase 4）

Phase 4 已在模块化单体中实现独立的过期释放 Worker。系统不使用每个订单单独创建
进程内定时器的方式。

原因是应用一旦重启，内存定时器就会全部丢失。

每张待支付订单直接在数据库中保存：

```text
expires_at
```

后台 Worker 周期性按批次扫描：

```text
status = PENDING_PAYMENT
AND expires_at <= 数据库当前时间
```

实际候选查询按 `expires_at ASC, id ASC` 排序并使用可配置 `batch_size`；默认值为
100。每个候选 Order 使用独立事务，先以 `FOR UPDATE SKIP LOCKED` 锁 Order 并重新
检查状态和数据库时间，再依次锁 Reservation 和按 ID 升序排列的 SessionSeat。

全部正式关联座位必须仍为 HELD，且 `current_reservation_id` 必须指向目标
Reservation。校验通过后，在同一数据库事务中：

1. Order → EXPIRED。
2. Reservation → EXPIRED。
3. SessionSeat：HELD → AVAILABLE。
4. SessionSeat.current_reservation_id → NULL。

因为过期时间持久化在数据库中，所以应用停止后重新启动，仍然能够继续清理之前
已经超时的订单。不能把“只有新订单请求到来时才顺便清理旧订单”作为主方案；
突发票务流量可能产生集中到期，清理工作不能转嫁给后续用户请求。

Worker 通过 Drogon `registerBeginningAdvice` 在应用启动后立即执行一轮，本轮异步
处理全部完成后，再由 `getLoop()->runAfter()` 等待可配置周期（默认 5 秒）并启动
下一轮，因此同一 Worker 不会发生轮次重叠。`FOR UPDATE SKIP LOCKED` 已通过双后端
实例竞争同一过期 Order 的测试；这是本项目的 PostgreSQL 工程选择。

座位释放还会比较正式关联数量与实际更新数量；任何状态、所有权或数量不变量失败，
当前 Order 的事务都会回滚并记录 ERROR，批次继续处理下一张订单。详细实现见
[Phase 4 订单过期专项设计](order_expiry_design.md)。

---

## 11. 接口实施范围

已完成并验证：

```text
GET /events
GET /events/{eventId}
GET /events/{eventId}/sessions
GET /sessions/{sessionId}/seats
POST /reservations
GET /orders/{orderId}
```

Phase 4 后台能力已完成并验证：

```text
订单超时释放 Worker
```

Phase 8 待实现：

```text
POST /orders/{orderId}/pay
POST /orders/{orderId}/cancel
```

前端 `expireOrderForDemo` 是 Mock-only 行为，不是后端接口。管理端功能不是 MVP
重点；活动、场次和座位继续由现有 Schema 与稳定 Seed 提供。

---

## 12. 测试方案

MVP 不能只验证接口能否返回 200，还必须验证业务不变量。

### 12.1 单座位并发竞争

准备一个座位 A01。

同时发送大量预订请求。

最终必须满足：

- 只有一个请求成功。
- 只能存在一个有效 Reservation。
- A01 只能属于一个有效订单。

### 12.2 多座位交叉竞争

准备：

```text
A01
A02
A03
```

同时执行：

```text
用户甲：A01 + A02
用户乙：A02 + A03
```

必须保证只有一组成功。

不能出现 A02 同时属于两个有效 Reservation。

### 12.3 相同幂等键并发重试

同一用户使用同一个 `Idempotency-Key`、相同 `sessionId` 和相同 `seatIds` 并发发送。

最终必须满足：

- 只有一条 Reservation。
- 只有一条 Order。
- 重复请求获得同一业务结果，而不是座位冲突或新订单。
- 同一个 Key 改为其他 Session 或座位时返回 `IDEMPOTENCY_CONFLICT`。

### 12.4 数据库不变量

除 HTTP 响应外，还要直接查询数据库验证：

```text
HELD SessionSeat 只能指向一个 Reservation
一个 Reservation 最多一个 Order
Order.total_amount = 对应 reserved_price 之和
Reservation 与 Order 的 expires_at 一致
失败事务没有残留 Reservation、HELD 座位或孤立 Order
```

### 12.5 测试数据隔离

现有 Seed 保留为稳定 Demo 基线，其中已有 AVAILABLE、HELD、SOLD、Reservation、
Order 和真实关联数据。并发测试不能反复污染这些记录。

每轮测试使用专门的测试座位和用户，并在开始前恢复目标 SessionSeat 为 AVAILABLE、
清理上一轮测试创建的 Order、Reservation 和关联记录。这样 Demo 数据保持稳定，
并发场景可以确定性重复执行。

### 12.6 取消释放

用户成功锁定 A01 后取消订单。

需要验证：

- Order 进入 CANCELLED。
- Reservation 进入 CANCELLED。
- A01 恢复 AVAILABLE。
- 其他用户之后可以重新预订 A01。

### 12.7 超时释放

创建一个支付时间较短的订单。

等待其过期。

需要验证后台 Worker 最终：

- 把订单修改为 EXPIRED。
- 把 Reservation 修改为 EXPIRED。
- 释放所有 HELD 座位。

### 12.8 支付、取消与超时竞争

让支付、取消操作与超时任务尽可能同时处理同一订单。

最终只能产生一个合法结果：

- PAID + CONFIRMED + SOLD。
- CANCELLED + CANCELLED + AVAILABLE。
- 或 EXPIRED + EXPIRED + AVAILABLE。

不能出现：

- PAID + AVAILABLE。
- EXPIRED + SOLD。

### 12.9 服务重启恢复

创建即将超时的订单后停止服务。

等待订单超过 expires_at，再重新启动服务。

后台 Worker 应能够识别并释放这个历史超时订单。

---

## 13. 当前暂不实现的能力

当前 Phase 3 及核心正确性验证阶段明确不实现：

- Redis 座位图缓存。
- Redis 分布式锁。
- Redis 限流。
- Kafka / RabbitMQ。
- WebSocket 实时座位推送。
- 多后端实例。
- Nginx 负载均衡。
- Prometheus / Grafana。
- Kubernetes。
- 第三方真实支付。
- 退款。
- 优惠券。
- 推荐系统。
- 复杂后台管理系统。

这些能力都不影响使用 PostgreSQL 事务验证核心预订模型。Phase 7 的 Redis 只用于
SELECTING 阶段的临时竞争，不是缓存、分布式锁或正式库存来源。

---

## 14. 后续演进方向

### 购票会话与长期调用链

Phase 5 已引入服务端 Checkout Session（购票会话），作为某个用户针对一个具体场次
的一轮连续购票过程的稳定身份。第一次真实选座时直接用首版完整座位集创建，
纯浏览不创建。一个用户可以同时拥有多个独立购票会话。

长期调用链为：

```text
购票会话
↓
选座
↓
Redis 临时占座
↓
确认购票会话
↓
复用现有 Phase 3 ReservationService / 正式 Reservation 事务
↓
Reservation
↓
Order
```

当前确认入口负责购票会话的状态和恢复语义，但正式库存仲裁继续复用 Phase 3 已完成
的 PostgreSQL 事务、固定顺序行锁、Reservation 专用幂等和 COMMIT 确认能力。
Phase 3 不是临时方案，也不因未来增加购票会话而废弃。

首次 confirm 在 CheckoutSession 行锁内生成服务端 Key，写入 `SUBMITTING` 后提交；
并发或用户主动重试看到 `SUBMITTING` 时复用该 Key，不生成第二把 Key。随后在事务外
调用 Phase 3 `ReservationService`，继续依靠 `(user_id, idempotency_key)` 唯一约束仲裁正式结果。

恢复入口为：启动时一次有界被动对账、GET 按需对账，以及用户对 `SUBMITTING`
主动重试 confirm。前两者只修复已存在的 Reservation/Order，找不到正式结果时保持
`SUBMITTING`，启动对账绝不会自动购票。详见 [Phase 5 购票会话落地设计](checkout_session_phase5_design.md)。

### Redis 临时占座（Phase 7 已完成）

Redis 是 `SELECTING` 阶段的临时竞争/软占座层；PostgreSQL 仍是正式库存、
Reservation、Order 和 SessionSeat 的最终事实来源。正式 Confirm 仍调用 Phase 3
PostgreSQL Reservation 事务，Redis 不能让 PostgreSQL 本应失败的请求成功。

当前结构为：

```text
Key    ticketing:seat-hold:{sessionId}:sessionSeatId
Value  checkoutSessionId|revision
TTL    默认 300 秒
配置   custom_config.checkout_seat_hold.ttl_seconds
Client seat_holds
```

Redis `/data` 使用 tmpfs，不挂持久化 volume。Redis 丢失或不可用只会失去临时占座
保护：命令超时、连接失败等技术异常按 `Unavailable` 处理并降级到 Phase 6，继续
PostgreSQL 流程；临时残留依靠 TTL 自愈。

同一 CheckoutSession 的 PUT 继续先由 PostgreSQL `FOR UPDATE + revision` 串行化。
拿到行锁并验证版本后，对 full-set 计算 added、retained 和 removed：Redis Prepare
先原子检查并取得目标 Hold，不提前释放旧 Hold；PostgreSQL 成功提交 selectedSeats
与 revision 后，Finalize 才释放 removed；PostgreSQL 失败时 Abort 只撤销本次 added。
revision 同时作为 Redis fencing version，旧 Abort/Finalize 不能删除更高 revision
重新取得的 Hold。这不是 Redis 与 PostgreSQL 的强一致事务。

第一版不增加 Redis 分布式锁、分布式事务、heartbeat、CheckoutSession 到 Hold
集合的 Redis 索引或主动对账 Worker。详细设计见
[Phase 7 Redis 临时占座设计](redis_seat_hold_phase7_design.md)。

### WebSocket

用户锁座或支付成功后，通过 WebSocket 向同场次其他客户端实时广播座位变化。

### 多实例部署

使用 Nginx + 多个 Drogon 实例。

验证不同请求落到不同实例时，数据库和共享缓存仍然能够保持一致。

### 异步事件

引入持久化事件或消息队列，用于：

- 电子票生成。
- 邮件通知。
- 订单事件。
- 后台统计。

限流、排队、异步受理和后台操作查询属于另一类高峰保护能力，只在 Phase 9 的真实
压测证明同步确认出现大量连接等待、请求积压或数据库过载后评估。未来若使用
HTTP 202 和后台操作编号，该编号只标识一次后台执行，不等于购票会话编号、
幂等键或 Order ID；当前不提前选择消息队列或执行框架。

### 可观测性和压测

加入：

- Prometheus。
- Grafana。
- 并发压力测试。
- 故障注入。
- Redis 故障下的不超卖验证。

---

## 15. MVP 完成标准

MVP 完成时必须能够完整演示：

```text
活动
 ↓
场次
 ↓
座位图
 ↓
选择多个具体座位
 ↓
原子锁座
 ↓
创建待支付订单
 ↓
支付 / 取消 / 超时
 ↓
座位 SOLD 或重新 AVAILABLE
```

并且经过并发测试确认：

1. 同一个场次座位不会被重复预订。
2. 多座位请求不会部分成功。
3. 已支付座位不会被超时任务释放。
4. 取消和超时能够正确释放座位。
5. 服务重启不会导致超时订单永久占座。

只要以上业务闭环和并发正确性成立，才认为核心 MVP 完成。当前 Phase 1～4 已经
完成，Phase 5～7 的购票会话、恢复和 Redis 临时占座也已经落地；支付/取消以及完整故障恢复验证仍属于后续阶段，不能因为 Reservation 和
过期回收已经可运行就把完整 MVP 标记为完成。
