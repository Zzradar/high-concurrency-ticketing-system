# Phase19 简历证据边界

| 可直接使用（已实现事实） | 需带本地环境限定（实际测量） | 禁止宣称 |
|---|---|---|
| 实现通知、支付、退款、未知提交的串行轮询、可见性暂停、退避与旧身份响应隔离；328 项前端测试通过 | 固定 Edge、受控 HTTP、七场景 60/91/30 秒 A/B：治理 GET 267→56，减少 79.03%，隐藏期间零新读取 | 所有接口流量减少 79.03%；线上网络带宽降低同等比例 |
| 建立 Closed/Open 双模型、独立 cursor、真实状态传播计时和库存校验的冻结证据流程 | 本地 API 2 CPU/1 GiB、k6 2 CPU/4 GiB：2000 actual VUs 额外观察 10 分钟有效，Delta 72.23 req/s | 2000 req/s、2000 并发购买，或生产峰值容量 |
| 分离 HTTP 写入、业务流程和正式/临时状态变化计数 | 开放 L3 120 秒 Delta 500.05 req/s、HTTP write 42.85 req/s、零 dropped/interrupted，查询 p95 2.441ms | 50 笔订单/s、50 支付/s；把 HTTP 查询延迟当状态传播延迟 |
| 构建热点严格一胜者和 Outbox/SQL/Redis 收敛验证 | 5001 条累计旅程完成；1000 人单席争抢 1 winner/999 明确冲突、零超卖 | 5001 同时在线；将 999 冲突算成功业务吞吐 |
| 以 Fake Provider 验证过载下既有业务恢复、支付退款内部一致性 | 两轮独立 ENFORCED 新购票洪峰下 Checkout/Order/Payment/Refund 读取成功；最终金融/库存零违规 | Stripe 渠道容量、生产支付 SLA 或真实资金结算证明 |
| 用实测边际内存、OLS、30% 余量与 FD/宿主门禁评估扩展可行性 | 10000/20000/30000 VU 发生器保守估计 6.53/13.16/19.80 GiB，UNSAFE、未执行；3000 SUT 预热有 2 次 503 | 已支持数万 actual VUs，或以 online-equivalent 偷换实际用户数 |

所有数字追溯 [完整报告](FINAL_REPORT.md)、report-tables.json、逐点 result/identity/archive-manifest。传播每类仅 6 样本，约 2s/5s 包含客户端轮询等待；不得将尾分位表述为生产 SLA。等待独立复验，尚未 merge main。
