# 高并发订票系统

基于 Drogon/C++20、PostgreSQL、Redis 与 Vue 3 的票务系统，覆盖占座、确认、支付、退款、后台恢复、座位增量同步和准入保护。

运行方式见 [后端](backend/README.md)、[前端](frontend/README.md) 和 [性能验证](performance/README.md)。

## 已取得的 Phase19 本地证据

在固定本地 Docker 配额、5000 用户夹具与 5000 席场次下，2000 actual VUs 闭合模型额外观察 10 分钟有效，Delta 实测 72.23 req/s；开放混合 L3 的 120 秒窗口实测 Delta 500.05 req/s、HTTP 写入 42.85 req/s，dropped/interrupted 为零。
累计旅程实际完成 5001 条；单席 1000 人热点为 1 个成功者和 999 个明确冲突，最终库存与读模型校验零违规。

前端轮询治理覆盖通知、支付、退款、未知提交和旧身份响应隔离；完整前端测试 328 项通过。详细浏览器 A/B、生产身份、传播延迟、失败记录及回归门禁见 [Phase19 完整报告](performance/experiments/phase19-global-polling-mixed-load/FINAL_REPORT.md)。

这些数字只代表记录的本机配额、短窗口和固定数据集；3000 actual VU 已出现预热 503，数万 VU 因内存/FD/宿主余量不足未运行。它们不是生产 SLA、理论最大容量或 Stripe 渠道容量。
