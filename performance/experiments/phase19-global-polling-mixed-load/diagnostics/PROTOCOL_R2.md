# r2 协议修复与重新资格

r1 L2 首次运行无效：启动期 64 次 503（58 Snapshot、6 Delta），本地 Availability Bulkhead 上限仍为 16。原始未压缩 JSONL 在 Windows bind mount 写回积压，210 秒墙钟截止时缺失最终 summary；原始时间序列仅覆盖部分运行。原结果中的 summary 回退零值不代表没有请求，禁止作为吞吐统计。完整 r1 正式组已移动至 r1-formal-retired，relocation.json 逐文件验证原字节哈希；其内部 manifest 保留原路径，仅供诊断。

第一次启动修正只错开十条读取流，仍遇到 63 次启动 503。第二次尝试分段 ramping，错误消失，但实际启动 4249 与计划 4250 不守恒，继续判无效。第三次采用独立 per-VU bootstrap，在预热期间按 50/s 为全部 200 VU 各自建立 Snapshot，随后固定速率阶段使用自身保留的游标。短诊断 200 bootstrap + 3759 reads + 134 flows 全部完成，无 dropped/interrupted；没有降低正式到达率或修改业务 Bulkhead。

原始指标写回改为 k6 原生 gzip JSONL，同样用于 generator-only 资格，保留完整可解压点流。L2 完整诊断 31278 次、L3 62352 次迭代全部完成，零非预期错误、dropped、interrupted。传播采样和前后 verifier 通过。累计旅程实际 5001（计划 5000，固定速率边界多一次），100/500/1000 热点分别严格一个 winner，控制探针零失败。10000 席独立布局检查通过，库存零失配。这些都只是诊断，不能替代重新冻结后的正式基线。

r2-gzip-validated-source 保存上述完整负载诊断执行时的协议。最终 r2 又补充明确的三点内存增长停止规则（两次增量均达到容器配额 5%，且后一次不减速，启动期也适用）、万席检查身份/UTC/前后 verifier，以及被冻结的报表脚本。这些最终变更必须重新资格后才可开展正式测量。新 r2 协议未混入任何前端生产逻辑变更。

资格和正式主容量身份均为用户批准的 k6 2 CPU / 4 GiB，事件策略 OFF、本地 Bulkhead 保持默认。旧 2 GiB 和原 4 GiB 资格仅为历史记录。新协议须完整重跑资格和全部 baseline；after 必须使用同一冻结协议。

原生 gzip 方式见 [Grafana k6 JSON output](https://grafana.com/docs/k6/latest/results-output/real-time/json/)。

最终门禁的第一轮新资格：100/250/500 有效；1000 在 15 秒空闲结束后，cgroup 连续从 248.44→477.69→792.71 MiB 增长，触发门禁并停止，1000 次迭代未完成。检查发现资格未传递正式 Closed 已使用的 INIT_SPREAD_SECONDS=30，导致同时解析所有首次 Snapshot。修正资格启动为 15 秒空闲 + 与正式相同的 30 秒首读展开，之后仍完整观察 60 秒；没有放宽停止阈值、增加资源或减少 VU。全部资格从 100 重新开始，旧运行保存至 r2-initial-qualification。
