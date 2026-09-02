# 前端接口契约文档

> 调查对象：当前仓库中的 Vue 3 前端实际代码。  
> 主要依据：frontend/src/types.ts、frontend/src/api/ticketApi.ts、frontend/src/App.vue、frontend/src/views 和 frontend/src/components。  
> 本文只记录当前前端已经存在的数据模型、调用方式和状态语义，不代表后端最终方案。

## 1. 当前 API 运行方式

- API 封装位于 frontend/src/api/ticketApi.ts。
- Axios 的 baseURL 为 **/api**，超时时间为 **8000 ms**，请求统一携带 **Content-Type: application/json** 和 Demo 用户请求头 **X-User-Id: U-1001**。
- 开发环境会把 **/api** 代理到 **http://localhost:8080**，并移除路径前缀 **/api**。例如浏览器请求 **/api/events**，C++ 后端实际接收 **/events**。
- 当 **VITE_USE_MOCK_API** 不等于字符串 **false** 时使用 mock；仓库中的 .env.example 当前为 **true**。
- 真实 API 成功响应直接读取 Axios 的 response.data，不使用统一 data 外层包装，也不做响应字段转换。失败响应提取 `code` 和 `message`，并转换为兼容现有处理逻辑的 TicketApiError。
- 当前实际代码存在以下真实后端调用：

| 前端方法 | HTTP |
| --- | --- |
| getEvents | GET /events |
| getSessions | GET /events/{eventId}/sessions |
| getSeats | GET /sessions/{sessionId}/seats |
| createReservation | POST /reservations |
| createCheckoutSession | POST /checkout-sessions |
| getCheckoutSession | GET /checkout-sessions/{id} |
| listRecoverableCheckoutSessions | GET /checkout-sessions?sessionId=...&recoverable=true |
| replaceCheckoutSessionSeats | PUT /checkout-sessions/{id}/seats |
| confirmCheckoutSession | POST /checkout-sessions/{id}/confirm |
| abandonCheckoutSession | POST /checkout-sessions/{id}/abandon |
| getOrder | GET /orders/{orderId} |
| payOrder | POST /orders/{orderId}/pay |
| cancelOrder | POST /orders/{orderId}/cancel |

当前代码**没有**调用 GET /events/{eventId}。活动详情数据直接复用活动列表中选中的 TicketEvent。  
expireOrderForDemo 仅用于 mock 演示；真实 API 模式会直接报 MOCK_ONLY，不能视为后端接口契约。

当前后端已实际打通 `GET /orders/{orderId}`；支付和取消接口仍是后续能力。

## 2. 页面、组件与数据需求

前端没有 Vue Router。App.vue 使用 currentView 在四个视图间切换；购票会话通过服务端恢复，`sessionStorage` 只保存当前 Tab 的 `checkoutSessionId + sessionId` locator。

| 页面 / 视图 | 主要组件 | 当前依赖数据 | 当前来源 | 后端联调需求 |
| --- | --- | --- | --- | --- |
| 活动列表 EventListView | EventCard | events、loading | App 挂载后调用 ticketApi.getEvents；默认来自 eventsSeed mock | TicketEvent[] 必须由 GET /events 提供 |
| 场次选择 SessionListView | SessionCard | currentEvent、sessions、loading | currentEvent 来自用户刚选中的活动对象；sessions 来自 getSessions(event.id) | TicketSession[] 必须由 GET /events/{eventId}/sessions 提供 |
| 座位选择 SeatSelectionView | SeatGrid、SeatItem、SelectedSeats、RecoverableCheckoutPanel | currentEvent、currentSession、seats、selectedSeatIds、currentCheckoutSession、恢复候选与确认状态 | seats 来自 getSeats；selectedSeatIds 为当前 UI 意图；CheckoutSession 是服务端 checkpoint | Seat[] 与 CheckoutSession API；提交时后端最终确认是否锁座成功 |
| 订单 OrderView | OrderSummary | currentOrder、currentEvent、currentSession、seats、busy、倒计时 | currentOrder 来自创建预订或订单接口；event/session/seats 沿用 App 内存；倒计时由 expiresAt 与浏览器当前时间计算 | 创建、查询、支付、取消后的 TicketOrder 必须由后端返回；状态变更后前端会重新获取 seats |

