# Phase11 支付对账终态原子提交与异常半状态自愈

## 源码基线与修正后的方案

基线为 `23ed5ce`。正常路径采用单事务；异常路径采用重新查渠道的自愈扫描。
不增加 Job 表、MQ 或 heartbeat，不改变 API、card-only、Stripe 600 秒、Simulation 10 秒及 Order-first 规则。

实际旧版 Payment 窗口是：独立 `recordProviderPayment` 写 `provider_status=succeeded/canceled`、同步时间并清空 `next_reconcile_at`，随后另一个生命周期事务失败或进程退出。本地仍 PROCESSING/TIMED_OUT，**provider_terminal_at 仍为 NULL**。007 的 CHECK 禁止终态时间与本地未终态同时存在，该约束继续保留。

Refund 原有 `WITH updated ... INSERT notification` 已是单条原子 SQL，没有同型两事务窗口，本轮保留。其风险测试针对 claim 之后、该 SQL 成功之前的进程失败或事务回滚。

## 字段职责及写入路径

| 对象 / 字段 | 职责和写入路径 |
| --- | --- |
| PaymentAttempt.status | 本地业务事实；PROCESSING/TIMED_OUT 尚待渠道最终裁决，SUCCEEDED/FAILED 已完成 |
| Refund.status | 本地退款事实；PROCESSING 未完成，SUCCEEDED/FAILED 完成 |
| provider_status | 最近一次经过对象身份、关联和金额验证的渠道观察；不能单凭缓存裁决 Order |
| provider_last_sync_at | 本地持久化有效观察的数据库时间 |
| provider_terminal_at | 与本地终态同一事务持久化的渠道完成时间标记；保留现有 CHECK |
| provider_retry_count | 每次领取增加；在线请求的 transport 错误也增加 Payment 的重试计数 |
| next_reconcile_at | 下一次最早允许尝试的时间，**不是工作完成事实，也不是 lease** |
| reconciliation_lease_until/token | 008 新增，30 秒临时领取权与 fencing token；两个字段同时为空或非空 |
| Inbox.status | 插入 PENDING；同一 SQL 完成对象持久化唤醒后才 PROCESSED；现有 FAILED 形状保留，但当前无主动写入路径 |
| Inbox.next_retry_at/retry_count | 保留原有到期领取字段；不存在跨 HTTP ownership，因此不新增 Inbox lease |

Payment 创建时，非 simulation 的 next_reconcile_at=now；simulation 仍走原 timer。
claim 在短 SQL 中提交 lease 与指数退避调度，HTTP 在 SQL 完成之后发生。
非终态观察独立短 SQL 写 status/sync、安排两秒后重试，匹配 token 后释放 Worker lease。
transport/HTTP/身份验证错误不伪造金融失败；保留退避时间并按 token 释放 lease；释放失败时 lease 自然到期。
最终事务失败保留 claim 已提交的 lease 和调度，后续可重新领取。
最终业务事务成功才清空调度与 lease。在线迟到的非终态响应不能改写已完成记录。

## Payment 原子终态事务

在线 pay 与 reconciliation 共用 `OrderLifecycleService::completeProviderPayment`。
传入快照仅包含 provider、对象 ID、状态、已验证的期望金额、成功标志、安全失败码与可选 claim token；没有 clientSecret、raw JSON 或密钥。

事务锁序仍为 Order → PaymentAttempt → 必要的 Reservation → SessionSeat。
锁定后复核 Provider、对象 ID、Order 金额和 claim token，继续使用现有订单期限、座位状态和 ownership 检查。

- accepted success：Attempt SUCCEEDED/accepted_at、Provider 终态、Order PAID、Reservation CONFIRMED、Seat SOLD、PAYMENT_SUCCEEDED 通知及调度清理一起提交。
- unaccepted success：Attempt SUCCEEDED/accepted_at=NULL、Provider 终态和唯一 SYSTEM/PROCESSING Refund 一起提交；已取消/过期/已支付订单和库存不复活。
- 渠道明确失败：Attempt FAILED、真实安全失败码、Provider 终态与调度清理一起提交。有效订单继续等待重试；timeout、429、5xx 或身份不匹配不是金融失败。

事务回滚时，快照和所有本地写入一起回滚。HTTP 不在该事务内，锁 Order 后不会等待 Stripe 网络。

## 旧版异常恢复与 lease

