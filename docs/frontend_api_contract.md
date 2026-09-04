# 前端接口契约文档

> 调查对象：当前仓库中的 Vue 3 前端实际代码。  
> 主要依据：frontend/src/types.ts、frontend/src/api/ticketApi.ts、frontend/src/router.ts、frontend/src/pages、frontend/src/views 和 frontend/src/components。
> 本文只记录当前前端已经存在的数据模型、调用方式和状态语义，不代表后端最终方案。

## 1. 当前 API 运行方式

- API 封装位于 frontend/src/api/ticketApi.ts。
- Axios 的 baseURL 为 **/api**，超时时间为 **8000 ms**，并启用 `withCredentials`。不再发送 `X-User-Id`；认证身份来自 Session Cookie。
- 开发环境会把 **/api** 代理到 **http://localhost:8080**，并移除路径前缀 **/api**。例如浏览器请求 **/api/events**，C++ 后端实际接收 **/events**。
- 当 **VITE_USE_MOCK_API** 不等于字符串 **false** 时使用 mock；仓库中的 .env.example 当前为 **true**。
- 真实 API 成功响应直接读取 Axios 的 response.data，不使用统一 data 外层包装，也不做响应字段转换。失败响应提取 `code` 和 `message`，并转换为兼容现有处理逻辑的 TicketApiError。
- 当前实际代码存在以下真实后端调用：

| 前端方法 | HTTP |
| --- | --- |
| login | POST /auth/login |
| me | GET /auth/me |
| logout | POST /auth/logout |
| getEvents | GET /events |
| getEvent | GET /events/{eventId} |
| getSessions | GET /events/{eventId}/sessions |
| getSession | GET /sessions/{sessionId} |
| getSeats | GET /sessions/{sessionId}/seats?checkoutSessionId={optionalCheckoutSessionId} |
| createReservation | POST /reservations |
| createCheckoutSession | POST /checkout-sessions |
| getCheckoutSession | GET /checkout-sessions/{id} |
| listRecoverableCheckoutSessions | GET /checkout-sessions?sessionId=...&recoverable=true |
| replaceCheckoutSessionSeats | PUT /checkout-sessions/{id}/seats |
| confirmCheckoutSession | POST /checkout-sessions/{id}/confirm |
| abandonCheckoutSession | POST /checkout-sessions/{id}/abandon |
| getOrder | GET /orders/{orderId} |
| getOrders | GET /orders?status=...&sessionId=...&limit=... |
| payOrder | POST /orders/{orderId}/pay |
| getPaymentAttempt | GET /payment-attempts/{paymentAttemptId} |
| cancelOrder | POST /orders/{orderId}/cancel |
| getNotifications | GET /notifications |
| markNotificationRead | POST /notifications/{notificationId}/read |

expireOrderForDemo 仅用于 mock 演示；真实 API 模式会直接报 MOCK_ONLY，不能视为后端接口契约。

当前后端已实际打通订单查询、异步支付、取消、PaymentAttempt 查询和用户通知接口。

## 2. 页面、组件与数据需求

前端使用 Vue Router；`App.vue` 提供共享壳层和通知中心，各 route page 自行加载权威数据。
购票会话通过服务端恢复，`sessionStorage` 只保存当前 Tab、当前用户命名空间下的
`checkoutSessionId + sessionId` locator。

| 页面 / 视图 | 主要组件 | 当前依赖数据 | 当前来源 | 后端联调需求 |
| --- | --- | --- | --- | --- |
| 活动列表 `/events` | EventCard | events、loading | EventListPage 调用 getEvents | TicketEvent[] 必须由 GET /events 提供 |
| 场次选择 `/events/:eventId/sessions` | SessionCard | event、sessions、loading | SessionListPage 按 URL 调用 getEvent/getSessions | Event 与 TicketSession[] 详情接口 |
| 座位选择 `/sessions/:sessionId/seats` | SeatGrid、SeatItem、SelectedSeats、RecoverableCheckoutPanel | event、session、seats、selectedSeatIds、checkout、恢复候选与确认状态 | 页面按 route 加载详情；CheckoutSession 是服务端 checkpoint | Seat[] 与 CheckoutSession API；提交时后端最终确认是否锁座成功 |
| 订单 `/orders/:orderId` | OrderSummary | order、paymentAttempt、event、session、seats、操作状态、倒计时 | OrderPage 按 URL 获取 Order，再按 eventId/sessionId 补齐详情 | 支付返回后轮询 Attempt；订单终态变化后重新获取 order 和通知 |
| 我的订单 `/orders` | OrderListPage | orders、status、loading | GET /orders，默认 limit=20 | 当前认证用户的订单列表 |

页面中的以下内容目前是纯前端常量，不来自接口：

- 品牌名称、页头步骤和说明文案。
- Mock 模式的 Demo 登录账号和展示文案。
- 活动页“本周精选 2 场活动正在售票”中的数字 2。
- 舞台文字、座位状态中文说明、状态提示文案。
- 最多选择 6 个座位的前端限制。