页面中的以下内容目前是纯前端常量，不来自接口：

- 品牌名称、页头步骤和说明文案。
- 当前用户展示值和 Demo 请求头用户值 **U-1001**。
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
| AVAILABLE | 是 | 最近一次座位接口返回可选；允许本地点选，但不代表已经锁座 |
| SELECTED | **否** | 纯前端派生状态：Seat.status 为 AVAILABLE 且 seat.id 位于 selectedSeatIds 中 |
| HELD | 是 | 已被有效预订临时锁定；前端禁止点击 |
| SOLD | 是 | 已售出；前端禁止点击 |

用户点选 AVAILABLE 座位时不会发请求，也不会修改 Seat.status，只会增删 selectedSeatIds。selectedSeats 是从 seats 中按 selectedSeatIds 计算得到的 Seat[]。

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

订单页展示活动、场次和座位详细信息时，使用的是 App 内存中的 currentEvent、currentSession 和 seats，并非 TicketOrder 自身提供的展开数据。

## 4. 页面操作与接口调用关系

| 时机 / 操作 | 当前前端行为 | 接口与数据 |
| --- | --- | --- |
| App 首次挂载 | loadEvents | GET /events，保存 TicketEvent[] 到 events |
| 点击“查看场次” | 保存整个 event 为 currentEvent，切换视图并加载场次 | GET /events/{event.id}/sessions |
| 点击“进入选座” | 保存整个 session 为 currentSession，清空本地选择并加载座位 | GET /sessions/{session.id}/seats |
| 进入选座 | 先按 locator GET；无有效 locator 时查询全部可恢复会话且不自动选最新一条 | GET CheckoutSession / list recoverable |
| 第一次点击 AVAILABLE 座位 | 立即更新 selectedSeatIds，并异步创建唯一 C1 | POST /checkout-sessions |
| 后续 add/remove | UI 立即更新；同一 C1 以 single-flight PUT 同步最新完整集合 | PUT seats，携带 seatIds、expectedRevision |
| 点击刷新座位 | 重新获取 Seat[]；不删除恢复出的 HELD/SOLD 意图座位 | GET /sessions/{session.id}/seats |
| 点击“提交预订” | 禁止继续编辑，等待 create/PUT 并把最终集合 flush 到服务端 checkpoint，再正式确认 | POST /checkout-sessions/{id}/confirm |
| 确认成功 | 使用 CheckoutSession 响应中的 order，刷新座位图并进入订单页 | confirm 响应 RESERVED CheckoutSession；随后 GET seats |
| SEAT_CONFLICT | GET 当前 C1 回到 SELECTING，保留服务端意图并刷新 Seat Map | GET CheckoutSession + GET seats |
| 点击订单“刷新状态” | 更新 currentOrder，并同步刷新座位 | GET /orders/{order.id}；随后 GET /sessions/{session.id}/seats |
| 倒计时归零 | 倒计时组件只发出 expiryReached，不自行把订单设为 EXPIRED | GET /orders/{order.id}，以后端状态为准 |
| 点击“模拟支付” | 用返回值替换 currentOrder，再刷新 seats | POST /orders/{order.id}/pay；随后 GET seats |
| 点击“取消订单” | 用返回值替换 currentOrder，再刷新 seats | POST /orders/{order.id}/cancel；随后 GET seats |
| 点击“模拟订单超时” | 仅 mock 模式调用本地 expireOrderForDemo | 不对应真实后端接口 |

支付请求出错时，前端不会直接认定支付失败，而是显示“支付请求结果未知”并调用 GET /orders/{orderId} 重新查询结果；刷新订单过程会保留本次支付提示。

## 5. 当前前端期望的接口契约

所有真实 API 请求统一携带 `X-User-Id: U-1001`。成功响应的 JSON 直接作为 `response.data` 使用；业务失败响应统一为：

    {
      "code": "SEAT_CONFLICT",
      "message": "Selected seats are no longer available"
    }

