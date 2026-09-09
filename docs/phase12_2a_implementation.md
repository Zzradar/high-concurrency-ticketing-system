# Phase 12-2A 前端实施记录

日期：2026-09-09。范围：买家主动整单全额退款的前端；不包含真实 Stripe Sandbox 或发布。

## 1. 结果与基线

退款类型、真实 API、Mock、订单页确认交互、刷新恢复、2 秒轮询、生命周期保护及自动化验证已完成。
本阶段使用现有 Vue、自有 UI、Axios、Vitest 和 Playwright，没有增加依赖。

起始分支 `main`，HEAD `4e896ef7cf3bfcb33128df51e88808f39c458e1d`，工作区干净。
日志和 `git merge-base --is-ancestor` 均确认包含：

- `f569cc6`：Phase 12-1 后端实现。
- `41ff7f7`：旧测试兼容。
- `4e896ef`：后端门禁完成记录。

已完整读取用户提供的 Phase 12-2A 实施提示、Phase 12 买家全额退款设计，
以及仓库 `docs/phase12_1_implementation.md`。业务含义依照设计，JSON 依照当前后端。
用户批准的唯一旧测试兼容修改是在 `frontend/src/pages/OrderPage.test.ts` 的 `currentOrder`
夹具中加入 `buyerRefund: null`；其余夹具字段、所有原有断言均保持不变。
用户后续明确要求先报告、不要 commit 或 push；因此本阶段修改保留在工作区，尚未提交。

## 2. 官方项目与文档对照

