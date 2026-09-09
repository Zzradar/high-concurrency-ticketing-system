# 高并发票务预订系统 MVP 前端方案设计

## 1. 前端目标

前端 MVP 的目标不是构建一个完整票务平台，而是为后端核心预订能力提供一个清晰、可演示、可联调的用户界面。

第一阶段需要完整展示以下业务流程：

```text
活动列表
  ↓
选择场次
  ↓
查看座位图
  ↓
选择一个或多个座位
  ↓
提交预订
  ↓
进入待支付订单
  ↓
模拟支付 / 主动取消 / 等待超时
```

前端的重点是把座位状态、预订状态和订单状态直观展示出来，方便后续验证后端的并发预订和状态管理逻辑。

---

## 2. 技术栈

### 2.1 Vue 3

使用 Vue 3 作为前端框架。

选择原因：

- 座位状态、已选座位、订单状态和支付倒计时都属于典型的响应式状态。
- Vue 可以让页面根据数据变化自动更新，避免手动操作大量 DOM。
- 项目规模不大，但已经超过纯静态 HTML Demo 的复杂度。
- 后续接入 WebSocket 实时座位状态时，也可以继续沿用现有组件和状态结构。

---

### 2.2 Vite

使用 Vite 作为开发和构建工具。

主要用途：

- 本地开发服务器。
- 热更新。
- 前端打包。
- 配置后端 API 代理。

Node.js 仅作为前端开发环境，不承担本项目的业务后端职责。

---

### 2.3 TypeScript

MVP 当前使用 TypeScript，入口文件为 `src/main.ts`。

原因是：

- 当前数据模型和 API 契约已经通过 TypeScript 类型表达。
- Vue 组件、工具函数和测试均使用 TypeScript 源文件。
- 类型检查有助于保持活动、场次、座位、Reservation 和 Order 数据一致。

---

### 2.4 原生 CSS

第一阶段使用原生 CSS 实现页面样式。

暂时不引入：

- Quasar。
- Element Plus。
- Tailwind CSS。

主要原因是当前页面数量少，座位图又有较强的定制性，直接使用 CSS 更容易控制不同座位状态的视觉表现。

---

## 3. 暂不引入的前端能力

MVP 第一阶段暂不使用：

- Pinia。
- Quasar。
- Element Plus。
- WebSocket。
- SSR。
- 复杂权限系统。

原因是第一阶段只有少量页面和状态，使用 Vue 自身的响应式能力即可完成。

Phase 9 已引入 Vue Router；跨页面全局业务状态仍不足以要求 Pinia。

---

## 4. 页面结构

MVP 由 Vue Router 管理登录、活动、场次、选座、订单列表和订单详情页面。

### 4.1 活动列表页

用于展示当前可售票的活动。

每个活动卡片主要显示：

- 活动名称。
- 简短描述。
- 活动状态。
- 查看场次按钮。

示意：

```text
--------------------------------
周杰伦 2026 世界巡演

上海站

[查看场次]
--------------------------------

篮球总决赛

体育中心

[查看场次]
--------------------------------
```

MVP 不实现：

- 搜索。
- 推荐。
- 分类筛选。
- 营销 Banner。
- 活动后台管理。

---

### 4.2 场次选择页

用户进入某个活动后，展示该活动对应的场次列表。

每个场次主要显示：

- 场次时间。
- 场馆或影厅。
- 售票状态。
- 进入选座按钮。

示意：

```text
周杰伦 2026 世界巡演

2026-10-01 19:30
上海体育馆
[选择场次]

2026-10-02 19:30
上海体育馆
[选择场次]
```

---

### 4.3 座位选择页

这是 MVP 前端最重要的页面。

页面主要由两部分组成：

1. 座位图。
2. 当前选择信息。

座位图需要至少展示以下状态：

- AVAILABLE：可选择。
- SELECTED：当前用户已选择但尚未提交。
- HELD：已经被其他用户临时锁定。
- SOLD：已经正式售出。

示意：

```text
                舞 台

        01   02   03   04   05

A       ○    ○    ×    ○    ○

B       ○    ●    ●    ×    ○

C       ○    ○    ○    ○    ○
```

含义：

```text
○  可选择
●  当前已选择
×  不可选择
```

右侧或下方展示：

```text
已选座位

B02
B03

共 2 张

[提交预订]
```

用户点击可选座位时：

- 如果当前未选择，则加入 selectedSeats。
- 如果已经选择，则取消选择。
- HELD 和 SOLD 状态不可点击。
- UI 先本地乐观更新，再通过 CheckoutSession create/full-set PUT 异步同步购买意图和 Redis 临时 Hold。

---

### 4.4 订单页

用户锁座成功后进入订单页面。

展示：

- 订单号。
- 活动名称。
- 场次。
- 已预订座位。
- 当前订单状态。
- 支付截止时间。
- 剩余支付时间。
- 模拟支付按钮。
- 取消订单按钮。

示意：