Axios 响应拦截器会提取字符串类型的 `code` 和 `message`，转换为 TicketApiError；无法匹配该结构的异常仍交给现有通用错误处理逻辑。

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
- Query：当前无。

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

### 5.4 POST /reservations

对应点击“提交预订”。当前请求 JSON 使用 camelCase：

    {
      "sessionId": "ses-concert-1001",
      "seatIds": [
        "ses-concert-1001-A01",
        "ses-concert-1001-A02"
      ]
    }

当前请求不包含 userId、价格或前端计算的 totalAmount；用户由 `X-User-Id` 请求头提供。前端要求后端以 sessionId 和 seatIds 为准，原子确认全部座位。

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

App 当前运行时只读取 order，但 TypeScript 方法签名明确声明响应包含 reservation 和 order。

### 5.5 GET /orders/{orderId}

对应手动刷新、倒计时归零，以及支付结果不确定后的状态确认。

- Path：orderId，string，例如 TKT-24082602。
- Query：当前无。
- Header：`X-User-Id`，当前 Demo 值为 `U-1001`。

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

对应模拟支付。当前无请求体。

前端期望 response.data 直接返回更新后的 TicketOrder，例如：

    {
      "id": "TKT-24082602",
      "reservationId": "RSV-24082601",
      "eventId": "evt-concert-2026",
      "sessionId": "ses-concert-1001",
      "seatIds": [
        "ses-concert-1001-A01",
        "ses-concert-1001-A02"
      ],
      "status": "PAID",
      "totalAmount": 256000,
      "expiresAt": "2026-08-30T05:30:00.000Z",
      "createdAt": "2026-08-30T05:15:00.000Z",
      "paidAt": "2026-08-30T05:17:00.000Z"
    }

前端使用返回对象整体替换 currentOrder，随后重新获取座位图，期望对应座位最终为 SOLD。

### 5.7 POST /orders/{orderId}/cancel

对应主动取消待支付订单。当前无请求体。

前端期望 response.data 直接返回更新后的 TicketOrder，例如：

    {
      "id": "TKT-24082602",
      "reservationId": "RSV-24082601",
      "eventId": "evt-concert-2026",
      "sessionId": "ses-concert-1001",
      "seatIds": [
        "ses-concert-1001-A01",
        "ses-concert-1001-A02"
      ],
      "status": "CANCELLED",
      "totalAmount": 256000,
      "expiresAt": "2026-08-30T05:30:00.000Z",
      "createdAt": "2026-08-30T05:15:00.000Z"
    }

前端使用返回对象整体替换 currentOrder，随后重新获取座位图，期望原 HELD 座位已经恢复为 AVAILABLE。

## 6. 前端状态流转与权威边界

    currentView = event-list
      -> GET /events
      -> currentEvent
      -> GET /events/{eventId}/sessions
      -> currentSession
      -> GET /sessions/{sessionId}/seats
      -> seats
      -> 本地点选 selectedSeatIds / selectedSeats
      -> create / full-set PUT CheckoutSession
      -> final sync barrier
      -> POST /checkout-sessions/{id}/confirm
      -> currentOrder
      -> pay / cancel / GET order

| 状态 | 所有者 / 来源 | 说明 |
| --- | --- | --- |
| currentView | 完全属于前端 | event-list、session-list、seat-selection、order |
| events | 后端权威数据的前端副本 | 首次挂载获取 |
| currentEvent | 前端内存引用 | 从 events 中选中；没有活动详情请求 |
| sessions | 后端权威数据的前端副本 | 选择活动后获取 |
| currentSession | 前端内存引用 | 从 sessions 中选中 |
| seats | 后端权威数据的前端副本 | 进入选座、刷新、订单变更后重新获取 |
| selectedSeatIds | 完全属于前端 | 只是用户意向；不是锁座结果 |
| selectedSeats | 完全属于前端的计算值 | 从 seats 和 selectedSeatIds 派生 |
| currentCheckoutSession | 后端权威 checkpoint 的前端副本 | 包含 seatIds、revision、status；成功 PUT 后整体替换 |
| recoverableCheckoutSessions | 后端查询结果 | 多个候选必须由用户显式选择 |
| currentReservation | **当前不存在** | 创建预订响应包含 reservation，但 App 未保存 |
| currentOrder | 必须以后端返回为准 | 来自创建、查询、支付或取消接口 |
| 倒计时 | 前端展示状态 | 由 expiresAt - Date.now() 计算；归零不直接修改订单 |
| checkoutCreating、checkoutSyncInFlight、confirming、submittingPolling、submitUncertain | 完全属于前端 | 区分后台同步、确认屏障、结果恢复和 15 秒不确定状态 |
| loading、busy、errorMessage、noticeMessage | 完全属于前端 | 页面交互和订单操作反馈状态 |