## 3. 当前实际数据结构

### 3.1 TicketEvent

| 字段 | TypeScript 类型 | mock 示例 | 当前实际用途 |
| --- | --- | --- | --- |
| id | string | evt-concert-2026 | 列表 key；加载场次时作为 eventId |
| name | string | 星海回响 · 2026 巡演 | 活动卡、场次页、选座页和订单页展示 |
| description | string | 沉浸式环形舞台与全景声现场… | 活动卡和场次页展示 |
| city | string | 上海 | 活动卡和场次页展示 |
| venue | string | 上海体育场 | 活动卡和场次页的活动级场馆展示 |
| dateRange | string | 2026.10.01 — 10.03 | 活动卡和场次页直接展示，前端不解析 |
| status | ON_SALE 或 COMING_SOON | ON_SALE | 类型和 mock 中存在，但当前组件没有读取；活动卡始终显示“正在售票” |
| cover | string | /images/concert-cover.png | img 的 src |
| sessionCount | number | 3 | 活动卡显示“3 个可选场次” |
| category | string | 演唱会 | 活动卡、场次页、选座页和订单页展示 |

当前 GET /events 期望返回完整 TicketEvent[]，因为代码没有额外的活动详情请求。

### 3.2 TicketSession

| 字段 | TypeScript 类型 | mock 示例 | 当前实际用途 |
| --- | --- | --- | --- |
| id | string | ses-concert-1001 | 选择场次后加载座位；创建预订时作为 sessionId |
| eventId | string | evt-concert-2026 | 模型和 mock 中存在；当前页面不直接读取 |
| date | string | 10月01日 | 场次卡、选座摘要和订单页直接展示 |
| time | string | 19:30 | 场次卡、选座摘要和订单页直接展示 |
| weekday | string | 周四 | 场次卡、选座页和订单页展示 |
| venue | string | 上海体育场 · 主场馆 | 场次卡、选座页和订单页展示 |
| gateTime | string | 17:30 | 场次卡展示入场时间 |
| status | ON_SALE 或 SOLD_OUT | ON_SALE | SOLD_OUT 时禁用“进入选座” |
| priceFrom | number | 58000 | 单位为分；场次卡格式化显示“¥580 起” |
| availability | 充足、紧张或售罄 | 紧张 | 场次卡显示余票提示和颜色 |

date、time、weekday、gateTime 当前都是已经格式化的展示字符串，不是前端计算结果。

### 3.3 Seat

| 字段 | TypeScript 类型 | mock 示例 | 当前实际用途 |
| --- | --- | --- | --- |
| id | string | ses-concert-1001-A01 | 本地选择主键；POST /reservations 提交 seatIds；订单 seatIds 关联 |
| sessionId | string | ses-concert-1001 | 模型和 mock 中存在；当前组件不直接读取 |
| label | string | A01 | 已选座位列表、订单座位和无障碍文本 |
| row | string | A | SeatGrid 分组 |
| number | number | 1 | 单个座位图中显示的数字 |
| status | AVAILABLE、HELD 或 SOLD | AVAILABLE | 决定能否点击和显示样式 |
| zone | string | 星光区 | 已选座位摘要和 title 展示 |
| price | number | 128000 | 单位为分；用于单座价格、本地合计和创建订单 mock 金额，展示时统一格式化为人民币元 |

#### Seat 状态语义

| 展示状态 | 是否属于 Seat.status | 语义 |
| --- | --- | --- |
| AVAILABLE | 是 | 最近一次座位接口返回可选；允许本地点选，但不代表已经正式锁座 |
| SELECTED | **否** | 纯前端派生状态：Seat.status 为 AVAILABLE 且 seat.id 位于 selectedSeatIds 中 |
| HELD | 是 | PostgreSQL 正式预订已锁定，或 PG AVAILABLE 座位被其他 CheckoutSession 的 live Redis Hold 临时覆盖；前端禁止点击 |
| SOLD | 是 | 已售出；前端禁止点击 |

用户点选 AVAILABLE 座位时先增删 selectedSeatIds，并异步创建或更新 CheckoutSession
完整座位集；后端会尝试取得或调整 Redis 临时 Hold，但不会把前端 Seat.status
直接改成正式库存状态。selectedSeats 是从 seats 中按 selectedSeatIds 计算得到的 Seat[]。

### 3.4 Reservation

| 字段 | TypeScript 类型 | mock 示例 | 当前实际用途 |
| --- | --- | --- | --- |
| id | string | RSV-24082601 | ReservationResult 契约字段；mock 内部与订单关联 |
| userId | string | U-1001 | mock 内部数据；页面未读取 |
| sessionId | string | ses-concert-1001 | mock 内部数据；页面未读取 |
| seatIds | string[] | [ses-concert-1001-A01] | mock 内部数据；页面未读取 |
| status | ACTIVE、CONFIRMED、CANCELLED 或 EXPIRED | ACTIVE | mock 内部随订单变化；页面未读取 |
| expiresAt | string | 2026-08-30T05:30:00.000Z | mock 内部数据；页面未读取 |
| createdAt | string | 2026-08-30T05:15:00.000Z | mock 内部数据；页面未读取 |

