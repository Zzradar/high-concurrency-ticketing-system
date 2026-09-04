# Phase 9：用户登录、会话认证与多客户端一致体验设计

## 1. 问题场景

Phase 8 以前，受保护接口通过 `X-User-Id` 接收用户身份。任意客户端都可以伪造该
Header，浏览器也没有登录、退出和跨客户端恢复的真实语义；订单 URL 刷新后还依赖
单页内存中残留的活动、场次和座位数据。Phase 9 要解决的是服务器可验证的用户身份、
同一账号的多客户端独立会话，以及基于正式后端状态的订单恢复，而不是引入新的库存或
支付状态机。

## 2. 采用方案

### 2.1 账号、密码与登录

迁移 `006_add_user_authentication.sql` 为 `app_users` 增加规范化小写 `username`、
`password_hash` 和 `ACTIVE / DISABLED` 状态，并建立 `user_sessions`。Demo 账号为
`demo`，密码只以 Argon2id 编码值保存。

登录流程为：

```text
POST /auth/login
→ Origin 白名单校验
→ 用户名规范化与 Redis 局部限流
→ PostgreSQL 查询用户
→ PasswordHashExecutor 有界线程池执行 Argon2id verify
→ PostgreSQL 创建 user_sessions
→ 写入 Redis Session Cache
→ 返回 CurrentUser 并设置 Cookie
```

Argon2id 参数来自配置，当前为 time cost 2、memory cost 65536 KiB、parallelism 1。
哈希验证不占用 Drogon Event Loop；线程池当前 2 个 worker、队列上限 64，队列满返回
`AUTH_BUSY`。用户不存在、被禁用或密码不可用时仍对固定 dummy Argon2id hash 做一次
验证，避免明显的用户存在性时序差异。登录失败按规范化用户名和来源 IP 分别在 Redis
计数，当前窗口 60 秒、最多 5 次；Redis 故障时该局部限流 fail-open，但 PostgreSQL
用户检查和 Argon2id 验证不会被跳过。

### 2.2 Opaque Session 与正式事实

登录成功生成 32 字节 CSPRNG 值并编码为 64 个十六进制字符的 opaque Session Token。
原始 Token 只进入 `ticketing_session` HttpOnly Cookie，不写 PostgreSQL、Redis value
或日志；数据库只保存其 SHA-256 `token_hash`。CSRF Token 独立随机生成并保存在可由
前端读取的 `ticketing_csrf` Cookie。

`user_sessions` 保存：

- Session ID、User ID 和唯一 `token_hash`；
- `created_at`、`last_seen_at`、`idle_expires_at`、`absolute_expires_at`；
- 可空的 `revoked_at`。

PostgreSQL 是 Session 有效性和撤销状态的正式事实。默认 idle timeout 为 1 天，
absolute timeout 为 7 天；更新 idle timeout 时不会越过 absolute timeout。
`last_seen_at` 默认每 300 秒才回写一次，以控制请求造成的数据库写放大。

一个 User 可以同时拥有多个 `user_sessions`。不同浏览器或 Cookie Jar 获得不同随机
Token；退出只撤销当前 `AuthContext.sessionId`，不会撤销同一用户的其他 Session。

### 2.3 Cookie、CSRF 与请求认证

Session Cookie 和 CSRF Cookie 都使用 `Path=/`、`SameSite=Lax`，`Secure` 由部署配置
决定；只有 Session Cookie 带 `HttpOnly`。登录要求 `Origin` 命中配置白名单。所有
POST、PUT、PATCH、DELETE 受保护请求还必须同时满足：

```text
Origin 在白名单
X-CSRF-Token == ticketing_csrf Cookie
```

比较使用恒定时间函数。前端 Axios 启用 `withCredentials`，并只在 unsafe method 上从
CSRF Cookie 读取值写入 `X-CSRF-Token`。401 响应会清理前端认证状态。