```text
订单号：10001

活动：
周杰伦 2026 世界巡演

座位：
A01
A02

状态：
待支付

剩余支付时间：
14:32

[模拟支付]

[取消订单]
```

支付成功后：

```text
状态：
已支付
```

取消后：

```text
状态：
已取消
```

超时后：

```text
状态：
已过期
```

---

## 5. 前端状态设计

MVP 不使用 Pinia。

当前各 route page 使用 Vue `ref` 维护页面局部状态，`authState` 维护共享当前用户，
`App.vue` 只维护通知中心和壳层状态。核心状态包括：

```text
event / session

seats

selectedSeats

currentCheckoutSession

recoverableCheckoutSessions

order

currentPaymentAttempt

notifications

checkoutCreating / checkoutSyncInFlight / confirming

submittingPolling / submitUncertain

paymentStarting / paymentPolling / cancelling
```

其中：

### event

当前选择的活动。

### session

当前选择的场次。

### seats

当前场次完整座位数据。

例如：

```text
id
label
row
number
status
```

### selectedSeats

当前用户在前端临时选中的座位。

这些座位尚未真正锁定；`selectedSeatIds` 是 UI 最终意图，服务端 CheckoutSession 的
`seatIds + revision` 是最近一次成功保存的 checkpoint。

Phase 7 中，成功的 CheckoutSession create/PUT 还会尝试建立或刷新 Redis 临时 Hold；
它只是 SELECTING 阶段的短期竞争保护，不等于 PostgreSQL 正式 Reservation 锁座。

只有最终同步屏障完成并且 CheckoutSession confirm 成功返回后，才认为真正锁座成功。

### currentCheckoutSession

当前服务端购票会话。每个 C1 最多一个完整集合 PUT in-flight；成功响应整体更新
`seatIds + revision`。普通后台同步不复用订单操作的 `busy`。

### currentReservation（未来规划 / 目标状态）

当前前端没有维护全局 `currentReservation`；确认成功后进入 Order 深链接，页面以
后端返回的 Order 为准。是否在后续保存 Reservation 留待未来规划。

### order

当前订单信息。

### currentPaymentAttempt 与 notifications

`currentPaymentAttempt` 保存当前异步支付尝试；`notifications` 保存通知中心列表。
支付轮询与 Phase 6 的 Checkout SUBMITTING 轮询使用独立状态、generation 和 timer，
避免两个会话恢复流程互相取消或覆盖。

### route 与 currentUser

Vue Router 的 URL 保存 eventId、sessionId 或 orderId；`authState.currentUser` 由
`/auth/me` 恢复。订单列表和订单详情 route 需要登录，公开活动和选座 route 可直接浏览。

---

## 6. 前后端数据边界

前端不能自行决定座位最终状态。

例如：

```text
用户看到 A01 = AVAILABLE
```

只能代表最近一次查询结果中 A01 可售。

用户点击“提交预订”后，前端必须等待后端返回最终结果。

如果后端返回：

```text
A01 已被其他用户抢占
```

前端需要：

1. 提示预订失败。
2. 重新请求座位图。
3. 更新 A01 的状态。

因此前端负责：

- 展示。
- 用户交互。
- 本地乐观选择和 CheckoutSession 同步编排。

后端负责：

- SELECTING 阶段的 Redis 临时占座与降级。
- 真正锁座。
- 防止重复预订。
- 创建订单。
- 支付状态。
- 超时状态。
- 最终座位状态。

---

## 7. API 交互设计

MVP 前端至少需要调用以下接口。

### 认证

```text
POST /auth/login
GET /auth/me
POST /auth/logout
```

启动时 `/auth/me` 恢复当前用户；LoginView 提交用户名和密码。Session Token 位于
HttpOnly Cookie，前端不读取；logout 清除当前用户、通知和当前用户命名空间的
Checkout locator。

### 活动

```text
GET /events
```

获取活动列表。当前前端直接复用列表中的完整活动对象，不调用 GET /events/{eventId}。
路由页同时使用 `GET /events/{eventId}` 恢复活动详情。

---

### 场次

```text
GET /events/{eventId}/sessions
GET /sessions/{sessionId}
```

获取活动场次。

---

### 座位

```text
GET /sessions/{sessionId}/seats?checkoutSessionId={optionalCheckoutSessionId}
```

获取当前场次座位图。已有 C1 时携带其 ID；当前 C1 自己的 Redis Hold 不覆盖 PG
AVAILABLE，其他 C1 的 live Hold 将 PG AVAILABLE 表现为 HELD。Redis 读取失败时后端
退化为纯 PostgreSQL seat map。

---

### 预订

```text
POST /reservations
```

提交：

```text
sessionId
seatIds[]
```

后端返回 ReservationResult：

- reservation。
- order。
- reservation 和 order 中的 expiresAt 使用 ISO 8601 字符串。
- price、priceFrom、totalAmount 均使用整数分，前端统一格式化为人民币元展示。

正常页面通过 CheckoutSession confirm 间接复用该正式预订能力，不直接提交用户 ID。