createReservation 的 TypeScript 返回类型要求同时包含 reservation 和 order，但 App.vue 当前只保存 result.order。当前 App 状态中**没有 currentReservation**。

### 3.5 TicketOrder

| 字段 | TypeScript 类型 | mock 示例 | 当前实际用途 |
| --- | --- | --- | --- |
| id | string | TKT-24082602 | 订单号展示；查询、支付、取消的路径参数 |
| reservationId | string | RSV-24082601 | mock 内部关联；页面未读取 |
| eventId | string | evt-concert-2026 | 模型和 mock 中存在；页面未用它重新获取活动 |
| sessionId | string | ses-concert-1001 | 模型和 mock 中存在；页面未用它重新获取场次 |
| seatIds | string[] | [ses-concert-1001-A01] | 从当前 seats 中筛选订单座位并展示 label |
| status | PENDING_PAYMENT、PAID、CANCELLED 或 EXPIRED | PENDING_PAYMENT | 控制订单状态文案、按钮和样式 |
| totalAmount | number | 128000 | 单位为分；订单金额和支付按钮统一格式化为人民币元展示 |
| expiresAt | string | 2026-08-30T05:30:00.000Z | 与 Date.now() 计算显示倒计时；归零后触发订单查询 |
| createdAt | string | 2026-08-30T05:15:00.000Z | 模型中存在；页面未读取 |
| paidAt | string，可选 | 2026-08-30T05:17:00.000Z | 支付成功 mock 返回；页面未读取 |

订单页根据 TicketOrder 的 `eventId / sessionId` 调用详情接口恢复活动、场次和座位，
因此可以直接刷新或打开订单深链接。

### 3.6 PaymentAttempt、PaymentStartResult 与 UserNotification

`PaymentAttempt` 包含 `id`、`orderId`、`status`、`startedAt`、
`processingDeadline`、`scheduledCompleteAt`，以及可选的 `completedAt`、`timedOutAt`、
`acceptedAt`、`failureReason`。状态为 `PROCESSING / SUCCEEDED / FAILED / TIMED_OUT`；
`acceptedAt` 存在才表示渠道成功已被 Order 接纳。

`PaymentStartResult` 固定包含 `order` 和可空的 `paymentAttempt`。`UserNotification`
包含 `id`、`orderId`、`type`、`title`、`message`、`createdAt` 和可选 `readAt`；`type`
为 `ORDER_CREATED / PAYMENT_SUCCEEDED / ORDER_CANCELLED / ORDER_EXPIRED /
AUTO_REFUND_COMPLETED`。

### 3.7 CurrentUser 与认证 Cookie

`CurrentUser` 直接包含 `id`、`username`、`displayName`。POST `/auth/login` 和 GET
`/auth/me` 成功时都返回该对象。raw Session Token 只在 HttpOnly
`ticketing_session` Cookie 中；前端可读取独立的 `ticketing_csrf` Cookie，并在
POST、PUT、PATCH、DELETE 请求上发送 `X-CSRF-Token`。Cookie 由浏览器自动携带，
业务请求体和 Header 都不再提交用户 ID。

## 4. 页面操作与接口调用关系

