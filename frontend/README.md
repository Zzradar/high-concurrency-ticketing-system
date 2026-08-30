# 票迹前端 Demo

基于 Vue 3、Vite 和 TypeScript 的高并发票务预订系统前端演示。

## 本地运行

在 frontend 目录执行 npm install，然后执行 npm run dev。

默认使用内置 mock API，可完整演示活动、场次、选座、预订、支付、取消和超时流程。

## 接入 Drogon 后端

复制 .env.example 为 .env.local，并将 VITE_USE_MOCK_API 改为 false。

开发服务器会把 /api 请求代理到 http://localhost:8080，接口定义集中在 src/api/ticketApi.ts。

## 验证

执行 npm test 运行测试，执行 npm run build 完成类型检查和生产构建。