---

### 订单

```text
GET /orders?status=...&sessionId=...&limit=...
GET /orders/{orderId}
```

查询订单。

```text
POST /orders/{orderId}/pay
```

启动或复用异步模拟支付，通常返回 HTTP 202 和 PROCESSING PaymentAttempt，不代表订单
已 PAID。前端随后约每 1 秒调用：

```text
GET /payment-attempts/{paymentAttemptId}
```

最多主动观察约 15 秒。Attempt 终态后重新查询订单、座位和通知。

```text
POST /orders/{orderId}/cancel
```

主动取消。

```text
GET /notifications
POST /notifications/{notificationId}/read
```

获取用户通知并幂等标记已读。

当前前端使用 axios。

Axios 请求统一封装于：

```text
src/api/ticketApi.ts
```

该封装启用 `withCredentials`，unsafe method 自动把 `ticketing_csrf` Cookie 写入
`X-CSRF-Token`，不再发送 `X-User-Id`；包含 code、message 的业务错误解析为
TicketApiError，401 同时清理前端认证状态。

---

## 8. 组件设计

建议保持组件数量适中。

目录可以设计为：

```text
src/
├── api/
│   └── ticketApi.ts
│
├── components/
│   ├── EventCard.vue
│   ├── SessionCard.vue
│   ├── SeatGrid.vue
│   ├── SeatItem.vue
│   ├── SelectedSeats.vue
│   └── OrderSummary.vue
│
├── views/
│   ├── EventListView.vue
│   ├── SessionListView.vue
│   ├── SeatSelectionView.vue
│   └── OrderView.vue
│
├── App.vue
└── main.ts
```

其中：

### SeatItem.vue

负责单个座位。

根据状态决定：

- 是否可点击。
- 显示样式。
- 点击行为。

### SeatGrid.vue

负责座位布局。

接收完整 seats 数据，并按行展示。

### SelectedSeats.vue

展示当前用户本地选择的座位。

### OrderSummary.vue

展示当前订单状态和支付倒计时。

---

## 9. 座位状态展示原则

前端需要明确区分：

```text
AVAILABLE
SELECTED
HELD
SOLD
```

其中 SELECTED 只存在于前端本地。

后端实际状态主要是：

```text
AVAILABLE
HELD
SOLD
```

前端展示规则：

```text
AVAILABLE
且 seat.id 在 selectedSeats 中
    ↓
显示 SELECTED
```

这样不需要为了用户点击一下座位就直接修改 PostgreSQL 正式库存状态。

用户点选后会异步调用 CheckoutSession create/full-set PUT 取得临时 Hold；只有
CheckoutSession confirm 复用 Phase 3 正式 Reservation 成功后，才成为 PostgreSQL
正式 HELD。API 为其他 C1 的 Redis Hold 复用 HELD 展示，但它不等于数据库正式 HELD。

---

## 10. 支付倒计时

订单创建成功后，后端返回绝对过期时间：

```text
expiresAt
```

前端不自己计算“15 分钟以后”作为最终依据。

前端根据：

```text
expiresAt - 当前时间
```

显示倒计时。

例如：

```text
14:32
```

倒计时归零后：

- 禁用支付按钮。
- 重新查询订单状态。
- 由后端返回订单是否已经进入 EXPIRED。

前端倒计时只用于显示。

真正是否超时由后端数据库中的 expiresAt 决定。

`expiresAt` 是允许开始支付的截止时间，不是要求渠道在该时刻前完成。截止前创建的
PROCESSING Attempt 有后端约 10 秒的处理宽限；前端倒计时不会自行实现或延长该宽限。

### 异步支付交互

支付启动、支付观察和取消分别使用 `paymentStarting`、`paymentPolling`、`cancelling`。
支付启动或 polling 时禁用 Pay，Cancel 仍可点击。取消不停止当前 Attempt polling；若
随后观察到未被订单接纳的迟到 SUCCEEDED，前端刷新通知并提示查看自动退款结果。

右上角 Bell 展示未读数和通知列表；App 启动、窗口重新 focus 以及每 5 秒低频刷新通知，
点击通知调用 read 接口。通知刷新是 best effort，不干扰选座、确认或支付主流程。

---

## 11. 错误处理

前端至少需要处理以下场景。

### 座位竞争失败

用户提交 A01、A02，但其中一个已经被其他用户抢走。

页面提示：

```text
所选座位已发生变化，请重新选择。
```

然后刷新座位图，同时保留本次座位竞争提示。

---

### 临时占座冲突

`SEAT_TEMPORARILY_HELD`（座位被其他购票会话临时锁定）是选座阶段的明确业务冲突。首次创建失败时，页面保留请求前的选择，直接刷新动态座位状态；已有购票会话更新失败时，先读取服务端会话恢复选择和版本，再复用恢复流程中的一次动态刷新。读取会话失败仍尽力刷新一次；动态刷新本身失败不立即重复请求。失败请求中的新座位集合不会写成成功选择，也不会进入确认结果未知的轮询。

