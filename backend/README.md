# Ticketing backend MVP — Phase 12

C++20、Drogon、PostgreSQL 与 Redis 的票务后端。已实现原子多座位预订、
购票会话、认证、支付/取消/超时、Stripe 对账恢复，以及开场前买家整单全额退款。
正式库存和金融生命周期以 PostgreSQL 事务为准。

## Layout

- `src/controllers`、`src/services`、`src/repositories`：HTTP、业务和持久化边界。
- `src/dto/TicketDtos.h`：公开 JSON 契约。
- `db/migrations`：按编号执行 001–009；009 为买家退款迁移。
- `db/seeds/001_demo_seed.sql`：开发夹具；`db/tests`：六份 SQL verifier。
- `tests`：离线契约、单元及独立在线集成测试。

## Run with Docker Compose

在 `backend/` 执行 `docker compose up --build`。现有 Compose 启动后端、
PostgreSQL 和 Redis；默认支付 Provider 为 simulation。配置见
[`docker-compose.yml`](docker-compose.yml) 和 [`config`](config)。
新数据卷按迁移、seed、verifier 顺序初始化；已有卷升级需按序执行尚未应用的迁移，
不要重复 seed 或删除验收数据卷来代替升级。

Stripe Sandbox 使用 `TICKETING_PAYMENT_PROVIDER=stripe`，通过进程环境配置
`STRIPE_SECRET_KEY`、当前转发器生成的 `STRIPE_WEBHOOK_SECRET`、
`STRIPE_CURRENCY=cny` 和官方 `STRIPE_API_BASE_URL=https://api.stripe.com`。
测试凭据必须是 test 前缀；不要将值写入文档、提交或日志。
`STRIPE_PROCESSING_GRACE_SECONDS` 默认 600；创建 PaymentAttempt 后即开始计时，
应在人工输入已准备好后开始支付。支付成功还必须被本地接纳，迟到成功走 SYSTEM 退款。
Stripe CLI 转发到本次隔离后端的 `/payment-webhooks/stripe`，事件包括支付结果及
`refund.created`、`refund.updated`、`refund.failed`；启动新转发器时同步其新签名密钥。

## HTTP entry points

活动、场次、购票会话、认证、订单、支付和通知接口见
[后端技术设计](../docs/backend_technical-design.md)。退款入口：

- `POST /orders/{orderId}/refunds`：登录 owner、Origin/CSRF 校验，**无请求体**。
  首次持久化义务或复用处理中记录返回 202；复用终态返回 200。
  200/202 本身不代表资金成功，读取 Refund.status。
- `GET /refunds/{refundId}`：查询所属订单可访问的退款资源。
- `GET /orders/{orderId}`：含 buyerRefund 摘要和 refundEligibility；页面恢复以此为准。

买家退款从已接纳支付取得金额、币种与渠道身份。处理中订单和座位权益有效；
Worker 核实渠道成功后原子取消订单/预订、释放座位并发送一次完成通知。
重复申请复用原退款，不创建第二笔资金动作。

## Native build

需要 CMake 3.20+、C++20、Drogon（PostgreSQL ORM）、libpq 和 Python 3。

```bash
cmake -S . -B build -DBUILD_TESTING=ON
cmake --build build --parallel
ctest --test-dir build --output-on-failure
./build/ticketing_backend config/config.json
```

也可配置 `-DTICKETING_FETCH_DROGON=ON` 获取项目固定版本。
脱离 Compose 初始化时，按编号应用全部迁移，再在新开发数据库执行 seed/verifier。
开发默认数据库凭据仅供本地使用。

## Verification and scope

正常 Dockerfile 包含构建与 CTest。在线集成需另启动隔离服务；例如基础 HTTP、
预订、`phase12_buyer_refund_integration_test.py`，后者依赖项目现有 Fake Stripe
测试夹具，不能指向真实 Stripe。运行环境及日志索引见
[Phase12-2B 验收记录](../docs/phase12_2b_sandbox_validation.md)。
`001_verify_seed.sql` 要求固定 seed 总数，不能用于新增真实样本后的全库验收。

真实渠道处理中与前端可见状态已经验收；隐藏/失焦的精确请求调度由确定性自动化测试覆盖，
未把未观察到的真实浏览器时间线伪称为已观察。

当前不支持部分退款、退款失败后自动第二次退款、项目外 Dashboard 退款自动认领，
以及 succeeded → failed 后续冲正。Stripe Sandbox 不是生产资金或真实银行结算证明。

本地 Demo 账号：`demo / Ticketing123!`（CUSTOMER）、`admin / Ticketing123!`（ADMIN）。
Demo 管理员只供本地演示，生产部署不得使用此 Seed 作为管理员 provisioning 方案。
