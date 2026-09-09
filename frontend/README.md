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
