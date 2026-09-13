# Phase18 当前交付

Layout ETag缺陷已修复，完整after-v2与本地门禁通过，等待独立复验。默认OFF。

- [最终报告](FINAL_REPORT.md)：完整收益、退化、SQL、浏览器、资源与限制。
- [当前交付Manifest](phase18-delivery.json)；[After状态](AFTER_STATUS.json)。
- [正式after-v2](after-v2/manifest.json)，SUT `6807a01516a75cf834ca1fac46fb1ac9abcdc53e`。
- [Stage0清单](manifest.json)与[baseline清单](baseline/manifest.json)均保持原字节，基线SUT `ed51447154418e05ed9e4c49728f3eb114713db9`。
- 旧after/与SUT `4dd48c1` 已失效，仅保留历史证据；[旧报告/交付清单原字节归档](history/fc9e41a/README.md)。
- [字段映射及数据库revision设计](../../../docs/phase18_layout_revision.md)、[最终回归](capabilities/layout-revision-final/manifest.json)。

旧checkpoint和失败诊断不是可部署版本。此单次共享主机结果不代表生产SLA；没有merge或创建PR。