| 时机 / 操作 | 当前前端行为 | 接口与数据 |
| --- | --- | --- |
| App 首次挂载 | 恢复认证并启动通知同步 | GET /auth/me；已登录时 GET /notifications |
| 点击“查看场次” | 路由到 eventId 并加载活动与场次 | GET event + GET /events/{event.id}/sessions |
| 点击“进入选座” | 路由到 sessionId，加载场次、活动和座位 | GET session + GET event + GET seats |
| 进入选座 | 先按 locator GET；无有效 locator 时查询全部可恢复会话且不自动选最新一条 | GET CheckoutSession / list recoverable |
| 第一次点击 AVAILABLE 座位 | 立即更新 selectedSeatIds，并异步创建唯一 C1；后端同时尝试取得首批 Redis 临时 Hold | POST /checkout-sessions |
| 后续 add/remove | UI 立即更新；同一 C1 以 single-flight PUT 同步最新完整集合 | PUT seats，携带 seatIds、expectedRevision |
| 点击刷新座位 | 重新获取 Seat[]；已有 C1 时携带其 ID，不删除恢复出的 HELD/SOLD 意图座位 | GET /sessions/{session.id}/seats?checkoutSessionId={C1} |
| 点击“提交预订” | 禁止继续编辑，等待 create/PUT 并把最终集合 flush 到服务端 checkpoint，再正式确认 | POST /checkout-sessions/{id}/confirm |
| 确认成功 | 使用 CheckoutSession 响应中的 order，刷新座位图并进入订单页 | confirm 响应 RESERVED CheckoutSession；随后 GET seats |
| SEAT_CONFLICT | GET 当前 C1 回到 SELECTING，保留服务端意图并刷新 Seat Map | GET CheckoutSession + GET seats |
| SEAT_TEMPORARILY_HELD | 视为明确业务冲突，保留合理的本地意图并刷新 Seat Map，不进入结果未知轮询 | GET seats；Final PUT 冲突时不调用 confirm |
| 点击订单“刷新状态” | 更新页面 order | GET /orders/{order.id} |
| 打开“我的订单” | 按状态筛选当前用户最近订单 | GET /orders?status=...&limit=20 |
| 直接打开订单 URL | 按 orderId 恢复 Order，再恢复 Event、Session 与 Seat[] | GET /orders/{id}、GET /events/{id}、GET /sessions/{id}、GET seats |
| 倒计时归零 | 倒计时组件只发出 expiryReached，不自行把订单设为 EXPIRED | GET /orders/{order.id}，以后端状态为准 |
| 点击“模拟支付” | 保存返回的 order 和 PROCESSING Attempt，约每 1 秒轮询，最长约 15 秒 | POST /orders/{order.id}/pay；GET /payment-attempts/{id} |
| 支付 Attempt 到达终态 | 重新查询订单、座位与通知；未接纳的 SUCCEEDED 以退款通知为准 | GET order、GET seats、GET notifications |
| 点击“取消订单” | 独立执行取消；即使支付仍在 polling 也不停止观察其迟到结果 | POST /orders/{order.id}/cancel；随后 GET seats 和 notifications |
| 点击“模拟订单超时” | 仅 mock 模式调用本地 expireOrderForDemo | 不对应真实后端接口 |

支付启动请求出错时，前端不会直接认定支付失败，而是显示“支付请求结果未知”并调用 GET /orders/{orderId} 重新查询；已经拿到 Attempt 后则以 Attempt polling 的终态为准。

## 5. 当前前端期望的接口契约

成功响应的 JSON 直接作为 `response.data` 使用；业务失败响应统一为：

    {
      "code": "SEAT_CONFLICT",
      "message": "Selected seats are no longer available"
    }

Axios 响应拦截器会提取字符串类型的 `code` 和 `message`，转换为 TicketApiError；无法匹配该结构的异常仍交给现有通用错误处理逻辑。

### 5.0 认证接口与浏览器请求规则

- `POST /auth/login` 请求 `{ "username": "demo", "password": "..." }`，成功直接返回
  `{ "id", "username", "displayName" }` 并设置 Session/CSRF Cookie；必须带允许的 Origin。
- `GET /auth/me` 使用 Session Cookie 恢复同一 CurrentUser；无效或过期 Session 返回
  401 `UNAUTHENTICATED`，认证依赖暂不可用返回 503 `AUTH_UNAVAILABLE`。
- `POST /auth/logout` 必须通过当前 Session、Origin 和 CSRF 校验，成功返回
  `{ "status": "ok" }` 并清 Cookie；只撤销当前浏览器 Session。
- Axios `withCredentials=true`。POST、PUT、PATCH、DELETE 自动发送从
  `ticketing_csrf` Cookie 读取的 `X-CSRF-Token`；业务接口不再发送 `X-User-Id`。
- Origin/CSRF 不合法返回 403 `CSRF_INVALID`；登录失败为 401
  `INVALID_CREDENTIALS`，局部限流触发为 429 `TOO_MANY_LOGIN_ATTEMPTS`。

PostgreSQL `user_sessions.revoked_at` 是撤销的正式事实。Redis Session Cache miss/error
回源 PostgreSQL；cache hit 也会用 Session ID 与 token hash 轻量检查数据库有效性，
所以 logout 后即使 Redis 删除失败，旧 Cookie 也不能继续通过认证。

### 5.1 GET /events

对应活动列表首次加载。无请求参数。

前端期望 response.data 直接为数组：

    [
      {
        "id": "evt-concert-2026",
        "name": "星海回响 · 2026 巡演",
        "description": "沉浸式环形舞台与全景声现场，和三万名观众一起点亮这个夜晚。",
        "city": "上海",
        "venue": "上海体育场",
        "dateRange": "2026.10.01 — 10.03",
        "status": "ON_SALE",
        "cover": "/images/concert-cover.png",
        "sessionCount": 3,
        "category": "演唱会"
      }
    ]

当前代码明确依赖：id、name、description、city、venue、dateRange、cover、sessionCount、category。status 存在于类型中，但当前活动组件未消费。

### 5.2 GET /events/{eventId}/sessions

对应用户选择活动后加载场次。

- Path：eventId，string，例如 evt-concert-2026。
- Query：当前无。

