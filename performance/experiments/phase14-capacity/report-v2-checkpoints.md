# Phase14 本地预演与交付报告（v2）

**U2 调度边界修复、完整缩小矩阵、观测复验和浏览器请求链校准已完成。正式测量未达资格：本地特征不构成万人正式容量证明。**

功能通过不代表性能门槛全部通过：L1/L2 背景余票相对延迟未通过，smoke 时长不足以满足正式恢复窗口，持久采样的首次 4 秒对照未通过。所有结果保留原判定。

## 基线与范围

起始干净 main：`a45cab7e4e33c7153d8a98114ebef45be9beef3a`。本轮修复提交 `9b1d086`，持久只读采样及浏览器校准提交 `e321f0e`。最终文档提交见 Git 日志。未 push；未改 frontend、业务状态机、迁移、连接池、线程池、队列或回收批量。模拟支付沿用现有提供者。

本批 25 条矩阵记录：4 条已通过的 v1 G0/U1/U2 前序记录，经业务参数完全相同核验后只读复用；新增 21 条 v2 运行。另有单/双分片交付探针各一次，以及两条 H3 持久采样复验。每个新运行完整恢复快照、清空 Redis，使用新 Run ID、幂等命名空间和证据目录。

## 非业务保护尾段

配置升为 version 2，仅新增 `generator.scheduler_delivery_guard_seconds=1`；其他业务字段逐项相同。旧哈希 `669c9d44809dcfdf939f561e4b0fcf60cf7582497324414bbc7e8c4c29a98749`；新哈希 `917a03daa02168de6a430b1cf45e13b1510d9f7eca3fd6c32558e42835d95674`。旧失败目录 101 个文件哈希无变化。

共享生成器为 constant/ramping arrival 增加执行器尾段，原阶段速率、timeUnit、startTime、时长、计划数、身份映射保持不变。H3 的 per-vu-iterations 没有同类积分终点取消问题，不改其发车模型。逻辑上界检查先于身份访问和 HTTP；额外 tick 只计固定 phase14_scheduler_boundary，业务 started/completed 不增加。

真实单分片/双分片探针分别产生 30/29 个边界 tick；两轮均只有 30 个 HTTP、30 个业务完成，包含常速 20/20/20 与升压 10/10/10，dropped=0。回归证明尾段不能豁免 dropped、中断、系统错误或正式模式交付守恒。

业务吞吐使用 businessWindows.seconds，不使用扩展执行器窗口。例如 U2 refresh_0 按原 2 秒计算 10/2=5 次/秒，refresh_1 按原 4 秒计算 40/4=10 次/秒。执行器保护时间单列在 spec.deliverySchedule。

## 逐轮矩阵

以下计数只取主负载（U2 含所有进入/刷新阶段，L 含登录与背景），排除 control/payment 探针。闭合模型没有有限 planned，以 — 表示。E1 是 20 组订单夹具，不是 k6 迭代。全部功能检查、数据库对账通过；完整分步骤成功/冲突/拒绝/错误、分位数及资源峰值见 JSON。

