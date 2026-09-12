# Phase17 evidence

真实门禁执行于 2026-09-12，专用 Phase17 工作树与隔离容器。详见 [实施记录](../../../docs/phase17_admin_event_publishing_implementation.md)。

- phase17_*test.txt：升级/fresh、角色、Venue、发布真实门禁。
- phase11-stripe.txt / phase11-crash.txt / phase12-refund.txt：11+11+38 项。
- phase15-*、phase16-*：售票窗口、退出恢复、投影/缓存故障与不变量。
- ctest.txt / performance-unit.txt：34 / 233。
- playwright.json：5 项，包括 UI 创建发布、草稿隔离、购买支付退款取消与两种规模。
- scale.json：顺序创建/发布、HTTP 20 样本、PG 语句增量与 Redis SLOWLOG。
- browser-*.json：5 次 navigation 至两次 RAF、当前 Zone DOM 数。
- layout-comparison.json：同 5000 席旧夹具对照；基线为现存包含 Phase16 的 Phase15 镜像，非本轮重建的固定 SHA。
- phase14-g0/u1/u2：原 smoke-check、correctness、verdict。仅功能与正确性门禁通过，measurement_validity 不具正式容量资格；没有隐去诊断结果。
- verifier.json：Phase17 27 项检查及嵌套 Phase15/16/原 verifier 全部通过。

规模测试不代表生产 SLA/并发容量。原始 SQL 增量包含后台任务，不可直接合计为单请求 roundtrip。gzip 是本地压缩，不是服务器传输编码证明。Redis EVAL 是服务端命令耗时，浏览器样本含网络和框架更新。
