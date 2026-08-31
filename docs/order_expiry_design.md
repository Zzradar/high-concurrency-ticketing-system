# 高并发票务系统 Phase 4：订单状态机、过期时间与原子释放方案设计

## 1. 实施范围与状态

Phase 4 已在当前 C++20 + Drogon 模块化单体中实现：

```text
GET /orders/{orderId}
订单超时释放 Worker
```

本阶段没有实现支付、取消、退款、Redis、消息队列、独立 Worker 进程或新的
Migration。过期处理复用现有 PostgreSQL Schema、`orders_pending_expiry_idx`、
Reservation 与 SessionSeat 关系及 Phase 3 已验证的事务生命周期模式。

## 2. Order 查询

路由为：

```text
GET /orders/{orderId}
X-User-Id: <current user>
```

`OrderController` 读取路径参数和 `X-User-Id`；`OrderService` 复用当前 Demo 用户校验
规则；`OrderRepository` 通过以下两个条件同时限制查询：

```sql
ticket_order.id = $1
AND ticket_order.user_id = $2
```

Order 不存在和属于其他用户两种情况统一返回：

```text
404 ORDER_NOT_FOUND
```

接口从 orders、reservations、sessions 和 reservation_session_seats 的正式关系组装
完整 `TicketOrder`。`seatIds` 是按 ID 排序的 SessionSeat ID；时间统一格式化为 UTC
ISO 8601。数据库 `paid_at` 非 NULL 时输出可选 `paidAt`，NULL 时省略。

该 GET 不执行任何状态迁移。即使已经超过 `expires_at`，也只返回数据库当前正式
状态；回收工作由 Worker 完成。

## 3. 权威过期时间

`orders.expires_at` 是支付截止时间的权威来源，判断使用 PostgreSQL
`CURRENT_TIMESTAMP`。Worker 是资源回收器，不是过期事实的创造者。

这意味着未来支付实现必须在自己的事务中再次用数据库时间判断是否已经到期，不能
把“Worker 是否已扫描到该 Order”作为是否允许支付的依据。Worker 延迟只影响 HELD
座位恢复 AVAILABLE 的及时性。

## 4. 实际代码分层

```text
OrderController
  └── OrderService
        └── OrderRepository                 Order 只读查询

OrderExpiryWorker
  └── OrderExpiryService
        └── OrderRepository                 候选扫描、行锁与状态写入
```

- `OrderRepository` 负责 SQL，不持有业务状态机。
- `OrderService` 负责订单查询的输入、用户与结果语义。
- `OrderExpiryService` 负责单 Order 事务、锁顺序、不变量和批次内继续处理。
- `OrderExpiryWorker` 只负责启动和下一轮调度。

核心过期逻辑不依赖 HTTP Controller，未来拆成独立 Worker 进程时不需要重写状态机。

## 5. 配置和调度

配置位于 Drogon `custom_config.order_expiry_worker`：

```json
{
  "batch_size": 100,
  "interval_seconds": 5.0
}
```

两个参数都必须为正数。代码也保留相同默认值，配置缺失时仍可安全启动。

应用加载配置后创建一个 `OrderExpiryWorker`，通过 Drogon v1.9.13 的
`registerBeginningAdvice()` 在主事件循环启动后立即执行第一轮。每轮异步处理全部
完成后，Worker 才调用：

```text
drogon::app().getLoop()->runAfter(interval_seconds, callback)
```

安排下一轮。实现没有使用 `runEvery()`，因此同一个 Worker 的两轮任务不会重叠；
正常没有候选订单时不打印高频 INFO。

## 6. 候选扫描

候选扫描使用普通 DbClient，不在扫描阶段领取业务所有权：

```sql
SELECT id
FROM orders
WHERE status = 'PENDING_PAYMENT'
  AND expires_at <= CURRENT_TIMESTAMP
ORDER BY expires_at ASC, id ASC
LIMIT $1;
```

该查询形状可使用已有的部分索引 `orders_pending_expiry_idx`。扫描结果只是可能过期的
Order ID；每张 Order 随后各自创建独立 PostgreSQL Transaction。

## 7. 单 Order 锁顺序和重新检查

长期固定锁顺序为：

```text
1. Order
2. Reservation
3. SessionSeat（按 SessionSeat.id ASC）
```

单 Order 首先执行：

```sql
SELECT id,
       reservation_id,
       status,
       expires_at <= CURRENT_TIMESTAMP AS expired
FROM orders
WHERE id = $1
FOR UPDATE SKIP LOCKED;
```

未取得行表示记录不存在或已经被其他事务锁定，当前轮正常跳过。取得锁后再次确认
`status = PENDING_PAYMENT` 且数据库时间已经到达 `expires_at`；条件不再成立也正常
跳过。

随后以 `FOR UPDATE` 锁对应 Reservation，并要求仍为 ACTIVE。最后通过
reservation_session_seats 读取正式关联的 SessionSeat，按库存 ID 升序执行
`FOR UPDATE OF inventory`。

`FOR UPDATE SKIP LOCKED` 是本项目针对 PostgreSQL 的工程选择，不代表其他数据库或
所有票务系统必须采用相同机制。

## 8. 座位双重所有权验证

正式关联的每个 SessionSeat 必须同时满足：

```text
reservation_session_seats.reservation_id = 当前 Reservation
session_seats.status = HELD
session_seats.current_reservation_id = 当前 Reservation
```

全部校验完成后才开始写入。实际释放 SQL仍同时携带三重条件：