边界原则：

1. 用户点选座位只改变 selectedSeatIds，不能视为锁座。
2. 正常 UI 不直接调用 POST /reservations；confirm 返回 RESERVED + order 后才进入订单页。底层 createReservation 仍保留用于 Mock 竞争和较低层测试。
3. Seat.status、Reservation.status 和 Order.status 的正式值必须以后端为准。
4. 倒计时仅用于展示；是否过期由 GET /orders/{orderId} 的返回状态决定。
5. 支付或取消后，前端既采用返回的 TicketOrder，也会重新获取 Seat[]，不自行推断座位最终状态。

## 7. 已收敛事实与联调前待确认问题

### 7.1 已落地的契约事实

1. POST /reservations 请求体字段统一为 camelCase：sessionId、seatIds；成功响应字段同样使用 camelCase。
2. price、priceFrom、totalAmount 均为整数分。前端通过统一格式化函数转换为人民币元展示，例如 128000 分显示为 ¥1,280。
3. 所有 Axios 请求统一携带 Demo 用户请求头 X-User-Id: U-1001，预订请求体不重复提交 userId。
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

### 7.2 仍需联调确认的问题

1. **Reservation 返回但未保存。** ReservationResult 包含 reservation，App 当前只保存 order；后端仍需按当前类型完整返回。
2. **订单页不能仅靠 GET /orders/{orderId} 独立恢复。** 页面展示依赖内存中的 currentEvent、currentSession 和完整 seats；刷新浏览器后这些状态会丢失。
3. **availability 是中文枚举。** 当前类型只接受充足、紧张、售罄，且样式类直接拼接该值；需要确认它由后端如何计算，以及它与 Session.status 的关系。
4. **Event.status 当前未生效。** 类型允许 COMING_SOON，但活动卡始终显示“正在售票”，也不会根据 status 禁用进入流程。
5. **cover 当前是前端静态路径。** GET /events mock 返回 /images/...；真实后端应返回何种可访问 URL 或资源标识尚未确认。
6. **空列表、分页和排序没有契约。** 当前所有 GET 都假定直接返回完整数组，没有分页参数、分页元数据或排序字段。
7. **支付和取消的幂等性与并发 HTTP 语义仍需确认。** 当前前端依赖成功时返回最新 TicketOrder，失败时重新查询订单。

当前前端没有 GET /events/{eventId} 调用，活动详情复用 GET /events 返回的完整 TicketEvent；该接口不属于当前 MVP 对接清单。

## 8. 后端最小对接清单

在不修改当前前端代码的前提下，后端至少需要满足：

- 接受开发代理转发后的 /events、/sessions、/reservations、/orders 路径。
- 所有 HTTP JSON 字段使用 camelCase；POST /reservations 接受 sessionId 和 seatIds。
- 所有请求通过 X-User-Id 请求头接收 Demo 用户 U-1001。
- 成功响应直接返回本文所列 JSON，不增加 data 外层包装。
- 业务失败响应返回字符串类型的 code 和 message。
- price、priceFrom、totalAmount 使用整数分。
- 使用本文列出的精确状态字符串。
- expiresAt、createdAt、paidAt 使用可被浏览器 Date.parse 正确解析的 ISO 8601 字符串。
- 创建、支付、取消和订单查询返回完整 TicketOrder；创建预订返回 ReservationResult。
- 座位竞争、支付、取消或超时处理后，GET seats 和 GET order 能返回一致的最终状态。

其中订单查询和超时处理已在 Phase 4 后端实现并完成真实联调；支付与取消仍待后续
Phase 实现。