- [pretix 订单生命周期](https://docs.pretix.eu/dev/api/guides/order_lifecycle.html)、
  [自助取消](https://pretix.eu/about/en/blog/20200325-cancellations/)、
  [Payment Provider](https://docs.pretix.eu/dev/development/api/payment.html)：
  退款是独立对象，自助入口受服务端政策和能力控制；不把渠道原始信息当成用户状态。
- [Vendure RefundState](https://docs.vendure.io/current/core/reference/typescript-api/payment/refund-state)、
  [PaymentService 源码](https://github.com/vendurehq/vendure/blob/master/packages/core/src/service/services/payment.service.ts)：
  Refund 关联指定 Payment，具有 Pending/Settled/Failed 生命周期。当前项目对应
  PROCESSING/SUCCEEDED/FAILED，订单票务状态单独展示。
- [Saleor Refunds](https://docs.saleor.io/developer/payments/refunds)、
  [Dashboard 变更记录](https://github.com/saleor/saleor-dashboard/blob/main/CHANGELOG.md)：
  退款请求使用已保存的交易/退款信息；异步动作通过刷新订单详情更新显示。
- [Vue watcher 清理](https://vuejs.org/guide/essentials/watchers.html)、
  [Vue 生命周期](https://vuejs.org/api/composition-api-lifecycle.html)、
  [MDN Page Visibility](https://developer.mozilla.org/en-US/docs/Web/API/Page_Visibility_API)：
  清理定时器和监听器，同时使旧异步请求失效；焦点与可见性需要分别检查。
- [Quasar Dialog](https://quasar.dev/vue-components/dialog/) 已核对。
  当前仓库实际没有 Quasar，也没有现成对话框；使用原生模态 `dialog` 和现有按钮样式，
  浏览器提供焦点约束、取消键及关闭后的焦点恢复，不引入新的 UI 框架。

采用的共同原则是独立退款状态、明确确认、服务端资格和可恢复处理中状态。
没有照搬管理员页面、部分退款、复杂政策引擎、事件总线或新轮询库。

## 3. 真实后端契约

依据 `RefundController.{h,cpp}`、`RefundService.cpp`、`RefundRepository.cpp`、
`OrderController.cpp`、`OrderRepository.cpp`、`TicketDtos.h`、`ApiResponse.h`、
`AuthFilter.cpp`、`AuthHttp.cpp`，并与 `phase12_buyer_refund_integration_test.py` 交叉确认。

| 对象/接口 | 当前后端事实 |
| --- | --- |
| POST `/orders/{orderId}/refunds` | **无请求体**；任何非空正文均被拒绝，包括 `{}`、`null` 和客户端金融字段 |
| POST 成功 JSON | 根对象为 `{disposition, refund, pollAfterMs}`，没有 `data` 或 `success` 包裹；`pollAfterMs=2000` |
| POST HTTP | CREATED / REUSED_PROCESSING 返回 202；REUSED_TERMINAL 返回 200；200 不代表资金成功 |
| GET `/refunds/{refundId}` | 200，直接返回完整 Refund，按所属订单 owner 隔离；可查询 SYSTEM 资源 |
| Refund 字段 | `id, orderId, paymentAttemptId, source, reason, status, amount, currency, createdAt`；可选 `refundedAt`、`failedAt`、`failureCode`，不存在时省略，不输出 null |
| 失败码 | 公开终态失败码为 `PROVIDER_REFUND_FAILED`；不输出渠道原始错误 |
| GET `/orders/{orderId}` | 200，直接返回 Order；`buyerRefund` 始终存在，没有买家申请时为 null；详情始终带资格 |
| buyerRefund | 仅 `id, orderId, source, reason, status, amount, currency`；source=BUYER，reason=BUYER_REQUESTED；没有 createdAt / paymentAttemptId / failureCode |
| refundEligibility | `{eligible: boolean, deadline: string, reason: null 或稳定原因码}`；原因有 ALREADY_REQUESTED / ORDER_NOT_REFUNDABLE / REFUND_WINDOW_CLOSED |
| 列表和写响应 | `buyerRefund` 为摘要或 null；列表不计算资格，DTO 在资格为空时省略字段，因此共享类型为可选资格、不可选摘要 |
| 金额与时间 | 整数最小货币单位；Refund.currency 为三位小写快照；时间是 UTC ISO 字符串，毫秒精度 |
| 错误 JSON | 根 `{code, message}`；409 ORDER_NOT_REFUNDABLE / REFUND_WINDOW_CLOSED；404 ORDER_NOT_FOUND / REFUND_NOT_FOUND；400 INVALID_REQUEST_BODY；不变量错误 500 |
| 认证与 CSRF | 认证 Cookie；修改请求要求允许的 Origin、CSRF Cookie 与 X-CSRF-Token 一致；401 UNAUTHENTICATED、403 CSRF_INVALID |

只读运行时检查使用已有 `phase12-approved` 后端 `127.0.0.1:18096` 的 demo 测试账户，
GET `/orders` 返回 200 和空列表。没有为核验创建订单、发起支付或退款；因此未取得单笔运行时
订单样本，详情字段采用上述源码与集成测试双重证据。没有读取或使用真实 Stripe 密钥。

与设计示例的差异：本地退款 ID 前缀为 RFD；订单摘要不是完整 Refund；GET Refund 可以返回
SYSTEM；失败终态字段省略规则及固定 failureCode 以 DTO 为准。没有为凑齐示例而虚构字段。

创建前的 Order/Eligibility 没有 currency，确认框按项目现有单币种金额习惯复用 `formatCny`；
Refund 创建后，展示严格使用 `formatMoney(amount, refund.currency)`。新增工具也测试了 USD、
JPY、KWD 的货币精度。当前确认框继续依赖项目的人民币订单显示约定，并不宣称已支持
跨币种订单确认；若部署包含历史非人民币订单，该显示限制需要在发布核验时明确处理。

## 4. 实现结构

| 文件 | 行为 |
| --- | --- |
| `frontend/src/types.ts` | 新增 Refund、BuyerRefundSummary、RefundEligibility、CreateRefundResult 及状态/来源/原因类型；补齐四类退款通知并保留全部旧值 |
| `frontend/src/api/ticketApi.ts` | 复用原 Axios 客户端及 Mock 切换；新增 createRefund/getRefund；POST 调用不传第二参数 |
| 同一 API 文件中的 Mock | 首次 PROCESSING、重复返回同一记录；通过既有测试注入风格配置延迟和成功/失败；成功取消并释放 SOLD 座位，失败保留权益；SYSTEM 与 buyerRefund 分离 |
| `frontend/src/components/BuyerRefundPanel.vue` | 服务端资格、原生确认对话框、提交禁用、三态权益文案、金额/本地退款 ID；截止时间采用一次性定时器及时禁用；卸载清理 |
| `frontend/src/pages/OrderPage.vue` | 提交互斥、结果不确定时 GET Order 恢复、409 中文提示与刷新、404 不可访问处理；统一串行订单读取入口；代次和页面销毁保护 |
| `frontend/src/views/OrderView.vue` | 退款插槽；POST 已返回成功而 Order 尚待同步时暂不展示有效票务摘要 |
| `frontend/src/utils/money.ts` | 保持原 formatCny，增加按 Refund.currency 的金额格式化 |

Mock 金融状态只保存在现有 Mock 模块内存中；应用层不把退款状态写入浏览器存储。
Mock 的完整页面重载仍会重置演示数据，真实 API 模式通过 GET Order 恢复服务端记录。
新页面实例分别恢复三态的组件测试和浏览器路由重新进入测试，独立验证恢复流程不依赖点击历史。

## 5. 异步与生命周期不变量

订单读取共用一个在途 Promise。当前代次请求合并，旧代次请求先结束再开始下一次 GET。
手动刷新、订单 ID 变化、提交结果同步和卸载使旧读取失效。所有异步结果写入前检查代次；
旧路由 POST 无论成功还是响应丢失，均不能触发对新路由的恢复查询或覆盖其文案。

仅 BUYER/PROCESSING 使用递归 setTimeout：前一整次读取完成后再等待 2000 ms，
不使用 setInterval。失焦或隐藏停止安排新请求；在途请求完成时再次检查前台状态。
恢复时立即同步，focus 与 visibilitychange 共用入口；即使首个 GET 在第二个事件前完成，
同一次激活仍只发一次同步。初始后台挂载也不启动轮询。

SUCCEEDED/FAILED 停止轮询；成功 POST 重新读取 Order，轮询识别成功时追加一次串行 Order
同步。单次读取错误保留原退款状态并继续按策略重试，不把网络失败当成退款 FAILED。
卸载清理退款定时器、截止定时器和 focus/blur/visibilitychange 监听，并使在途响应失效。

## 6. 自动化证据

| 测试文件 | 证明内容 |
| --- | --- |
| `src/api/refundApi.test.ts` | 实际 Axios transform 后 adapter 的 data 为 undefined；原 Cookie/CSRF/baseURL；200/202 与三个 disposition；GET 完整资源和统一错误 |
| `src/api/refundMock.test.ts` | 并发 POST 复用、确定性成功/失败、金额/字段形状、截止后复用、订单/座位权益、登出登入恢复、SYSTEM 不污染摘要 |
| `src/pages/OrderPage.refund.test.ts` | 资格与截止、取消确认、重复确认/事件互斥、响应三态、初始恢复、2000 ms 串行、不重叠、焦点/可见性两种事件顺序、后台挂载、终态停止、超时恢复、409/404、旧路由/旧 POST/旧轮询、卸载及在途请求清理 |
| `src/refundContract.test.ts` | 真实 DTO 类型形状与编译期可空性；四种通知都可渲染、标记已读并打开订单 |
| `src/utils/refundMoney.test.ts` | 保持 CNY 格式并按返回币种处理 USD/JPY/KWD |
| `e2e/refund.spec.ts` | 真实 Chromium 原生模态对话框、默认焦点、Escape 取消、双击确认、处理中、离开并重新进入订单、成功/失败权益和截图 |

已有支付、路由、选座、通知等回归测试全部保留；唯一旧文件修改为已批准的一处夹具补充。
测试不连接真实 Stripe；浏览器退款测试为 Mock 验证，不能替代真实渠道验收。

## 7. 验证结果

从仓库根目录执行：

| 命令 | 结果 |
| --- | --- |
| `npm --prefix frontend test` | 17 个文件，157 项通过，0 失败；原基线为 12 文件、95 项通过 |
| `npx --no-install vue-tsc -b`（frontend 目录） | 通过；最终 build 再次执行同一类型检查 |
| `npm --prefix frontend run build` | 通过；1940 modules transformed；JS 216.43 kB / gzip 77.04 kB，CSS 29.77 kB |
| `npm --prefix frontend run test:e2e` | 10 项通过，0 失败，含原有 8 项和新增 2 项退款浏览器测试 |
| `git diff --check` | 通过 |
| lint | 仓库没有 lint 脚本或 ESLint 配置，未编造 lint 通过结果；执行已有 vue-tsc 的 noUnusedLocals/noUnusedParameters/noFallthroughCasesInSwitch 静态检查及 diff 空白检查，不新增依赖 |

首次沙箱内运行基线 Vitest 时 Vite 子进程触发 spawn EPERM；改用获准的沙箱外执行后通过。
Playwright 仅输出原有 NO_COLOR/FORCE_COLOR 环境提示，不影响测试通过。
浏览器截图位于被忽略的 `frontend/test-results/refund-succeeded.png` 和 `refund-failed.png`，
已目视确认新增退款区域无溢出，成功与失败权益提示准确。生成目录不纳入提交。

## 8. 范围与剩余工作

`git diff --name-only -- backend` 无输出；没有修改 Backend、migration、Stripe Provider、Worker、
后端测试、依赖锁文件或无关页面。没有执行真实支付/退款、真实 Stripe Sandbox、部署、commit 或 push。
交付时 `git status --short` 仅包含上述前端修改、新测试和本实施记录。

Phase 12-2B 仍需完成真实 Stripe Sandbox、最终发布门禁和 README/正式产品技术文档同步。
本阶段测试证明的是前端行为与契约消费，不是生产发布或真实渠道资金验收。

待用户后续允许提交时，建议把前端实现、配套测试及这份记录作为一个可独立回滚的提交：
`feat(frontend): implement recoverable buyer full refunds`。当前不执行该提交。