| 场景/参数 | Run ID | 配置 | planned / started / completed | dropped | 测量 / 容量 / 过载保护 |
|---|---|---:|---|---:|---|
| G0 {} | phase14-smoke-g0-20260910T014114Z-a26cab | 1 | 20 / 20 / 20 | 0 | fail / not_applicable / not_applicable |
| U1 {"round":0} | phase14-smoke-u1-20260910T014150Z-ea4415 | 1 | — / 59 / 59 | 0 | fail / not_applicable / not_applicable |
| U1 {"round":1} | phase14-smoke-u1-20260910T014235Z-cc30e7 | 1 | — / 58 / 58 | 0 | fail / not_applicable / not_applicable |
| U2 {"round":0} | phase14-smoke-u2-20260910T014323Z-c168c4 | 1 | 70 / 70 / 70 | 0 | fail / not_applicable / not_applicable |
| U2 {"round":1} | phase14-smoke-u2-20260910T030307Z-2c6690 | 2 | 70 / 70 / 70 | 0 | fail / not_applicable / not_applicable |
| J1 {"window":0} | phase14-smoke-j1-20260910T030354Z-bb82d0 | 2 | 20 / 20 / 20 | 0 | fail / not_applicable / not_applicable |
| J1 {"window":1} | phase14-smoke-j1-20260910T030442Z-8a13e9 | 2 | 20 / 20 / 20 | 0 | fail / not_applicable / not_applicable |
| J1 {"window":2} | phase14-smoke-j1-20260910T030525Z-72afc7 | 2 | 20 / 20 / 20 | 0 | fail / not_applicable / not_applicable |
| O1 {"window":0} | phase14-smoke-o1-20260910T030608Z-146265 | 2 | 20 / 20 / 20 | 0 | fail / not_applicable / not_applicable |
| O1 {"window":1} | phase14-smoke-o1-20260910T030655Z-59b1b1 | 2 | 20 / 20 / 20 | 0 | fail / not_applicable / not_applicable |
| O1 {"window":2} | phase14-smoke-o1-20260910T030741Z-e86cba | 2 | 20 / 20 / 20 | 0 | fail / not_applicable / not_applicable |
| E1 {} | phase14-smoke-e1-20260910T030824Z-93e06e | 2 | 20 组 / 20 组到期 | 不适用 | fail / not_applicable / not_applicable |
| H1 {"path":"temporary"} | phase14-smoke-h1-20260910T030852Z-800fd2 | 2 | 20 / 20 / 20 | 0 | fail / not_applicable / fail |
| H1 {"path":"temporary"} | phase14-smoke-h1-20260910T030936Z-57cc88 | 2 | 20 / 20 / 20 | 0 | fail / not_applicable / fail |
| H1 {"path":"formal"} | phase14-smoke-h1-20260910T031017Z-c1e6f2 | 2 | 20 / 20 / 20 | 0 | fail / not_applicable / fail |
| H1 {"path":"formal"} | phase14-smoke-h1-20260910T031101Z-196a13 | 2 | 20 / 20 / 20 | 0 | fail / not_applicable / fail |
| H2 {"session_count":10} | phase14-smoke-h2-20260910T031147Z-b66698 | 2 | 20 / 20 / 20 | 0 | fail / not_applicable / fail |
| H2 {"session_count":20} | phase14-smoke-h2-20260910T031233Z-c7ccd0 | 2 | 20 / 20 / 20 | 0 | fail / not_applicable / fail |
| H3 {"path":"temporary"} | phase14-smoke-h3-20260910T031315Z-cf421f | 2 | 20 / 20 / 20 | 0 | fail / not_applicable / fail |
| H3 {"path":"formal"} | phase14-smoke-h3-20260910T031358Z-4789f7 | 2 | 20 / 20 / 20 | 0 | fail / not_applicable / fail |
| L1 {"control_only":true} | phase14-smoke-l1-20260910T031445Z-f56c8a | 2 | 224 / 224 / 224 | 0 | fail / not_applicable / fail |
| L1 {"control_only":false} | phase14-smoke-l1-20260910T031543Z-2cc58c | 2 | 244 / 244 / 244 | 0 | fail / not_applicable / fail |
| L2 {"control_only":true} | phase14-smoke-l2-20260910T031641Z-99eb15 | 2 | 168 / 168 / 168 | 0 | fail / not_applicable / fail |
| L2 {"control_only":false} | phase14-smoke-l2-20260910T031737Z-8e30f8 | 2 | 188 / 188 / 188 | 0 | fail / not_applicable / fail |
| S1 {} | phase14-smoke-s1-20260910T031833Z-b7490f | 2 | — / 131 / 131 | 0 | fail / not_applicable / not_applicable |

H1 的 formal 指正式预订路径，所有上表运行仍是 smoke，不能误读为正式容量运行。H1/H2 每轮 2 个赢家、18 个冲突；H3 每轮 1 个赢家、19 个冲突。H2 数据库所有者座位集合额外与预定映射逐项核对一致。

## 未通过项及观测边界

- 历史 U2 换入停止和后续 10 计划/9 启动失败仍为失败；新 U2 `phase14-smoke-u2-20260910T030307Z-2c6690` 的升压段达到 10/10/10。没有改成 planned=9，没有容忍少 1 或运行结束后补发。
- H1 重复轮的孤立换入保留 host_swap_activity，测量仍 fail、capacity 仍 not_applicable，但未阻断 smoke 功能矩阵。换出和其他安全停止规则保留。
- L1/L2 均完成 20 次登录和 20 次身份核对。背景余票请求数量与对照相同，但 p95 分别为 3→5ms、3→6ms，超过 1.5 倍线；背景占座/下单比较通过。L2 是已授权缩小功能矩阵的一部分，其执行不能表示正式 L1 升档门禁通过。
- 所有正式恢复窗口继续按原 30/60/300 秒等标准评估，短 smoke 的 recovery 保持失败，未放宽为通过；不声称完成正式过载恢复验收。
- E1 20 组合法订单约 6.365 秒排空，remaining=0，状态/库存/通知对账一致；不外推万人回收时间。