刷新成功显示“所选座位刚被其他用户临时锁定，座位状态已刷新，请重新选择。”刷新失败显示“所选座位刚被其他用户临时锁定，最新座位状态暂未取得，请点击‘刷新座位状态’后重试。”失败时保留最后成功座位图和合理选择，并展示不阻断页面的状态警告。页面以完整动态快照判断哪个座位被锁定，不根据刚点击的座位编号推测库存。

---

### 订单已过期

用户在倒计时结束附近点击支付，但后端已经把订单置为 EXPIRED。

前端以服务端返回结果为准，展示：

```text
订单已过期，座位已释放。
```

---

### 网络错误

请求失败时：

- 显示明确错误提示。
- 不擅自修改业务状态。
- 允许用户重新查询。

例如支付启动请求网络超时时，不能直接认为支付失败，应重新查询订单状态，并在查询
过程中保留“支付请求结果未知”提示。已获得 PaymentAttempt ID 后，以 Attempt 查询结果
区分 SUCCEEDED、FAILED 和 TIMED_OUT；TIMED_OUT 不被前端解释为渠道最终失败。

---

## 12. 页面交互原则

MVP 的交互重点是清晰，不追求复杂视觉效果。

主要原则：

- 可选座位与不可选座位区别明显。
- 当前选中座位必须容易识别。
- 提交预订前明确显示选中的座位。
- 订单状态始终显示在明显位置。
- 支付倒计时清晰可见。
- 发生竞争冲突后立即刷新座位状态。

---

## 13. MVP 暂不实现的前端能力

第一阶段暂不实现：

- WebSocket 实时座位推送。
- 多用户在线状态。
- 复杂动画。
- 座位缩放和拖拽。
- 活动搜索。
- 推荐系统。
- 用户注册、找回密码、OAuth 与复杂账号管理。
- 管理后台。
- 优惠券。
- 支付平台页面。
- 响应式移动端深度适配。
- SSR。
- 多语言。

---

## 14. 后续演进方向

### 服务端购票会话与恢复

当前前端已经接入服务端 Checkout Session。活动、场次和页面由 Vue Router 参数定位，
选座/确认流程可通过服务端恢复。

Phase 6 已围绕服务端 Checkout Session（购票会话）恢复业务状态。浏览器只保存
当前购票会话编号作为快速恢复线索，但正在选座、正在确认以及关联的 Reservation /
Order 等正式状态必须由服务器返回；浏览器存储不能成为业务事实来源。长期方案不
采用一个用户全局唯一的 `pendingReservationAttempt`，也不只依赖 Vue `ref`、
`localStorage` 或 `sessionStorage`；当前 `sessionStorage` locator 仅含
`checkoutSessionId + sessionId`。

用户进入具体 Session 后会查询可恢复会话；若同场次有多个会话，
由用户选择继续哪一个。`sessionStorage` 只作 locator，主要保存 `checkoutSessionId`，
可选保存 `eventId / sessionId`；不保存内部幂等键，也不把 selectedSeats、会话状态、
Order 状态或 Seat 状态当作权威事实。刷新后必须重新 GET 服务端；`SUBMITTING`
页面按 2 秒间隔短轮询，最长 15 秒后显示结果暂不确定和“继续原确认”。Event 页不强制查询历史会话。

同一购票会话进入 `SUBMITTING`（正在确认）后，其座位集合冻结，前端默认恢复或
查询原确认，不能换座后沿用该会话再次确认，也不能因超时静默生成第二笔订单。
这只冻结当前会话，不阻塞整个用户。用户在被明确告知上一笔仍可能成功后，可以
显式开始新的独立购票会话，旧会话继续解析；旧会话后来成功或失败都应明确通知。

当前由 `SeatSelectionPage` 编排，不引入 Pinia。Confirm 前先等待 C1 创建和已有
PUT，再把固定的最终座位集合 flush 到最新 revision；发生版本冲突时 GET 最新 C1，
不自动 merge。Phase 6 不增加 Redis 预占座。

Phase 7 在上述本地乐观 `selectedSeatIds`、serialized PUT 和 Confirm barrier 基础上
增加 Redis 临时占座。已有 C1 时 `getSeats()` 携带 `checkoutSessionId`；恢复 C1 后也会
用该上下文刷新座位图，使自己的 Hold 继续作为本地已选展示，其他 C1 Hold 的座位则
不可新选。`SEAT_TEMPORARILY_HELD` 只触发明确冲突提示和座位图刷新，不触发结果未知
恢复。Redis 不可用由后端降级，前端不感知 Redis 故障细节。

### 用户登录与多客户端一致体验（Phase 9 已完成）

`main.ts` 安装 Vue Router；当前 route 为 `/login`、`/events`、
`/events/:eventId/sessions`、`/sessions/:sessionId/seats`、`/orders` 和
`/orders/:orderId`。Router guard 在第一次导航时通过 `authState.ensureAuthLoaded()`
调用 `/auth/me`；订单列表和订单详情需要认证，活动、场次和座位浏览保持公开。未登录
用户第一次点选或确认时跳到 LoginView，并使用 redirect query 返回原 URL。