```sql
UPDATE session_seats AS inventory
SET status = 'AVAILABLE',
    current_reservation_id = NULL
FROM reservation_session_seats AS item
WHERE item.reservation_id = $1
  AND item.session_seat_id = inventory.id
  AND inventory.status = 'HELD'
  AND inventory.current_reservation_id = $1
RETURNING inventory.id;
```

Service 保存正式关联数量，并要求 `RETURNING` 的实际释放数量完全相等。不能释放几个
就提交几个；数量、状态或所有权不一致都属于业务不变量错误。

## 9. 原子状态迁移与事务生命周期

完整校验后按以下顺序写入：

```text
SessionSeat  HELD → AVAILABLE，current_reservation_id → NULL
Reservation ACTIVE → EXPIRED
Order       PENDING_PAYMENT → EXPIRED
```

Reservation 和 Order UPDATE 都带原状态条件并要求恰好影响一行。所有写入位于同一个
单 Order Transaction 中，任一步影响行数不符或数据库操作失败都会显式
`rollback()`。

成功路径沿用 Phase 3 已验证的 Drogon Transaction 生命周期：设置
`setCommitCallback()`，释放最后一个 Transaction shared pointer 触发提交，并且只在
COMMIT 回调确认成功后把该 Order 计为已过期。代码没有调用不存在的显式
`commit()`，也没有手写 SQL `COMMIT`。

## 10. 批次隔离和日志

一个候选 Order 对应一个独立 Transaction。单张异常订单回滚后，批次继续处理下一
张 Order，不会退出 Worker。运行结果区分：

```text
expired   成功提交
skipped   被锁、已处理或重新检查后不再满足条件
failed    业务不变量、数据库、事务或 COMMIT 失败
```

无候选的正常轮次不打印 INFO；有成功回收时打印批次汇总；任何失败都会输出包含
Order ID 和具体不变量原因的 ERROR，并在轮次结束时输出失败汇总。

## 11. 已验证行为

真实 Docker + PostgreSQL 验证覆盖：

- 当前用户查询自己的完整 Order，其他用户与不存在 Order 使用相同 404。
- GET 查询前后 Order、Reservation 和 SessionSeat 数据不变。
- PAID Seed Order 输出 UTC `paidAt`，NULL 时省略。
- PENDING_PAYMENT / ACTIVE / HELD 原子迁移为 EXPIRED / EXPIRED / AVAILABLE。
- `reservation_session_seats` 与 `reserved_price` 在过期后保留。
- `current_reservation_id` 不匹配时整单回滚，不会误释放座位。
- 同批异常订单不会阻断后续正常订单。
- 两个独立后端 Worker 同时竞争一张过期 Order 时，仅一个成功执行迁移。
- Phase 1～3 只读、幂等、热座竞争和多座位原子性回归继续通过。
- 测试清理后五个 Seed 场次仍各有 60 个库存座位，分布为 51 AVAILABLE、4 HELD、
  5 SOLD。

## 12. 明确未实现

Phase 4 没有实现支付和取消生产接口。未来 Pay、Cancel、Expire 三种终态竞争必须继续
以 Order 为第一仲裁点并沿用固定锁顺序；不得因为本 Worker 已经存在，就跳过未来
支付事务中的数据库过期时间检查。

## 后续稳定性与压测事项

以下事项目前都不是 Phase 4 correctness bug（正确性缺陷），不改变本阶段已经确认的
设计结论。其中第 1、2 点是后续稳定性与压测重点，第 3、4 点是未来架构演进约束。

1. **Worker 单轮可能因极端异步数据库 callback 长期不返回而停摆（后续稳定性/压测重点）**

   问题描述：当前下一轮只有在本轮全部 Order 处理完成后才通过 `runAfter()` 调度。
   如果某个数据库异步 callback 在极端情况下既不成功也不失败，本轮可能一直无法
   结束，后续轮次也不会再启动。普通 SQL 错误已有错误 callback，不属于这里的问题。

   后续处理思路：当前暂不增加 watchdog（看门狗）或 round timeout（单轮超时），
   后续作为稳定性增强项评估。

2. **大量订单同时过期时可能出现库存回收积压（后续稳定性/压测重点）**

   问题描述：当前默认每批最多处理 100 个 Order，批内逐 Order 串行处理，整批结束后
   再等待 5 秒开始下一轮。如果数千订单同时过期，不影响 `expires_at` 的业务正确性，
   但部分已经过期的 HELD 座位可能较晚重新变为 AVAILABLE。

   后续处理思路：压测大量订单同时到期的场景，再根据结果决定是否调大 batch、缩短
   interval，或采用“取满批次时立即继续排空”的策略。

3. **`OrderExpiryService` 当前异步安全依赖 Worker 的长生命周期（未来架构演进约束）**

   问题描述：当前部分异步 callback 捕获裸 `this`，之所以安全，是因为
   `OrderExpiryService` 是长期存活的 `OrderExpiryWorker` 成员，而 Worker 在应用运行
   期间持续被持有。当前实现不需要修改。

   后续处理思路：如果未来把 Service 改成可独立创建、短生命周期调用，需要重新设计
   异步对象所有权，避免 callback 执行时对象已经销毁。

4. **当前 Worker 没有独立的优雅停止生命周期（未来架构演进约束）**

   问题描述：当前没有显式 `stop()`、timer cancel 或 shutdown hook，退出主要依赖
   Drogon EventLoop 生命周期和 weak pointer 失效。当前模块化单体部署足够使用。

   后续处理思路：如果未来拆分独立 Worker 进程、进行滚动发布，或要求停机前等待在途
   事务完成，再补充显式停止与 timer 管理。