非 simulation、本地 PROCESSING/TIMED_OUT 且 lease 空闲或过期的记录满足以下任一条件即可领取：

1. provider_status 为 `succeeded` 或 `canceled`：存在明确终态证据，优先处理，完全不依赖 next_reconcile_at。
2. next_reconcile_at 为空：修复遗失调度的额外安全网。旧版 `requires_payment_method` 既可能是待输入，也可能携带 last_payment_error 而映射为失败；旧库没保存该错误，不能仅按状态字符串区分，故通过此路径重新 retrieve。
3. 正常 next_reconcile_at 到期。

领取后有对象 ID 则重新 retrieve，无 ID 则使用原幂等键 create/recover。Stripe Payment 验证对象 ID、Attempt/Order metadata、amount 和 currency，最新结果才送入统一事务。不能按缓存 succeeded 直接 PAID。

Refund 保留正常到期扫描和原子终态 SQL，加入独立 lease 及 token 条件。retrieve 同时验证 Refund ID、本地 Refund/Order metadata、PaymentIntent 和 amount。失败或崩溃不会先清空工作线索。
旧 Worker 失去 token 后不能清除新 Worker 的 lease 或提交新的本地终态；数据库行锁和业务唯一约束仍是幂等基础。

## Inbox durable handoff

Inbox 的唤醒和 PROCESSED 在一条 SQL 中原子完成。唤醒增加 provider identity 匹配，不覆盖有效 lease；未完成业务对象获得持久调度，已完成对象保持调度为空。
因此 PROCESSED 表示已完成持久化移交，而非已完成支付。之后任何 HTTP/业务事务失败，都有 PaymentAttempt/Refund 自身的调度或异常扫描作为恢复来源。

## 约束、迁移与可观测性

008 仅新增两组 lease 字段、形状 CHECK 和 Payment 异常候选部分索引。**不删除、不降级任何既有 CHECK**，不新增表，不修改历史 processing_deadline。
已有数据库须在启动新后端前执行 008；新库通过 Compose 初始化顺序执行。不要让旧后端继续处理新语义记录。

保留 Provider ID unique、Refund(payment_attempt_id) unique、Notification dedupe_key、Event unique、Order 行锁和座位 ownership 检查，采用 at-least-once 幂等处理。
复用 `ticketing_payment_reconciliation_total{object_kind,outcome}`，固定新增 outcome 为 `provider_terminal_local_nonterminal`、`missing_schedule`、`lease_expired`、`retry_due`，不加入业务 ID 标签。
Phase11 verifier 新增真实 Payment 终态证据/本地未终态检查，并保留 CHECK 所保护的异常检查；恢复后的最终环境与原有 14 项业务 verifier 必须零违规。

## 故障验证

测试只在独立 Fake Stripe 环境安装临时数据库触发器/序列/advisory lock；生产路径没有 sleep 或 crash 开关。定点杀应用后，在释放 gate 前终止由该 advisory lock 精确定位的数据库会话，确保 PostgreSQL 正在执行的 autocommit SQL 不会在客户端退出后继续提交。

- A：终态 retrieve 后，Attempt 终态写入前定点 SIGKILL，重启、lease 过期后恢复。
- B：通知写入故意失败一次，证明 Provider/业务一同回滚且 Inbox handoff 不丢工作，下一轮恢复。
- C：精确构造旧版合法 P1 状态（provider_status=succeeded、provider_terminal_at=NULL、本地 PROCESSING、next=NULL）；另测未来调度也不能隐藏终态证据。
- D：真实过期 Worker 先将订单/Attempt 过期，再由 Fake Provider 晚到成功触发唯一退款。
- E：SYSTEM Refund INSERT 前定点崩溃，整个 Payment 终态事务回滚，恢复后只建一个退款。
- F：Refund 通知写入失败一次，原子 SQL 回滚，重启后成功且通知一次。
- G：Refund claim 后、原子终态 SQL 前崩溃；保留旧 token，模拟 lease 截止时间流逝后恢复，不构造违反 CHECK 的半状态。
- 额外逐项验证 Payment retrieve 的五类身份不匹配不会导致 PAID。

B/F 等待真实 30 秒 lease 到期；A/E/G 仅回拨测试记录的 lease deadline 加速，不清除 dead-owner token。所有测试保留 CHECK。
真实 Stripe Sandbox、真人 3DS 和外部发布 Gate 不在本轮执行范围，修复后须回独立核验任务重新执行。