`AuthFilter` 从 Cookie 取得 raw token，经 SHA-256 后解析 Session，并把已验证的
`userId / sessionId / tokenHash / username / displayName` 写入请求的 `AuthContext`。
业务 Controller 只从 `AuthContext` 取得用户身份，`X-User-Id` 已从正式接口移除。

### 2.4 Redis Session Cache 与回源

独立 Redis client `auth_sessions` 使用键：

```text
ticketing:auth-session:<tokenHash>
```

value 只缓存 Session ID、用户公开身份和时间字段，不包含 raw Token、密码、密码哈希或
CSRF Token。TTL 取配置上限 300 秒、idle 剩余时间和 absolute 剩余时间的最小值。
Redis miss、反序列化失败或 Redis error 都回源 PostgreSQL；Redis 仍只是 Cache，故障
不会把认证退化成 `X-User-Id` 或 Redis-only Session。

阶段 A 安全审计确认，旧实现会在 Redis hit 时直接信任缓存，而 logout 的 `DEL` 是
best-effort，因此存在“PostgreSQL 已撤销、Redis 陈旧快照仍可认证至 TTL”的窗口。
最终实现保留 DB-first revoke 和 best-effort `DEL`，同时在每次缓存命中后执行按
`session id + token_hash` 的轻量 PostgreSQL 有效性查询，校验 `revoked_at`、idle/
absolute expiry 和用户 `ACTIVE` 状态。校验失败会拒绝请求并再次尽力删除缓存；数据库
校验异常返回 `503 AUTH_UNAVAILABLE`，不会接受无法确认有效的 Token。

因此，logout 的 PostgreSQL 更新提交后，任何随后开始的旧 Token 请求即使命中未删除
的 Redis value 也会得到 401。Cache 仍避免完整 Session/用户 DTO 的数据库读取和
反序列化，并继续承担 miss 加速及 `last_seen` 写节流；当前规模下，一次主键加 Token
哈希的轻量只读校验是立即撤销语义与复杂度之间的明确取舍。

### 2.5 Logout

```text
POST /auth/logout
→ AuthFilter 验证当前 Session 与 CSRF
→ UPDATE user_sessions
   SET revoked_at = COALESCE(revoked_at, clock_timestamp())
→ PostgreSQL 成功回调
→ best-effort DEL Redis cache
→ 清 Session / CSRF Cookie
→ 200 {"status":"ok"}
```

`revoked_at` 使用数据库时钟。`COALESCE` 使重复数据库 revoke 保留首次撤销时间；HTTP
logout 需要当前请求仍能通过认证，因此浏览器完成一次成功 logout 后再次调用会得到
401，而底层 revoke 操作本身是幂等的。Cookie 清除复用创建 Cookie 的属性并将
`Max-Age` 设为 0。HTTP 200 只在数据库更新成功后返回；Redis 删除失败不会恢复数据库
Session，也不会因最终的缓存命中校验产生陈旧认证窗口。

## 3. 业务接口与所有权

未登录用户可以访问健康检查、活动、活动详情、场次、场次详情和座位图。登录、
`/auth/me`、logout 之外，以下购票资源由 `AuthFilter` 保护：

- Reservation 创建；
- CheckoutSession 创建、查询、修改、确认和放弃；
- `GET /orders`、`GET /orders/{orderId}`、支付和取消；
- PaymentAttempt 查询；
- Notification 列表和已读操作。

Seat Hold 的 owner 仍是 CheckoutSession，但 CheckoutSession 的所有权由认证用户确定。
可选 `checkoutSessionId` 只在该会话属于当前认证用户时让自己的 Redis Hold 显示为可用；
不能借此查看或继承其他用户的临时占座。

`GET /orders` 支持可选 `status`、`sessionId` 和 `limit`，只返回当前用户订单；
`GET /sessions/{id}` 和 `GET /events/{id}` 使订单深链接能独立补齐页面数据。正式预订
成功时创建 `ORDER_CREATED` Notification，供另一个已登录客户端发现新订单。

