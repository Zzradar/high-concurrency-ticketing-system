# 票迹前端 Demo

基于 Vue 3、Vite 和 TypeScript 的高并发票务预订系统前端演示。

## 本地运行

在 frontend 目录执行 npm install，然后执行 npm run dev。

默认使用内置 mock API，可完整演示活动、场次、选座、预订、支付、取消、超时和买家全额退款流程。

## 接入 Drogon 后端

复制 .env.example 为 .env.local，并将 VITE_USE_MOCK_API 改为 false。

开发服务器会把 /api 请求代理到 http://localhost:8080，接口定义集中在 src/api/ticketApi.ts。

## 验证

执行 npm test 运行测试，执行 npm run build 完成类型检查和生产构建。

## Stripe 与买家退款

真实模式使用 `VITE_USE_MOCK_API=false`，通过 `VITE_API_PROXY_TARGET` 指向隔离后端，
并配置 `VITE_STRIPE_PUBLISHABLE_KEY` 的 test 前缀公钥。前端不得配置 Secret Key。
准备好人工输入后再点击“开始支付”，官方 Stripe Elements 负责卡信息。

已支付订单在开场前提供“申请全额退款”。确认框不可编辑金额；取消确认不会提交，
确认后无 body POST 并禁用提交。处理中权益仍有效，成功后订单取消、座位释放。
刷新或重新登录由后端恢复退款事实。订单权威终态会清除旧支付组件、Attempt 与提示。

`npm run test:e2e` 是 Mock 浏览器门禁；真实 Stripe 的资金与页面证据独立记录于
[Phase12-2B 验收记录](../docs/phase12_2b_sandbox_validation.md)。退款调度专项可运行
`npm test -- src/pages/OrderPage.refund.test.ts`。
真实渠道处理中与前端可见状态已经验收；隐藏/失焦的精确请求调度由确定性自动化测试覆盖，
未把未观察到的真实浏览器时间线伪称为已观察。详见
[前端技术设计](../docs/frontend_technical_design.md)。

当前不支持部分退款、退款失败后自动第二次退款、项目外 Dashboard 退款自动认领，
以及 succeeded → failed 后续冲正。Stripe Sandbox 不是生产资金或真实银行结算证明。

## Phase17 管理端真实演示

使用真实后端，按 [Demo Seed](../backend/db/seeds/001_demo_seed.sql) 的本地 ADMIN 登录配置进入账户菜单“管理后台”。流程：场馆区域/连续行 → 活动草稿 → 场次与区价 → Preview → 发布；CUSTOMER 无需重启即可购票。Demo 身份只用于本地演示。

Admin 请求复用原 Cookie/CSRF/401/错误处理，没有完整 Mock Admin 数据库。所有时间输入按北京时间解释；场馆 frozen、价格重置和结构化发布问题直接展示。既有消费者页面仍只渲染当前 Zone。

独立浏览器门禁在本目录执行 `npx playwright test -c playwright.phase17.config.ts`；先运行 `python performance/scripts/phase17_scale.py`（仓库根目录）准备规模夹具，再执行完整 5 项。它连接 18117 的专用真实后端，Vite 使用 5177。完整结果见 [Phase17 实施记录](../docs/phase17_admin_event_publishing_implementation.md)。