前端期望 response.data 直接为数组：

    [
      {
        "id": "ses-concert-1001",
        "eventId": "evt-concert-2026",
        "date": "10月01日",
        "time": "19:30",
        "weekday": "周四",
        "venue": "上海体育场 · 主场馆",
        "gateTime": "17:30",
        "status": "ON_SALE",
        "priceFrom": 58000,
        "availability": "紧张"
      }
    ]

当前代码明确依赖除 eventId 外的全部字段；eventId 目前仅存在于模型和 mock。

### 5.3 GET /sessions/{sessionId}/seats

对应进入选座、手动刷新座位，以及订单状态变更后的座位同步。

- Path：sessionId，string，例如 ses-concert-1001。
- Query：`checkoutSessionId` 可选。已有当前 C1 时传其 ID；没有 C1 时可省略。

前端期望 response.data 直接为完整 Seat[]：

    [
      {
        "id": "ses-concert-1001-A01",
        "sessionId": "ses-concert-1001",
        "label": "A01",
        "row": "A",
        "number": 1,
        "status": "AVAILABLE",
        "zone": "星光区",
        "price": 128000
      },
      {
        "id": "ses-concert-1001-A03",
        "sessionId": "ses-concert-1001",
        "label": "A03",
        "row": "A",
        "number": 3,
        "status": "HELD",
        "zone": "星光区",
        "price": 128000
      }
    ]

当前代码明确依赖 id、label、row、number、status、zone、price。sessionId 当前不被组件读取。SELECTED 不应由此接口返回。

Phase 7 的叠加规则为：

- 不传 `checkoutSessionId` 时，任何 live Redis Hold 都视为其他购票会话占用；
- 传当前 C1 时，该 C1 自己的 Hold 不把 PostgreSQL AVAILABLE 覆盖成不可选；
- 其他 C1 的 Hold 把 PostgreSQL AVAILABLE 在响应中表现为 HELD；
- PostgreSQL 已经 HELD/SOLD 时始终以正式状态为准；
- Redis 批量读取失败时接口仍成功，退化为纯 PostgreSQL seat map。

### 5.4 POST /reservations

对应点击“提交预订”。当前请求 JSON 使用 camelCase：

    {
      "sessionId": "ses-concert-1001",
      "seatIds": [
        "ses-concert-1001-A01",
        "ses-concert-1001-A02"
      ]
    }

当前请求不包含 userId、价格或前端计算的 totalAmount；用户由服务器验证后的 Session
和 `AuthContext` 提供。前端要求后端以 sessionId 和 seatIds 为准，原子确认全部座位。

成功时前端期望 response.data 直接为 ReservationResult：

    {
      "reservation": {
        "id": "RSV-24082601",
        "userId": "U-1001",
        "sessionId": "ses-concert-1001",
        "seatIds": [
          "ses-concert-1001-A01",
          "ses-concert-1001-A02"
        ],
        "status": "ACTIVE",
        "expiresAt": "2026-08-30T05:30:00.000Z",
        "createdAt": "2026-08-30T05:15:00.000Z"
      },
      "order": {
        "id": "TKT-24082602",
        "reservationId": "RSV-24082601",
        "eventId": "evt-concert-2026",
        "sessionId": "ses-concert-1001",
        "seatIds": [
          "ses-concert-1001-A01",
          "ses-concert-1001-A02"
        ],
        "status": "PENDING_PAYMENT",
        "totalAmount": 256000,
        "expiresAt": "2026-08-30T05:30:00.000Z",
        "createdAt": "2026-08-30T05:15:00.000Z"
      }
    }

底层 TypeScript 方法签名仍声明响应包含 reservation 和 order；正常路由 UI 通过
CheckoutSession confirm 取得 order，不维护全局 Reservation 状态。

### 5.5 GET /orders/{orderId}

对应手动刷新、倒计时归零，以及支付结果不确定后的状态确认。

- Path：orderId，string，例如 TKT-24082602。
- Query：当前无。
- 身份：由 `ticketing_session` Cookie 认证。

该接口已由 Phase 4 后端实现。只返回当前用户自己的 Order；订单不存在或属于其他
用户时统一返回 `404` 和 `ORDER_NOT_FOUND`。查询只读取后端正式状态，不顺手执行
过期写操作。

前端期望 response.data 直接为 TicketOrder：

    {
      "id": "TKT-24082602",
      "reservationId": "RSV-24082601",
      "eventId": "evt-concert-2026",
      "sessionId": "ses-concert-1001",
      "seatIds": [
        "ses-concert-1001-A01",
        "ses-concert-1001-A02"
      ],
      "status": "PENDING_PAYMENT",
      "totalAmount": 256000,
      "expiresAt": "2026-08-30T05:30:00.000Z",
      "createdAt": "2026-08-30T05:15:00.000Z"
    }