`App.vue` 是共享壳层，显示当前用户、退出入口和通知中心。Axios 使用 Cookie credentials
与 CSRF interceptor。Checkout locator 的 sessionStorage key 为
`ticketing.checkout.<userId>`，logout 或切换用户时不会继续使用旧用户定位信息。

订单详情可以直接刷新：OrderPage 按 URL 查询 Order，再用 `GET /events/{id}`、
`GET /sessions/{id}` 和座位接口恢复展示；OrderListPage 提供“我的订单”。选座页按
场次查询订单并显示 existing-order banner。Confirm、Pay、Cancel 根据
`CONFIRMED_NOW / REUSED_CONFIRMATION / ALREADY_CONFIRMED`、
`STARTED_NEW / REUSED_PROCESSING / ALREADY_PAID`、
`CANCELLED_NOW / ALREADY_CANCELLED` 显示新操作或既有结果的不同提示。

`ORDER_CREATED` 等通知每 5 秒同步，并在 window focus 时刷新；点击通知进入订单 route。
OrderPage 和 SeatSelectionPage 也在 focus 时读取正式状态，从而让同账号不同 Cookie Jar
的操作结果收敛。退出后 currentUser 和通知立即清空，旧用户轮询没有身份时不再请求。

### WebSocket 实时座位更新

后端引入实时推送后：

```text
用户 A 成功锁定 A01
        ↓
服务端广播
        ↓
正在查看同场次的其他客户端
        ↓
A01 自动变成 HELD
```

这样不再依赖手动刷新座位图。

---

### Vue Router（Phase 9 已完成）

当前正式路由为：

```text
/events

/events/:eventId/sessions

/sessions/:sessionId/seats

/orders

/orders/:orderId
```

由于使用 `createWebHistory()`，生产静态服务器必须把未知路径 fallback 到 `index.html`；
这是部署约束，不由前端路由代码或后端业务接口替代。

---

### Pinia

当用户信息、订单、活动等状态需要跨多个页面共享时，再引入 Pinia。

---

### UI 组件库

如果后续需要管理后台或大量表单，可以再引入 Quasar 或其他 UI 组件库。

座位图仍建议保留自定义组件。

---

## 15. MVP 前端完成标准

前端 MVP 完成时，用户必须能够完整演示：

```text
打开活动列表
  ↓
选择活动
  ↓
选择场次
  ↓
查看座位图
  ↓
选择多个座位
  ↓
提交预订
  ↓
进入订单页
  ↓
模拟支付 / 取消 / 等待过期
```

同时满足：

1. HELD 和 SOLD 座位不能被用户选择。
2. 本地选择状态和后端正式锁座状态明确区分。
3. 预订失败后可以重新刷新座位图。
4. 支付、取消和超时状态能够正确展示。
5. 前端不自行决定最终业务状态，一切正式状态以后端为准。
6. 异步支付轮询与 CheckoutSession 恢复轮询互不干扰，支付中仍可取消。
7. 用户可以通过通知中心看到支付、取消、过期与自动退款结果，并幂等标记已读。

MVP 第一阶段的目标是形成一个清晰、稳定、方便后端联调和演示的票务前端，而不是追求复杂视觉效果或完整商业产品能力。

## Phase 11 前端：Payment Element 与回跳恢复

