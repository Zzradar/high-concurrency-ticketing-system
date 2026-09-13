# Phase18 当前交付

migration016 search_path 遮蔽修复、完整回归及全新 after-v3 已通过，等待独立复验。默认 OFF。

- [最终报告](FINAL_REPORT.md)：根因、全部收益/退化、SQL、Registry、真实浏览器时间线、资源和限制。
- [交付 Manifest](phase18-delivery.json)、[独立哈希清单](DELIVERY_HASHES.json)、[After 状态](AFTER_STATUS.json)。
- [正式 after-v3](after-v3/manifest.json)，SUT `3a9e0c1311add748c7faec956bb6c9266ed7d5ba`。
- [Stage0](manifest.json) 与 [baseline](baseline/manifest.json) 原字节不变；baseline SUT `ed51447154418e05ed9e4c49728f3eb114713db9`。
- after/ 因 ETag v1 缺陷失效；after-v2/ 因 search_path 遮蔽缺陷失效；全部原始字节保留，[上一交付归档](history/8a62d57/phase18-delivery.json)。
- [函数审计](../../../docs/phase18_layout_resolution.md)、[新回归证据](capabilities/layout-resolution/manifest.json)、[91秒隐藏门禁](capabilities/final-hidden-v3/manifest.json)。

原反例已确认关闭；失败诊断保留并在报告说明，旧 checkpoint 和失效 After 不可部署。本轮共享主机结果不代表生产 SLA。未合并或创建 PR。