当数据库 `paid_at` 非 NULL 时，响应额外包含 UTC ISO 8601 的可选 `paidAt`；NULL 时
不输出该字段。当前订单页明确依赖 id、seatIds、status、totalAmount、expiresAt。
其他字段存在于类型和 mock，但页面未直接读取。

### 5.6 POST /orders/{orderId}/pay

对应异步模拟支付，无请求体。新建或复用仍在有效 grace 内的 PROCESSING Attempt 时
返回 HTTP 202：

```json
{
  "disposition": "STARTED_NEW",
  "order": {
    "id": "TKT-24082602",
    "reservationId": "RSV-24082601",
    "eventId": "evt-concert-2026",
    "sessionId": "ses-concert-1001",
    "seatIds": ["ses-concert-1001-A01", "ses-concert-1001-A02"],
    "status": "PENDING_PAYMENT",
    "totalAmount": 256000,
    "expiresAt": "2026-08-30T05:30:00.000Z",
    "createdAt": "2026-08-30T05:15:00.000Z"
  },
  "paymentAttempt": {
    "id": "PAY-24082603",
    "orderId": "TKT-24082602",
    "status": "PROCESSING",
    "startedAt": "2026-08-30T05:16:00.000Z",
    "processingDeadline": "2026-08-30T05:16:10.000Z",
    "scheduledCompleteAt": "2026-08-30T05:16:04.000Z"
  }
}
```

`disposition` 为 `STARTED_NEW / REUSED_PROCESSING / ALREADY_PAID`。Order 已 PAID 时
返回 HTTP 200，`order.status = PAID`；`paymentAttempt` 为已接纳 Attempt
或 `null`。找不到或不属于当前用户返回 404 `ORDER_NOT_FOUND`；CANCELLED 等不可支付
状态返回 409 `ORDER_NOT_PAYABLE`；已过期并完成在线收尾返回 409 `ORDER_EXPIRED`。

### 5.7 POST /orders/{orderId}/cancel

对应主动取消待支付订单。当前无请求体。

前端期望 response.data 返回 `CancelOrderResult`，例如：

    {
      "disposition": "CANCELLED_NOW",
      "order": {
        "id": "TKT-24082602",
        "reservationId": "RSV-24082601",
        "eventId": "evt-concert-2026",
        "sessionId": "ses-concert-1001",
        "seatIds": ["ses-concert-1001-A01", "ses-concert-1001-A02"],
        "status": "CANCELLED",
        "totalAmount": 256000,
        "expiresAt": "2026-08-30T05:30:00.000Z",
        "createdAt": "2026-08-30T05:15:00.000Z"
      }
    }

前端使用返回 wrapper 中的 `order` 整体替换页面订单状态，正式座位释放以后端事务为准。

`disposition` 为 `CANCELLED_NOW / ALREADY_CANCELLED`。重复取消已经 CANCELLED 的
订单仍返回 HTTP 200 和最新 TicketOrder。PAID 返回 409
`ORDER_NOT_CANCELLABLE`。PROCESSING Attempt 不阻止取消，也不会被取消路径伪造成
FAILED；若数据库权威时间已过期，在线收尾后返回 409 `ORDER_EXPIRED`。

### 5.8 GET /payment-attempts/{paymentAttemptId}

成功直接返回完整 PaymentAttempt。可选时间字段为 ISO 8601；`failureReason` 只在失败
原因存在时输出。找不到或属于其他用户均返回 404 `PAYMENT_ATTEMPT_NOT_FOUND`。
前端约每 1 秒查询，最长约 15 秒，观察 `PROCESSING` 转为 `SUCCEEDED / FAILED /
TIMED_OUT`。TIMED_OUT 只表示系统不再等待本次结果，不等价于渠道永远不会迟到成功。

### 5.9 GET /notifications 与 POST /notifications/{notificationId}/read

GET 成功直接返回当前用户的 UserNotification 数组。POST read 无请求体，成功返回更新后
的 UserNotification；重复标记已读保持幂等。不存在或属于其他用户的通知统一返回 404
`NOTIFICATION_NOT_FOUND`，避免跨用户探测。

### 5.10 CheckoutSession 临时占座冲突与 Confirm

CheckoutSession 的 create、完整集合 PUT 和 `SELECTING` Confirm 可能返回：

```text
HTTP 409
SEAT_TEMPORARILY_HELD
```

它表示一个或多个目标座位当前被其他 CheckoutSession 的 Redis 临时 Hold 占用。
该错误与以下冲突必须区分：

- `SEAT_TEMPORARILY_HELD`：SELECTING 阶段 Redis 临时竞争；
- `SEAT_CONFLICT`：正式 Reservation 阶段 PostgreSQL 最终库存冲突；
- `CHECKOUT_SESSION_VERSION_CONFLICT`：同一 C1 的 revision 冲突。