官方依赖为 `@stripe/stripe-js`（npm lockfile 9.15.0），不引入 Vue wrapper 或自行收集卡号/CVC。实现依据 Stripe 官方 [confirmPayment](https://docs.stripe.com/js/payment_intents/confirm_payment)、[Payment Element](https://docs.stripe.com/js/elements_object/create_payment_element) 和 [Elements 支付接入](https://docs.stripe.com/payments/accept-a-payment?platform=web&ui=elements)。本轮保留既有 Vue/Vite/TypeScript/Axios/Playwright 版本。

- `payments/stripeClient.ts` 仅读取 `VITE_STRIPE_PUBLISHABLE_KEY`，动态导入官方包并缓存一个 Stripe Promise。simulation 不调用 helper；缺 key 不加载脚本。加载失败只输出固定安全提示，刷新页面可重新初始化。
- `StripePaymentPanel.vue` 管理 `stripeElementLoading`、ready/change complete、`stripeConfirming` 和局部错误。为每个 clientSecret 创建独立 Elements/Payment Element；secret、订单或 Attempt 变化以及 unmount 均 destroy，并使旧异步回调失效。默认字段和支付方式由 Stripe/Backend 决定。
- `OrderPage.vue` 管理 `paymentStarting`、`paymentPolling`、当前 Attempt/action 及取消状态。开始按钮与组件确认按钮分离；缺 key/不支持 action 不重复 pay。取消按钮独立可用。正式 Order 终态均只来自 Backend，终态刷新销毁组件并停止 polling。
- `confirmPayment` 使用 Elements、同源订单 `return_url` 和 `redirect: 'if_required'`；由 Stripe 处理 3DS/redirect。非跳转返回后保留准备表单并禁止重复确认，立即同步同一本地 Attempt/Order，等 Backend 终态后清理。validation error 保留可编辑表单；card error 显示脱敏 message 并同步 Backend；transport error/throw/无明确结果保留 action 进入恢复，不自动第二次 POST。
- `payments/paymentReturn.ts` 生成编码后的本地 Order/Attempt URL，并按 query 键排除 provider 参数，绝不访问 Stripe 自动追加的 secret 值。Router 在登录守卫复制 fullPath 前就移除 provider 参数，OrderPage 在恢复结束 replace 清理本地 hint。认证后先验证 Order 可访问，再读取 owner 隔离的 Attempt，比较 orderId；非法 hint/404/跨订单提示安全错误。无关 query 保留。
- page/payment/read generation 阻止路由切换、取消和较新读取之后的旧响应覆盖当前状态。已提交的 Stripe confirm Promise 没有本地撤回能力；取消后前端销毁 Element、忽略返回，迟到成功交给后端退款。
- clientSecret 不持久化，仅用作页面/Elements 内存输入。重新打开页面需用户显式 pay，由后端按 PROCESSING/deadline 条件复用；ALREADY_PAID 直接展示后端 Order。不同客户端不生成支付身份。
- 默认 simulation/null action 继续每约 1 秒观察 Attempt，最长约 15 秒，超时显示结果未定；不将 Stripe provider status 或浏览器超时当作正式 Order 终态。前端不修改后端 grace；当前 Simulation 为 10 秒，Stripe 默认 600 秒。

### Phase 11 初版验证边界（2026-09-07 历史记录）

Vitest 使用官方包 mock，覆盖 loadStripe、elements/create/mount/destroy、ready/change/loaderror、确认成功/输入错误/transport/未完成 redirect 抽象、取消、重开、多客户端已有结果、15 秒超时及回跳校验。Mock Playwright 的测试代码仅在开发模块中覆写 API 返回，不添加 production window 后门，不请求 Stripe 网络。真实 Playwright 继续使用现有 Backend/PostgreSQL/Redis 与 simulation；只恢复专用 E2E 订单数据，不改 Schema/Seed/配置。

Real Stripe Sandbox = NOT RUN；reason = missing external credentials/tooling。Stripe CLI 未安装/未执行。普通卡、真实 3DS、真实失败、Webhook forwarding 暂停后的主动 reconcile 与真实 late-success refund 均未执行。10 秒 grace 的真实 3DS 验证：未执行。mock 中等待认证 11 秒仅证明前端不会自行宣告失败，不能证明 Backend 的 10 秒规则对真实用户足够。进入发布前必须补充正常人工速度的 3DS 时间线及 accepted_at/退款证据。

验证记录（2026-09-07，本地 main，Phase11 后端基线 `02277be`）：

| 验证 | 结果 |
| --- | --- |
| Frontend Vitest full | 12 files，87/87 PASS |
| vue-tsc -b / production build | PASS |
| 根目录 E2E TypeScript | PASS |
| Mock Playwright full | 7/7 PASS（原有 4 项 + 新增 3 项） |
| Real simulation Playwright round1 | 5/5 PASS，34.1 秒 |
| Real simulation Playwright round2 | 5/5 PASS，30.4 秒；连续两轮 full pass |
| clientSecret storage/log/notification 路径及前端 secret-key 搜索 | PASS；仅内存使用，query getter 测试确认未读取 provider secret 值 |
| Real Stripe Sandbox / Stripe CLI / 真实 3DS grace | NOT RUN；缺少外部凭据和 CLI |

Mock 浏览器首次新增测试直接调用 API login，未同步页面 authState，导致 3 项被登录守卫拦截；测试改用项目 authState.login 后全量通过。生产认证逻辑未为测试添加旁路。上述 Sandbox 缺项仍是正式发布核验前置条件，本地前端实现不代表真实渠道已验收。

### Phase 11 拒付后恢复修复（2026-09-08）

修复前，card_error 与 validation_error 共用只显示错误的路径，页面不会同步当前 Attempt；“刷新状态”只读取 Order。拒付后 Order 正确保持 PENDING_PAYMENT，旧 action 却一直存在，导致“支付已准备”按钮无法解禁。任务提供的独立 Sandbox 证据为 Attempt FAILED/card_declined、Order PENDING_PAYMENT、Reservation ACTIVE、Seat HELD，且无成功通知和退款；这些证据属于独立核验，本轮未执行真实 Stripe。

现在分别处理三类错误：输入 validation_error 保留可编辑的 Element，用户可修正后再次确认；card_error 立即显示安全文案，同时查询同一本地 Attempt；unknown/network error 保留 action 并同步服务器，不把网络未知视为失败。后两者同步期间都禁止重复确认和创建新 Attempt。Backend 仍 PROCESSING 时保留原 Element/action，按约 1 秒间隔观察，最长约 15 秒；超时仍保持结果未知和支付保护，用户可刷新。

支付动作属于某次 Attempt，而不是整个 Order。只有 Backend 明确 FAILED/SUCCEEDED 后，才统一清理旧 Element/action、轮询 timer 和旧临时状态，并重新读取 Order；读取失败时仍阻止新支付，直到刷新成功。FAILED 与 Order=PENDING_PAYMENT 可以同时成立。此时重新开放开始支付，由用户显式 POST pay 获取新的 Attempt B、新 action 和新 clientSecret，不复活 A，不复用旧 iframe。Stripe TIMED_OUT 仍按结果未定恢复，不能凭浏览器时间推断渠道最终结果。

“刷新状态”和窗口 focus 会同时同步 Order 与当前 Attempt。取消/过期/已支付、页面卸载或离开、开始下一笔 Attempt 也使用同一清理路径；generation 校验阻止旧请求覆盖新 Attempt，重复清理不会重复销毁 Element，旧 timer 不会继续运行。

Backend retry contract 核对：当前查询只锁定 status=PROCESSING 的 Attempt；不存在可复用 PROCESSING 且订单仍有效时创建新 Attempt。现有 Mock API 的失败后重试测试确认 STARTED_NEW、B.id != A.id、A 仍 FAILED。本轮不改变 Provider contract、支付状态机、reconciliation、lease、migration、退款或 grace（Stripe 600 秒、Simulation 10 秒）。

回到独立 Sandbox Gate 后必须补验同一订单的完整路径：拒付卡令 A FAILED → 页面自动或手动刷新恢复 → 旧 Element 消失 → 开始支付重新可用 → B.id != A.id → 成功卡令 B SUCCEEDED、Order PAID、Reservation CONFIRMED、Seat SOLD → 成功通知恰好一次、Refund 为 0。本轮未读取本机 Stripe 凭据文件，未运行真实 Stripe，未执行发布或 Phase12。

本轮验证：Frontend Vitest full 95/95 PASS（新增 8 项恢复用例，并加强 validation、unknown 与 Mock retry 断言）；vue-tsc/production build PASS；Mock Playwright full 8/8 PASS；隔离 simulation Real Playwright full 5/5 PASS（32.3 秒）。确定性测试覆盖 PROCESSING → PROCESSING → FAILED、A → B → PAID、手动刷新、未知结果超时后保护、卡错误最终成功、查询故障以及过时 A 响应不能覆盖 B。Backend diff 为 0；真实 Sandbox 未执行，留给独立 Gate。


## Phase 12：可恢复买家全额退款与最终验收

订单详情消费服务端 `buyerRefund` 与 `refundEligibility`。首次确认框仅展示整单金额，
不收集金额输入；取消/Escape不POST。`ticketApi.createRefund` 的Axios调用不传body，
沿用Cookie/CSRF。提交标记立即禁用按钮，页面与服务层共同防止重复申请；
未知结果先GET Order恢复，不能凭超时构造新退款。HTTP 200/202不代表退款资金终态。

仅 BUYER/PROCESSING 安排退款轮询：统一在途Promise串行读取，前一次读取完成后再等待
2000ms，不使用setInterval。blur/hidden清理timer，在途请求可以结束，但后台不能继续
排下一轮；恢复立即同步，focus与visibilitychange即使先后分属一个已完成GET两侧，
仍合并为一次激活读取。后台初次挂载不启动轮询。SUCCEEDED/FAILED、卸载停止轮询。
page/read/payment代次保护路由切换、旧POST和旧GET；过期异步结果不覆盖新页面。
识别PROCESSING→SUCCEEDED后另做一次串行权威订单确认，不是并行周期请求。

PROCESSING展示“完成前订单和座位权益仍然有效”；SUCCEEDED展示退款完成、订单取消、
座位释放；FAILED展示失败与权益有效，不自动第二次申请。初次访问、刷新、重新登录
都从后端恢复，浏览器存储不作为退款事实。页面只展示本地安全字段，不显示渠道ID或原始错误。

本次支付状态修复：`stopPayment()`清除旧Attempt及action；非待支付的pay响应不重新
保存旧Attempt；旧PROCESSING提示同时要求Order=PENDING_PAYMENT。
`refreshStatus()`仅在权威读取成功且代次有效时判断解除支付保护，缺少旧attemptId
不阻止安全解锁；读失败或仍有活跃支付动作不能解锁。对应39项支付定向门禁。

退款调度断言实际在 `src/pages/OrderPage.refund.test.ts`（44项），属于158项全量门禁；
与上述39项支付测试不同。已验证串行、隐藏/失焦、恢复立即同步、两种连续事件顺序、
在途完成后停调度、后台挂载及终态停止。本轮额外输出该44项的verbose日志。

真实渠道处理中与前端可见状态已经验收；隐藏/失焦的精确请求调度由确定性自动化测试覆盖，
未把未观察到的真实浏览器时间线伪称为已观察。本轮采用获准的分层证据裁决；工具
没有暴露document.hasFocus，创建另一标签也未使原页实际hidden。没有将这些操作写成
真实隐藏通过。真实前台请求无重叠，终态停止；详见[Phase12-2B验收](phase12_2b_sandbox_validation.md)。
前述Phase11小节保留当时的历史测试边界，不代表当前Phase12状态。

当前不支持部分退款、退款失败后自动第二次退款、项目外 Dashboard 退款自动认领，
以及 succeeded → failed 后续冲正。Stripe Sandbox 不是生产资金或真实银行结算证明。


## Phase 13：账户入口、业务导航与冲突后的座位刷新

订单详情顶部“返回我的订单”固定进入订单列表，终态订单底部“继续浏览活动”固定进入活动列表；两个动作不依赖浏览器历史，因此直接链接和支付返回后的导航行为一致。

登录后，页头的用户图标、名称和下拉指示共同作为账户菜单入口，点击名称只展开或收起菜单。菜单顶部显示当前用户的显示名称和用户名，帮助多账户使用者确认身份；“我的订单”通过现有命名路由进入订单列表，“退出登录”才调用原有退出逻辑，清理认证与通知并转到登录页。菜单与通知面板互斥，点击外部、按 Escape（退出键）、点击菜单项目或切换路由都会关闭菜单。键盘 Tab（制表键）可依次到达订单链接和退出按钮，Escape 关闭后焦点回到账户触发按钮；组件卸载时移除事件监听。

顶部“活动”和“我的订单”使用真实路由链接，以完整按钮区域表现悬停、焦点和当前栏目。活动、场次与选座页面都激活活动栏目，订单列表与订单详情都激活订单栏目。匿名访问保留登录入口并隐藏订单入口。手机宽度时导航进入页头第二行，链接等宽，账户菜单和通知面板仍从右侧展开并留在视口内。

选座页首次仍先读取场次，再并行读取活动、Layout（静态座位布局）和 Availability（动态座位状态），按座位编号合并。后续手动刷新、保存选择和冲突恢复均复用 refreshSeats，只读取动态状态；拥有当前场次 CheckoutSession（购票会话）时携带其编号，不重复读取布局，也不调用旧的完整座位接口。刷新按钮始终显示可见文字，进行中改为“正在刷新”并禁用重复点击。

首次占座与已有会话更新的明确冲突均遵循前文的恢复规则，每次冲突只安排一次动态读取，恢复路径已经刷新时不再额外请求。网络故障和其他错误沿用通用提示及会话恢复，不声称被其他用户锁定。当前没有座位定时轮询、WebSocket（双向实时连接）、SSE（服务端事件推送）、增量座位协议或新增服务端缓存；窗口重新获得焦点时的已有会话恢复、确认结果查询与通知刷新保持原有边界。

2026-09-09 实施验证基于 main 与远端主分支共同的 `2c5fdb09a40524f5e04fd4b126f6b7693ac8981f`，开始时工作区干净。前端 `npm test` 最终通过 17 个文件、174 个测试；`npx vue-tsc -b` 与 `npm run build` 通过；`npm run test:e2e` 通过全部 14 个 Mock（模拟接口）浏览器测试，耗时 32.5 秒，其中账户菜单覆盖 1280、820、375 和 320 像素宽度。根目录 e2e 的 `npm run typecheck` 通过，`git diff --check` 通过。最初沙箱内 Vitest 因 `spawn EPERM` 启动失败，退出码为 1；允许测试子进程后，首轮出现异步选座尚未完成便执行下一操作的测试时序问题，修正等待条件与卸载清理后全量通过，未放宽请求次数断言。

真实后端验证在独立 `ticketing-phase10a` 栈进行，前端代理端口为 18080，PostgreSQL 与 Redis 容器均健康。`e2e` 目录执行 `npm test -- --grep "different users"`，新增竞争测试 1/1 通过，耗时 9.9 秒。持有者 `perf-user-000005` 占用 `perf-ss-001-001-000002`，竞争者 `perf-user-000006` 在旧页面点击后收到真实 409 和临时占座错误码；页面只增加一次动态请求并将 R001-002 显示为锁定中，未新增静态或旧完整座位请求。数据库确认只有持有者新增成功会话，竞争者没有新增会话，正式座位仍为 AVAILABLE。测试主动放弃占座；随后只读检查确认持有者为 ABANDONED，座位无正式预订关联。

真实全量 `e2e/npm test` 本轮未执行：运行前只读查询发现 `perf-ss-001-002-000001` 和 `perf-ss-001-004-000001` 已为 SOLD，且 demo 与原多客户端用户已有 RESERVED 会话，不满足既有全量用例的干净数据前提。本轮未重置、删除或重建任何数据库卷，也未改动标准开发栈，完整真实回归留待独立核验按单独授权准备环境。这一限制不能用模拟接口的通过结果替代。
