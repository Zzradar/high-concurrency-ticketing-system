本次定位以原始证据为准，未修改生产实现。已确认的直接原因是短时在途请求达到 Availability Bulkhead 的 16 个许可；导致约 40–45 ms 尾部停顿的更下游原因未被历史观测唯一定位，不能把某个相关现象当作已证明的根因。

旧 open-l3-r1 的 8 次拒绝全部为 GET Delta，场次为 phase19-session-001-002，接口为 /sessions/phase19-session-001-002/seat-availability。UTC 完成时间及 scenario：

| UTC，2026-09-14 | scenario |
|---|---|
| 02:38:07.622942077 | readers3 |
| 02:38:08.302544908 | readers3 |
| 02:38:08.304265768 | readers4 |
| 02:38:08.307014832 | readers5 |
| 02:38:08.308550306 | readers6 |
| 02:38:08.311293490 | readers7 |
| 02:38:08.313098828 | readers8 |
| 02:38:08.313973880 | readers9 |

这些是 k6 完成时间，不是服务端取得/拒绝许可的时间。原冻结 systemTags 不导出 URL、Zone、用户或 VU ID，scenario 不能确定具体 VU/Zone；保留容器在 02:38:06–10 的日志也为空。因此具体 Zone 无法事后恢复，明确记为 unknown，而不是猜测。精确原时间、邻近 HTTP 及耗时保存在 diagnostics/open-l3-503-timeline.json。

从完成时间减去 http_req_duration 重建客户端区间，8 个拒绝点各重叠着 16 个最终返回 200 的可用性请求，加上当次 503 共 17 个区间。这个间接观测与服务端后续新鲜指标中的峰值 16、累计拒绝 8 相符。旧点最后一条采样完成于 02:38:07.406543，早于首次拒绝，且 PromExporter 存在缓存；该采样峰值仍为 12、在途为 0。不能用它声称故障瞬间在途为 0。旧 r2 开始的在途为 0、峰值为 16、拒绝累计为 8，结束累计仍为 8。不存在持续占满 16 个许可的证据。

r1 成功 Delta 的 p50/p95/p99/max 为 1.589/2.571/5.624/45.321 ms；r2 为 1.454/2.293/5.215/24.409 ms。第二批拒绝同时段有数个 40–45 ms 的成功 Delta，写请求也有约 100 ms 的确认耗时。它们支持瞬时积压的判断，但 HTTP 区间包含客户端、网络和服务端全过程，不能单独归责 PostgreSQL 或 Redis。

计算池采样队列深度和活跃数均为 0 或 1，提交拒绝计数为 0；这是采样值，并非完整瞬时峰值。Bulkhead 先于 authorizeRead 和 SeatAvailabilityReadModel 执行，8 个请求在进入 SQL/Redis/计算池前被拒绝，因此它们属于 Delta 请求的过载拒绝，不能标记成实际执行了 Snapshot、缓存未命中或 PostgreSQL 降级。邻近成功请求的完整同步类型、延迟直方图及累计事件计数保存在 metric-timeline 和原 system-observations 中。

从源码检查，正常读链路为 sessionExists SQL → Redis 初始化资格检查 → 到期清理 → Snapshot/Delta Lua → 计算池序列化 → reply 释放许可。Permit 使用析构释放，wrap 的原子 complete 保证只完成一次，回复前 reset 许可；计算池统一成功/异常收尾。没有发现可复现的许可泄漏分支，本次未为推测原因修改代码。

两个旧点的初始化 winner/READY 均保持 5，generation 前后不变，没有重新集中初始化的证据。正常写入更新正式版本并追加变更流，不会仅因 revision 变化重建 generation。r1 的失败发生在观察窗中段，而非 200 个 VU 的预热 Snapshot 起发阶段。r2 确实复用了 r1 的数据库、Redis 和进程，不能作为独立资格；但 r1 开始前也已经有 5 个就绪模型，所以“r1 建缓存后 r2 才能通过”没有得到因果证明。当前三轮采用全新隔离状态重新验证这一点。

旧 r1/r2 PostgreSQL 没有死锁或回滚增量，采样未发现等待锁；r1 末段可见一次 WALSync 等待。配置使用 4 个 PostgreSQL 连接，Redis 每类客户端 2 个连接。pg_stat_statements 只有聚合耗时，pg_stat_activity 只有采样，没有保留故障瞬间的客户端连接池排队长度或逐请求 SQL 时延。Redis 未报告拒绝连接、逐出、失败命令或错误回复；INFO 的累计耗时不能代替具体请求时延。原资源采样显示后端 CPU 配额占用峰值约 23.0%、Redis 36.8%、PostgreSQL 20.3%，后端 FD 最高 686/4096、cgroup 内存约 80 MiB/1 GiB，无 OOM、重启或换出；这些低频采样不能排除毫秒级调度停顿或 CPU 配额节流。新三轮另按同样方式补采 cpu.stat 与过滤参数后的 Redis SLOWLOG，未改变任何冻结请求起发和速率。

收敛检查使用原 measure.py 的前后库存验证与新边界观测。原验证会等待 Outbox 排空并核对 SQL/Redis 显示库存，而非只等待 HTTP 完成。指标缓存及周期工作线程意味着不能宣称观测到了所有后台回调的瞬时状态。新边界原始值和每轮初始库存保存在 rounds/r*/boundaries；不额外延长 sleep、不调换测试顺序，也不清掉旧失败后重试同一环境。

历史 r1：观察窗 HTTP 43,765，503 为 8，错误率 0.018279%，原冻结门禁中止，28 个迭代 interrupted，不能称为达标的完整 L3。历史 r2：观察窗 HTTP 65,788，503 为 0，但与 r1 同环境，仍只保留为单次通过。旧失败、旧通过与旧 Manifest 均保持原样。三轮独立资格的最终结果以 qualification.json 和 round-summary.json 为准。