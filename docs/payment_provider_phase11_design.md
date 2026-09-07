# Phase 11 可恢复支付 Provider 设计

## 目标与边界

Phase 11 保持 Phase 8 的 Order-first 业务状态机，把渠道交互从 `PaymentService` 内的不可恢复 timer 提升为 `PaymentProvider + Webhook Inbox + 主动对账`。默认 provider 仍是 `simulation`，processing grace 保持 10 秒；Stripe v1 仅支持 card，grace 默认 600 秒。Phase 12 的买家主动退款、部分退款和单座退款不在本阶段。

Stripe 没有官方 C++ 服务端 SDK，因此后端使用 Drogon 1.9.13 的异步 `HttpClient` 直接调用 REST。外部 HTTP 永远发生在 PostgreSQL 事务之外，timeout 默认 5 秒。请求固定 `Stripe-Version: 2026-07-29.dahlia`，Webhook endpoint 必须配置相同版本。

## Provider 契约

`PaymentProvider` 暴露 `createOrRecoverPayment`、`retrievePayment`、`createOrRecoverRefund`、`retrieveRefund`，并把 transport 结果区分为成功、可重试错误和永久错误。渠道状态映射到有限的 PROCESSING / ACTION_REQUIRED / SUCCEEDED / FAILED；Order 状态不读取 Stripe 枚举直接裁决。`SimulationPaymentProvider` 保留 2～6 秒、约 1% 失败和确定性测试 seam，但通过同一 Provider result 入口进入 `OrderLifecycleService`。

配置来自环境变量：

- `TICKETING_PAYMENT_PROVIDER=simulation|stripe`，缺省为 simulation；
- Stripe 模式要求 `STRIPE_SECRET_KEY` 和 `STRIPE_WEBHOOK_SECRET`；
- `STRIPE_CURRENCY` 缺省 cny；
- `STRIPE_API_BASE_URL` 缺省 `https://api.stripe.com`，测试可覆盖到 Fake Stripe；
- `STRIPE_HTTP_TIMEOUT_SECONDS` 缺省 5 秒。
- `STRIPE_PROCESSING_GRACE_SECONDS` 缺省 600 秒，启动时校验为正有限数；只影响新建 Stripe Attempt。

PaymentIntent create 使用 `PaymentAttempt.id` 作为 `Idempotency-Key`，包含 amount、currency、`payment_method_types[]=card` 及本地 attempt/order metadata，不发送 automatic_payment_methods 或 `confirm=true`。Refund create 使用 `Refund.id` 作为幂等键，并绑定原 PaymentIntent、全额 amount 和本地 refund/order metadata。超时、连接断开、429 和 5xx 只安排退避重试，不产生金融失败。

`PaymentProvider::processingGraceSeconds()` 定义渠道宽限，Simulation 读取原 `payment_simulation.processing_grace_seconds=10`，Stripe 读取自身配置。PaymentService 将宽限传给现有 createAttempt，保存为 `started_at + grace` 的 processing_deadline；无需 migration，不修改历史 Attempt。600 秒是支持真人填写卡信息和 3DS 的业务运行默认值，不是性能 SLO 或全 Provider 通用规则。[Stripe 3DS 流程](https://docs.stripe.com/payments/3d-secure/authentication-flow)和 [EMVCo 浏览器 OOB 流程](https://www.emvco.com/dynamic/emv-3-d-secure-whitepaper-v2/out-of-band-oob-authentication/oob-flow-for-browser-channel/)是认证时限设计参考，不意味着所有认证一定能在此窗口完成。

Stripe v1 不支持 ACH/SEPA/Klarna/Alipay/WeChat Pay 等长时间异步 Payment Method。未来增加 Provider 或 Payment Method 时，必须重新设计支付时限与 Seat 回收语义。合法 Attempt 在自身 deadline 内阻止订单过期；超过 deadline 后继续 TIMED_OUT/EXPIRED、释放座位及迟到成功异步退款，绝不复活已过期订单。前端不依据 grace 作业务裁决。

## 持久化与恢复

007 migration 使 `scheduled_complete_at` 可空，并给 PaymentAttempt 增加 provider identity、最新状态、同步时间、终态时间、重试次数和下次对账时间。Refund 成为 PROCESSING / SUCCEEDED / FAILED 异步对象，source 预留 SYSTEM / BUYER，但本阶段只创建 SYSTEM。provider payment/refund id 都在各自 provider 内唯一；一个 attempt 仍最多一个全额退款义务。

`POST /orders/{orderId}/pay` 先在短事务中锁 Order、检查现有 PROCESSING Attempt、创建本地 Attempt 并提交，之后才调用 provider。create response 丢失时保留同一 Attempt，worker 或再次 POST /pay 使用同一幂等键恢复；client secret 不落库。

`POST /payment-webhooks/stripe` 无登录过滤器，安全边界是原始 body 上的 Stripe 签名。验签只接受 v1，支持多个 v1 常量时间比较，忽略 v0，默认容差 300 秒。handler 只保存事件身份、类型、对象 id、本地引用、payload SHA-256 和重试状态；重复 event id 返回 2xx，不保存完整 payload、卡数据或 client secret。

`PaymentReconciliationWorker` 一轮完成后才安排下一轮。它用 `FOR UPDATE SKIP LOCKED` 的短 SQL claim 领取 Inbox、到期 PaymentAttempt 和 PROCESSING Refund，提交 lease 后在事务外调用 provider retrieve/create。Webhook 只是唤醒查单；乱序事件不会把本地终态倒退，因为业务使用 retrieve 的最新对象并继续由 Order-first 锁序仲裁。退避上限默认 60 秒。

渠道支付成功但订单已取消、过期或已被另一 attempt 支付时，Attempt 记录 SUCCEEDED 且 `accepted_at` 为空，同事务创建 SYSTEM/PROCESSING Refund。退款真正 SUCCEEDED 后才发 `AUTO_REFUND_COMPLETED`；明确 FAILED 时记录失败并发 `AUTO_REFUND_FAILED`，不改变 Order、Reservation 或 Seat 的既有终态。

## 安全与验证状态

支付终态采用 Provider snapshot 与 Order-first 本地生命周期单事务提交；旧版 `provider_status` 已终态而本地未终态的记录由独立于调度时间的兜底扫描重新查渠道。008 将 PaymentAttempt/Refund 的 30 秒 lease 与 next_reconcile_at 分离，保留所有 CHECK。Refund 继续使用既有原子终态 SQL；Inbox 继续原子 durable handoff。字段语义、迁移、故障注入与恢复设计见 [支付对账崩溃一致性设计](payment_reconciliation_crash_consistency_phase11_design.md)。

`clientSecret` 只通过已认证、订单 owner 的 pay response 临时返回，不出现在 PaymentAttempt GET、订单、通知、日志、metrics 或数据库。secret key、webhook secret、Authorization header、完整 Stripe body 同样不记录。metrics 只使用 provider/operation/outcome、object_kind/status 等低基数标签。

测试以 Python 标准库 Fake Stripe 为确定性主 Gate，覆盖幂等 create、response lost、429/5xx、重复/乱序/丢失 Webhook、Backend restart、异步退款和退款失败。真实 Stripe Sandbox 需要外部测试 secret、webhook secret 和可用 endpoint；没有凭据时只报告为待验证，不伪造通过结论。
