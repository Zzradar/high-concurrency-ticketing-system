# Phase19：全局轮询治理与混合读写验证

实现和正式测量完成，最终状态以 [交付 Manifest](manifest.json) 与 Git 交付回执为准。等待独立复验，尚未 merge main。

- 七场景冻结浏览器 A/B：治理 GET 267 → 56，减少 79.03%；after hidden 新请求为零，单在途/恢复合并/退出/终态门禁通过。Availability 在 seat/submitting 的请求数维持 9/10；不将其描述为被削减。
- 最高有效 2000 actual VUs，额外 10 分钟观察 Delta 72.23 req/s；3000 预热 2 次 Snapshot 503，为首次观测不稳定点。
- 开放混合 L3：120 秒实测 Delta 500.05 req/s、HTTP write 42.85 req/s；计数守恒、dropped/interrupted=0。真实传播延迟另表统计，不用 HTTP 延迟替代。
- 名义 5000、实际 5001 cumulative journeys；单席 1000 contenders 为 1 winner / 999 明确 409；10000 席布局校验通过。
- 数万 actual VU 估算 10000/20000/30000 加 30% 后发生器需 6.53/13.16/19.80 GiB，全部 UNSAFE、未执行。
- 实际保护条件：**事件策略 OFF、本地 Bulkhead 默认启用**。独立 ENFORCED 能力验证单列，不与吞吐相加；无 Stripe 渠道容量或生产 SLA 声明。

## 审查入口

[完整报告](FINAL_REPORT.md)、[轮询设计](POLLING_DESIGN.md)、[初始清单](POLLING_INVENTORY.md)、[简历证据](RESUME_EVIDENCE.md)。

`protocol/` 与 `protocol-sha256.json` 为冻结 r2；`capacity-thousands/baseline/manifest.json` 封存前端修改前完整基线；`polling-baseline/manifest.json` 与 `polling-after/manifest.json` 绑定各自源树与构建字节。`report-tables.json` 来自冻结统计器，`capacity-details.json` 为原始摘要与起发时间范围的报告提取。

[最终回归](final-regressions/manifest.json) 记录实际测试数量、日志和源文件 SHA。`overload-separated/` 是独立本地 Fake 保护/金融能力；`scale-estimate/` 保留估算公式和资格输入。每点 archive-manifest 记录大原始 gzip JSONL 的私有占位路径、哈希与大小，未提交认证凭据。

## 保留的失败与历史边界

r1 因 L2 启动 503 和未压缩 JSONL 写回阻塞整组退役，原字节保留 `diagnostics/r1-formal-retired/`。r2 重新资格、重新冻结、从 baseline 完整重跑，未拼接 r1 A/B。资格发展、提案测试与最终指标缓存断言失败均保留，详见完整报告。

`stage0/manifest.json` 是当时的历史快照；其中旧资格、待确认事项和未执行描述不代表当前交付状态。当前只使用 r2 4 GiB 完整资格与正式点作为容量证据。旧 Phase16/17/18 证据与 migration 不修改。

## 只读复核

```text
python performance/scripts/phase19_report_tables.py
python performance/scripts/phase19_delivery_audit.py
```

统计器会重新渲染派生报告；审计器本身只读。正式复跑必须使用新的独立环境和私有目录，命令参数见 protocol/PROTOCOL.md；不得复用实施容器冒充独立复验。