Confirm、支付和取消响应带显式 `disposition`，区分本次操作与复用的既有结果：

- Confirm：`CONFIRMED_NOW / REUSED_CONFIRMATION / ALREADY_CONFIRMED`；
- Pay：`STARTED_NEW / REUSED_PROCESSING / ALREADY_PAID`；
- Cancel：`CANCELLED_NOW / ALREADY_CANCELLED`。

这些字段防止客户端 B 把客户端 A 已完成的结果误报成“本次刚成功”。数据库库存、
Reservation、Order、支付和取消事务仍沿用 Phase 3～8 的正式规则。

## 4. 多客户端前端体验

前端已使用 Vue Router 和 `createWebHistory()`：

```text
/login
/events
/events/:eventId/sessions
/sessions/:sessionId/seats
/orders
/orders/:orderId
```

`/orders` 与 `/orders/:orderId` 有 route guard；启动或首次导航通过 `/auth/me` 恢复登录。
未登录用户仍可浏览活动和座位，在第一次选座或确认时被引导登录并带回原 URL。

`App.vue` 只负责共享壳层、登录入口、当前用户和通知中心。订单页面根据 URL 中的
Order ID 调用 `GET /orders/{id}`，再用 Event/Session 详情接口恢复展示数据，因此刷新
或直接打开深链接有效。“我的订单”页面调用 `GET /orders?status=...&limit=20`。

Checkout locator 保存在当前 Tab 的 `sessionStorage`，键包含认证 User ID：
`ticketing.checkout.<userId>`，避免用户切换时复用另一用户的定位信息。选座页还按
`sessionId` 查询当前用户订单，显示待支付或已购买的 existing-order banner，但允许
用户明确继续购票。

Confirm、Pay、Cancel 根据 disposition 显示“本次开始/完成”或“已有结果”的不同提示。
`ORDER_CREATED`、支付、取消、过期与自动退款通知每 5 秒轮询，并在 window focus 时
重新同步；点击通知跳到相应订单 URL。订单页和选座页也在 focus 时读取正式后端状态，
使不同 Cookie Jar 的操作结果能够收敛。logout 清空当前用户、通知和该用户 locator；
轮询函数在无 current user 时清空通知而不继续请求受保护资源。

生产静态服务器必须把未知前端路径 fallback 到 `index.html`，否则浏览器直接访问
`/orders/<id>` 等 history URL 会在到达 Vue Router 前得到 404。这是部署约束，不是
新增后端业务接口。

## 5. 为什么这样设计

- opaque 随机 Token 配合服务端 Session 能逐个撤销，并天然支持一个用户多设备登录；
- PostgreSQL 继续作为正式事实，复用项目已经验证的事务与故障模型；
- Redis 只做缓存和局部限流，Redis 故障不会改变身份所有权；
- Cookie 避免前端 JavaScript 接触 Session Token，Origin + double-submit CSRF 保护
  浏览器 unsafe method；
- 有界 Argon2id worker pool 防止 CPU/内存型密码验证阻塞 Event Loop 或无限排队；
- disposition、订单列表、深链接和通知同步解决多客户端“结果已发生但本端不知道”的
  体验问题，不改变 Phase 8 状态机。

## 6. 舍弃或暂缓方案

- 不采用客户端可伪造的 `X-User-Id`；
- 不采用 JWT、Refresh Token 或 Redis-only Session；
- 不实现注册、找回密码、OAuth、SSO、设备管理和 logout-all；
- 不引入 MQ、outbox、分布式锁、微服务、Nginx 或 WebSocket；
- 不用单纯缩短 Cache TTL 来掩盖撤销窗口，也不使用同样依赖故障 Redis 的 deny key；
- Phase 10 才根据真实压测决定限流、排队、异步受理和后台操作查询。