`SELECTING` Confirm 在写入 SUBMITTING 之前确保当前 selectedSeats 没有被其他 C1
临时占用。自己的 Hold 因 TTL 到期或 Redis 数据丢失而不存在时可以补建；其他 owner
返回 `SEAT_TEMPORARILY_HELD`，不会进入 SUBMITTING，也不会持久化确认 K1。
Redis 技术不可用时继续 PostgreSQL 正式确认。已经处于 SUBMITTING 的重试保持
Phase 5/6 语义，复用原 K1，不重新把 Redis Hold 当作正式确认资格。

Confirm 成功响应为 `{ "disposition", "checkoutSession" }`。`disposition` 精确为
`CONFIRMED_NOW / REUSED_CONFIRMATION / ALREADY_CONFIRMED`，前端据此区分本次确认、
复用在途确认和此前已经生成的订单。

### 5.11 GET /orders

该受保护接口直接返回当前用户的 `TicketOrder[]`，支持可选 `status`、`sessionId` 和
`limit`。当前前端订单列表使用 `status` 与 `limit=20`，选座页使用 `sessionId` 与
`limit=20` 查询本场次已有订单。非法状态或 limit 返回 400 `INVALID_ARGUMENT`；空结果
返回空数组，不暴露其他用户订单。

### 5.12 GET /events/{eventId} 与 GET /sessions/{sessionId}

两个公开详情接口分别返回单个 `TicketEvent` 与 `TicketSession`。订单深链接和路由页面
用 URL 参数及 Order 中的 `eventId / sessionId` 调用它们，不再依赖上一页的内存对象。

## 6. 前端状态流转与权威边界

    Vue Router /events
      -> GET /events
      -> /events/{eventId}/sessions
      -> GET /events/{eventId}/sessions
      -> /sessions/{sessionId}/seats
      -> GET /sessions/{sessionId}/seats
      -> seats
      -> 本地点选 selectedSeatIds / selectedSeats
      -> create / full-set PUT CheckoutSession
      -> final sync barrier
      -> POST /checkout-sessions/{id}/confirm
      -> /orders/{orderId}
      -> POST pay / PaymentAttempt polling / cancel / GET order
      -> notifications

| 状态 | 所有者 / 来源 | 说明 |
| --- | --- | --- |
| route | Vue Router | URL 保存 eventId、sessionId 或 orderId，受保护 route 由 guard 检查登录 |
| currentUser | `/auth/me` 的前端副本 | 启动恢复，401 时清空；一个 Cookie Jar 对应一个 Session |
| events / event | 后端权威数据的页面副本 | 列表和详情接口获取 |
| sessions / session | 后端权威数据的页面副本 | 列表和详情接口获取 |
| seats | 后端权威数据的前端副本 | 进入选座、刷新、订单变更后重新获取 |
| selectedSeatIds | 完全属于前端 | 是本地用户意向；服务端可能已为对应 CheckoutSession 建立 Redis 临时 Hold，但它不是正式锁座结果 |
| selectedSeats | 完全属于前端的计算值 | 从 seats 和 selectedSeatIds 派生 |
| currentCheckoutSession | 后端权威 checkpoint 的前端副本 | 包含 seatIds、revision、status；成功 PUT 后整体替换 |
| recoverableCheckoutSessions | 后端查询结果 | 多个候选必须由用户显式选择 |
| Reservation 页面状态 | **当前不存在** | 创建预订响应包含 reservation，但 route page 不单独保存全局 Reservation |
| order | 必须以后端返回为准 | OrderPage 按深链接查询，并由支付或取消响应更新 |
| paymentAttempt | 后端权威数据的页面副本 | POST pay 返回并由 GET Attempt 轮询更新 |
| notifications | 后端权威数据的前端副本 | 启动、窗口 focus 和 5 秒低频刷新 |
| 倒计时 | 前端展示状态 | 由 expiresAt - Date.now() 计算；归零不直接修改订单 |
| checkoutCreating、checkoutSyncInFlight、confirming、submittingPolling、submitUncertain | 完全属于前端 | 区分后台同步、确认屏障、结果恢复和 15 秒不确定状态 |
| paymentStarting、paymentPolling、cancelling | 完全属于前端 | 支付启动、Attempt 观察和取消互相隔离；支付观察不禁用取消 |
| loading、busy、errorMessage、noticeMessage | 完全属于前端 | 页面交互和操作反馈状态 |

边界原则：

1. 用户点选座位先改变 selectedSeatIds，并异步保存 CheckoutSession 意图和临时 Hold；只有 Phase 3 正式 Reservation 成功才是 PostgreSQL 正式锁座。
2. 正常 UI 不直接调用 POST /reservations；confirm 返回 RESERVED + order 后才进入订单页。底层 createReservation 仍保留用于 Mock 竞争和较低层测试。
3. Seat.status、Reservation.status 和 Order.status 的正式值必须以后端为准。
4. 倒计时仅用于展示；是否过期由 GET /orders/{orderId} 的返回状态决定。
5. 支付启动不等于 PAID；前端轮询 PaymentAttempt，并在终态后重新获取 Order、Seat[] 和通知，不自行推断正式终态。