最初 H3 轻量采样逐次启动 Docker CLI，实际最大间隔约 590ms。原记录不改。改为一个只读监测连接后，两条新 H3 运行保持 20/20/20、单赢家与零 dropped：
- `phase14-smoke-h3-20260910T032511Z-f16aa8`：99 点，名义间隔 200ms，平均 200.05ms，最大 219.34ms；发车集中度通过，连接关闭。
- `phase14-smoke-h3-20260910T032750Z-aed9b9`：113 点，名义间隔 200ms，平均 199.91ms，最大 218.68ms；发车集中度通过，连接关闭。

## 采样开销对照

每腿固定 20 个 no-op 请求/秒，顺序 off/on/on/off。两腿分位数的中位数仅用于对照，不用于拼接分片全局百分位。k6 场景汇总仍从所有分片原始点重算。

| 采样实现 / 时长 | 每腿请求 | p95 增幅 | p99 增幅 | 5% 比较 |
|---|---:|---:|---:|---|
| 逐次CLI / 4s | 80 | -0.75% | -7.15% | True |
| 持久只读 / 4s | 80 | 5.60% | 39.06% | False |
| 持久只读 / 60s | 1200 | -4.20% | 1.02% | True |

三组错误/dropped 均为 0。持久采样首次 4 秒对照失败保留；随后预先指定采用已有正式空闲基线的 60 秒时长补做一次，原速率不变。新对照通过不覆盖旧失败；没有反复运行同配置挑最好值。当前同宿主、低输入对照仍不能建立正式采样开销上界。

## 浏览器请求链校准

证据：`performance/results/phase14-browser-v2-20260910T033309Z/browser.json`。读取当前 frontend 源码，独立 15174 端口，API 指向 Phase14 18414；不加载 .env，阻止外部网络，未访问 Stripe。缓存写入独立证据目录，前端树 `3cee03224b2955157f8b13cd935b703f6d7a478d` 前后不变。

匿名和已登录选座核心链均只读一次 session、event、layout、availability；实测布局与余票请求时间区间重叠。首次选座创建一次 checkout 并刷新余票，第二次只 PUT 同一 checkout 并再刷新余票。两次写入均携带会话 Cookie 和 CSRF 头，证据仅保存是否携带的布尔值，不保存秘密值。

**模型范围差异**：当前冷启动已登录页面还读取两次 auth/me、两次 notifications、checkout 列表及订单列表。固定 k6 模型覆盖冻结的核心 API 旅程，并不是当前整个浏览器页面总流量的完整复刻；这些附加调用已记录，未在同一批次擅自加入冻结输入。正式测量前若要覆盖整页总流量，需要另行定义模型版本。

## 工程检查与文件

- Python performance（含最终报告回归）：157/157，1.352 秒，`performance/results/phase14-engineering/v2-final-tests.log`。
- 既有后端集成：57/57；真实 metrics 触发夹具另 5/5；exporter 故障检查 6/6。明细与耗时沿用 [已完成回归汇总](smoke-policy-followup.json)。
- backend 本轮没有新生产改动；沿用标准 Dockerfile 构建及 CTest 30/30、源码契约 4/4、Phase14 契约 3/3 的真实通过记录。本轮未重复构建，未跑前端测试套件。浏览器仅校准协议，不作为前端新功能验收。
- 数据生成仍是 1m 注册/100k 会话；真实生成耗时、文件哈希、约 24.2MiB OS 峰值及 1000 冷/热身份核对见 [早期证据](evidence-summary.json)。这是数据规模，不是并发人数。v2 smoke 使用独立 smoke-v2 数据及快照，旧数据保留。
- 只读复核 89 个非 Phase14 容器状态与原批准停止后完全相同；三个旧项目卷仍存在。未执行 down/rm/prune/-v，未停止宿主 Stripe CLI、原 Vite 或其他非本会话进程。
- 新增/修改：共享调度生成、v2 配置、单/双分片 no-op 夹具、持久 PG 监测、浏览器校准、测试及本报告；主要路径见 [实施记录](../../../docs/phase14_implementation.md)。

## 结论边界与证据索引

本地工程预演已执行完整，冻结 API 模型的调度、分类、身份、数据对账和报告链得到验证。不能说全部性能门槛通过，不能说系统支持万人在线。正式环境仍缺压力机与被测系统的核/资源隔离；正式 G0、万人 U1/U2 及长期 S1 未运行。登录相对保护失败及当前浏览器附加请求也须在正式测量设计中明确处理。

目前没有证据确认后端容量瓶颈。已证实并修复的是生成器边界交付和采样器启动开销问题，不能据此推断数据库或 Redis 的万人容量。Phase14 不包含真实 Stripe 万级支付、电子票、验票。

- [v2 逐轮原始汇总](v2-evidence-summary.json)
- [保留的 v1 阶段报告](report-v1-checkpoints.md)
- [保留的旧停止证据](approved-project-stop-evidence.json)
- [保留的 smoke 语义续验](smoke-policy-followup.json)
