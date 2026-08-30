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

本阶段不追求复杂微服务架构，也不提前引入 Redis、消息队列和实时推送。核心原则是：先用关系数据库事务把预订业务本身做正确。

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
- **Docker Compose**：本地启动 PostgreSQL 和后端服务。
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
  └── Order Module
          │
          ▼
      PostgreSQL

Background Worker
  │
  └── 扫描超时订单并释放座位
```

MVP 不拆微服务。

原因是当前最重要的问题是验证预订模型和并发正确性，而不是服务治理。模块化单体既能保持清晰的业务边界，也能减少服务发现、远程调用、分布式事务和部署带来的额外复杂度。

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

MVP 直接从 PostgreSQL 查询。

暂时不引入 Redis 缓存和 WebSocket。

### 5.3 提交座位预订

用户一次可以选择一个或多个具体座位。

例如：

```text
A01
A02
A03
```

后端开始一个数据库事务。

主要步骤：

1. 根据固定顺序锁定本次请求涉及的 SessionSeat。
2. 检查这些座位是否全部为 AVAILABLE。
3. 如果任意一个座位不可用，则整个事务回滚。
4. 创建 Reservation。
5. 将全部座位更新为 HELD，并关联 Reservation。
6. 创建 PENDING_PAYMENT 状态的 Order。
7. 写入统一的支付截止时间。
8. 提交事务。

因此一次多座位预订只有两种结果：

- 全部成功。
- 全部失败。

不存在只成功部分座位的情况。

---

## 6. 并发预订方案

### 6.1 核心原则

数据库负责最终座位归属。

不能采用：

```text
先查询座位是否 AVAILABLE
然后在应用层判断
再执行 UPDATE
```

这种流程存在并发竞争窗口。

正确方案是把座位竞争放在数据库事务中处理。

### 6.2 多座位统一锁定顺序

当一次预订涉及多个座位时，所有请求都按照固定顺序处理，例如按照 SessionSeat ID 从小到大排序。

这样可以降低以下场景产生死锁的概率：

```text
请求 A：先锁 A01，再锁 A02
请求 B：先锁 A02，再锁 A01
```

统一顺序后，所有请求都按照：

```text
A01 → A02
```

获取数据库行锁。

### 6.3 最终数据保护

除事务和行锁外，还需要通过数据库约束保证数据模型本身不会出现非法状态。

例如：

- `(session_id, seat_id)` 唯一。
- 一个有效座位不能对应多个有效 Reservation。
- Order 与 Reservation 保持一对一或明确的受控关系。

数据库约束作为应用逻辑之外的最后一道保护。

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

状态迁移必须通过数据库条件更新或事务控制完成。

例如支付操作只能修改：

```text
当前状态仍然是 PENDING_PAYMENT 的订单
```

这样可以防止支付和超时任务同时执行时互相覆盖。

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

## 10. 超时订单处理

MVP 不使用每个订单单独创建内存定时器的方式。

原因是应用一旦重启，内存定时器就会全部丢失。

每张待支付订单直接在数据库中保存：

```text
expires_at
```

后台 Worker 周期性扫描：

```text
status = PENDING_PAYMENT
AND expires_at <= current_time
```

找到超时订单后，在数据库事务中：

1. Order → EXPIRED。
2. Reservation → EXPIRED。
3. SessionSeat：HELD → AVAILABLE。

因为过期时间持久化在数据库中，所以应用停止后重新启动，仍然能够继续清理之前已经超时的订单。

---

## 11. MVP 主要接口

### 活动

- 查询活动列表。
- 查询活动详情。

### 场次

- 查询某个活动的场次列表。
- 查询场次详情。

### 座位

- 查询某场次座位图。

### 预订

- 提交一个或多个座位进行预订。
- 查询预订详情。

### 订单

- 查询订单。
- 模拟支付。
- 主动取消。

管理端功能不是 MVP 重点。

活动、场次和座位可以优先通过初始化 SQL 或 Seed 数据准备。

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

### 12.3 取消释放

用户成功锁定 A01 后取消订单。

需要验证：

- Order 进入 CANCELLED。
- Reservation 进入 CANCELLED。
- A01 恢复 AVAILABLE。
- 其他用户之后可以重新预订 A01。

### 12.4 超时释放

创建一个支付时间较短的订单。

等待其过期。

需要验证后台 Worker 最终：

- 把订单修改为 EXPIRED。
- 把 Reservation 修改为 EXPIRED。
- 释放所有 HELD 座位。

### 12.5 支付与超时竞争

让支付操作与超时任务尽可能同时处理同一订单。

最终只能产生一个合法结果：

- PAID + SOLD。
- 或 EXPIRED + AVAILABLE。

不能出现：

- PAID + AVAILABLE。
- EXPIRED + SOLD。

### 12.6 服务重启恢复

创建即将超时的订单后停止服务。

等待订单超过 expires_at，再重新启动服务。

后台 Worker 应能够识别并释放这个历史超时订单。

---

## 13. MVP 暂不实现的能力

第一阶段明确不实现：

- Redis 座位缓存。
- Redis 临时锁。
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

这些能力都不影响第一阶段验证核心预订模型。

---

## 14. 后续演进方向

### Redis

当座位图查询成为热点后，引入 Redis：

- 缓存座位图。
- 保存可丢失的临时锁座状态。
- 限制热门场次请求速率。

正式座位归属仍由 PostgreSQL 决定。

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

只要以上业务闭环和并发正确性成立，就认为 MVP 第一阶段完成。