## 7. 已收敛事实与联调前待确认问题

### 7.1 已落地的契约事实

1. POST /reservations 请求体字段统一为 camelCase：sessionId、seatIds；成功响应字段同样使用 camelCase。
2. price、priceFrom、totalAmount 均为整数分。前端通过统一格式化函数转换为人民币元展示，例如 128000 分显示为 ¥1,280。
3. Axios 使用 Session Cookie，unsafe method 自动携带 CSRF Header；用户身份不出现在业务请求体，也不再使用 X-User-Id。
4. 真实 API 业务错误统一提取 code 和 message，解析为 TicketApiError，并兼容当前通用异常处理。
5. 预订失败后刷新座位时保留本次预订错误提示；支付结果未知后刷新订单时保留本次支付提示。
6. Reservation 和 Order 的 expiresAt、createdAt、paidAt 使用可由 Date.parse 解析的 ISO 8601 字符串。
7. 每单最多 6 个座位；SELECTED 仍是纯前端本地选择状态。
8. Mock 已使用分为单位，并已使篮球场次 priceFrom 与该场次最低 seat.price 一致。

### 7.2 CheckoutSession revision 与恢复契约

`CheckoutSession` 必须包含整数 `revision`。座位完整集合替换请求固定为：

```json
{
  "seatIds": ["ses-concert-1001-A01"],
  "expectedRevision": 3
}
```

成功 PUT 使服务端 `revision + 1`。过期版本返回 HTTP 409、
`CHECKOUT_SESSION_VERSION_CONFLICT`；前端不 merge 或盲重试，而是 GET 最新 C1，整体采用
服务端 `seatIds + revision` 并要求用户重新确认。`SUBMITTING` 每 2 秒 GET，最长 15 秒；
仍未确定时显示“继续原确认”，不会显示预订失败。Phase 6 不使用 Redis 预占座。

### 7.3 Phase 7 Redis 临时占座契约

已有 C1 时，前端调用 `getSeats(sessionId, checkoutSessionId)`；恢复 C1 后也会以该
C1 上下文重新刷新座位图。`SEAT_TEMPORARILY_HELD` 是明确业务冲突：前端刷新座位图、
保留合理的本地购买意图、不自动 merge，也不进入“确认结果未知”的 SUBMITTING
polling。Confirm barrier 的最终 PUT 遇到该冲突时不会调用 confirm endpoint。
Redis 不可用的降级由后端处理，前端不感知 Redis 故障细节。

### 7.4 仍需联调确认的问题

1. **availability 是中文枚举。** 当前类型只接受充足、紧张、售罄，且样式类直接拼接该值；需要确认未来国际化时是否调整。
2. **Event.status 当前展示有限。** 类型允许 COMING_SOON，但活动卡的交互仍主要围绕 ON_SALE Demo。
3. **cover 当前是前端静态路径。** GET /events 返回 `/images/...`，生产资源部署路径仍需与静态服务器保持一致。
4. **订单列表是有界数组而非分页对象。** 当前支持 filter 和 limit，不返回分页元数据；更大历史列表留待后续。

## 8. 后端最小对接清单

在不修改当前前端代码的前提下，后端至少需要满足：

- 接受开发代理转发后的 /auth、/events、/sessions、/reservations、/orders 路径。
- 所有 HTTP JSON 字段使用 camelCase；POST /reservations 接受 sessionId 和 seatIds。
- 通过 opaque Session Cookie 认证受保护接口；业务身份来自 AuthContext，不接受 X-User-Id。
- 支持 `ticketing_csrf` + `X-CSRF-Token` + Origin 校验，并返回真实 401/403/503 认证错误。
- 成功响应直接返回本文所列 JSON，不增加 data 外层包装。
- 业务失败响应返回字符串类型的 code 和 message。
- GET seats 接受可选 checkoutSessionId，并按当前 C1 上下文叠加 Redis 临时 Hold。
- 临时占座冲突返回 HTTP 409 和 SEAT_TEMPORARILY_HELD。
- price、priceFrom、totalAmount 使用整数分。
- 使用本文列出的精确状态字符串。
- expiresAt、createdAt、paidAt 使用可被浏览器 Date.parse 正确解析的 ISO 8601 字符串。
- 支付启动返回 PaymentStartResult；取消和订单查询返回完整 TicketOrder；创建预订返回 ReservationResult。
- Confirm、支付和取消 wrapper 返回本文列出的精确 disposition。
- GET /orders 支持 status/sessionId/limit；Event 与 Session 详情接口支持订单深链接恢复。
- PaymentAttempt、通知列表和通知已读接口按当前用户隔离；通知已读保持幂等。
- 座位竞争、支付、取消或超时处理后，GET seats 和 GET order 能返回一致的最终状态。

其中异步支付、取消、PaymentAttempt polling、自动退款与用户通知已在 Phase 8 实现。

