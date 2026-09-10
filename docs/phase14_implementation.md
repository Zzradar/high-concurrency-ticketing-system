# Phase14 实施记录（v3）

冷启动模型与新 smoke 判定已收尾，详见 [v3 实施说明](phase14_v3_closeout.md) 和 [当前交付报告](../performance/experiments/phase14-capacity/report.md)。下方保留 v1/v2 实施历史；旧失败与旧判定不修改。正式万人容量尚未验证，当前没有证据证明或否定万人容量。

## 基线和授权边界

- 起点为干净 `main`，HEAD 与 fetch 后 origin/main 均为 `a45cab7e4e33c7153d8a98114ebef45be9beef3a`，左右差异 0/0。
- 用户确认：同一 Run ID 内身份切片不重叠；不同运行完整恢复数据库快照并清空 Redis 后可复用切片。每轮 Run ID、幂等命名空间和证据目录独立。
- 已提交 `6139baa`（冻结目标与流式数据）、`6e840ce`（后端观测）及 `4bccde2`（受保护的负载与证据框架）。报告提交见 Git 记录。未 push。
- 未修改 frontend、业务迁移、库存/认证/订单/支付/退款状态机，未修改原连接池、线程池、队列和回收参数。模拟支付仅使用既有 SimulationPaymentProvider，只成功配置保留原延迟。

## 现状、复用与新增

| 部分 | 现状与复用 | Phase14 新增 |
|---|---|---|
| 数据 | 原 generate_dataset 与 profile、COPY 模板 | 百万注册/十万会话流式导出、真实认证间隔打散、磁盘估算、源文件哈希 |
| 请求 | k6 config/data/http 公共库，现有页面接口 | 固定 60/25/15 分组、一次购买、U2 开放输入、无冲突及热点映射、独立探针 |
| 运行 | 原 k6 镜像、verify.sql、证据解析 | Phase14 Compose、双重清理保护、分片原始记录、SQLite 全局分位数、停止与恢复判定 |
| 观测 | 原 PerformanceMetrics、Prometheus、exporter | 固定 flow 在途、高水位、全部 12 个事务连接获取调用点、Redis 复合时延、主事件循环、expiry 批次 |
| 校验 | 现有全库不变量 | Run 范围订单/登录/支付对账，合法 E1 夹具，热点 owner/TTL 核对 |

## 文件与运行方式

- 唯一目标源：`performance/baseline/phase14-targets.json`；`phase14_model.py` 读取原始 SHA256 并应用明确的 smoke 覆盖。正式数字不因预演结果调整。
- 数据：`performance/data/profiles/phase14-1m-users-100k-auth.json`、原 `generate_dataset.py` 增量实现。输出位于被忽略的 `performance/generated/phase14/`。
- 负载：`performance/k6/lib/phase14-model.js`、`phase14-flow.js` 及四个 `workloads/phase14-*.js`。
- 调度/汇总/采样：`performance/scripts/run_phase14.py`、`phase14_evidence.py`、`phase14_sampling.py`。
- 业务核对：`performance/verification/phase14_verify.py`；始终复用原 `verify.sql`，未复制或放宽原不变量。
- Compose/exporter/no-op：`performance/docker-compose.phase14.yml`、`performance/phase14/`。专属端口 18414/19414，不共享旧项目的数据卷。

```powershell
# 默认只读计划，不启动容器或删除数据
python -X utf8 performance/scripts/run_phase14.py plan

# 以下是已实现入口；当前环境交换问题未解决前，不继续压力批次
python -X utf8 performance/scripts/run_phase14.py prepare --smoke --yes
python -X utf8 performance/scripts/run_phase14.py campaign --smoke --shards 2 --yes

# 百万数据、1000 冷/热抽样与按节奏预热
python -X utf8 performance/scripts/run_phase14.py prepare --yes
python -X utf8 performance/scripts/run_phase14.py calibrate --yes
```

`--yes` 仅允许已验证的 Phase14 专属项目/卷操作。运行器拒绝其他项目、外部卷/网络、未知 bind mount、错误目标配置与损坏快照。每轮在保留卷的前提下恢复完整快照、清空专属 Redis 并检查 DBSIZE=0；不是仅清业务行。正式 campaign 在当前没有隔离证据的实现中拒绝运行，不能通过改报告字段放行。

## 关键语义与观测边界

U1 的主负载和探针在独立 k6 进程运行，避免探针 VU 编号占用主身份。每个主 VU 的固定身份/分组只执行一次购买分支。U2 的进入与刷新分别计划，积分来自冻结人数与时长，不依赖完成速度。J/O 模糊确认只读取原 checkout，不创建第二个逻辑购买。

开放执行器保留有界的额外 VU 供窗口边界 tick 使用；超出逻辑计划的 tick 不发 HTTP，单列 `phase14_scheduler_boundary`。实际 dropped 仍判失败，未通过忽略 dropped 掩盖压力计划缺失。

所有分片原始 JSON 压缩后校验 SHA256，使用 SQLite 外部排序重新计算全局 p50/p95/p99；不平均分片 p95。固定结果为成功、业务冲突、容量拒绝、系统错误、非预期契约五类；成功延迟与快速拒绝分开。Run ID、用户/订单/座位/幂等键不进入指标标签。RFC3339Nano 时间戳接受 1–9 位小数；读取原始日志使用增量偏移，避免每秒重扫全部历史。

HTTP 在路由匹配后进入固定组、发送前或对象销毁完成；排除 health/metrics。事务指标只覆盖 `newTransactionAsync` 到回调收到事务的等待，不代表普通 SQL 连接池等待。Redis 指标为应用调用到回调入口的复合时延，包含客户端排队、网络和 Redis 执行；下游解析或业务冲突不会泄漏在途计数，但不把回调后的解析耗时记作 Redis 服务端执行。事件循环指标仅代表主循环。观察对象 exact-once，监控 sink 异常不改变业务异常传播。

PostgreSQL 活动等待过滤目标库、应用名、client backend 和 active 状态；空闲 ClientRead 不混入等待。原 exporter 公共文件只新增无需业务 SELECT 授权的查询；expiry 聚合位于专属 `phase14/queries.yml`，其只读角色授权也只在 Phase14 初始化。保存数据库/语句/I/O/WAL 增量及重启/reset/淘汰信息，异常时不得解释为有效增量。

宿主采样来自 Docker Desktop Linux VM。`pswpin` 增量是全宿主事实，不能仅凭它归因某个容器。CPU 配额不等于核隔离，当前 cpuset 为空、网络物理容量未建立，因此正式测量始终无效。

## 测试与兼容调整

138 项 performance Python 测试通过，包括 Node 执行真实 Phase14 JS 模块的 HTTP/时间模拟测试，覆盖分组、一次分支、同 checkout 恢复、登录 Cookie jar、支付 deadline、分类守恒和标签。C++ 观察对象覆盖重复/并发完成、空/错/超时、销毁与异常路径；标准 Dockerfile 构建及 CTest 30/30 通过。

对旧测试仅作一处兼容更新：`performance/tests/test_k6_framework.py` 的 sleep 允许列表增加 `phase14-flow.js`。原 Phase10 开放单接口负载的无 sleep 断言全部保留；Phase14 的闭合思考、刷新和支付轮询另有行为测试。

当前缺口包括：全部受影响后端集成回归、全缩小矩阵、正式 G0 与采样开销对照、H3 200ms 轻量采样、当前浏览器请求图校准和最终真实指标/数据库故障夹具。具体已运行/未运行项目见阶段报告。不能以离线测试通过替代这些门禁。

## 官方资料与采用范围

- [k6 开放与闭合模型](https://grafana.com/docs/k6/latest/using-k6/scenarios/concepts/open-vs-closed/) 与 [dropped iterations](https://grafana.com/docs/k6/latest/using-k6/scenarios/concepts/dropped-iterations/)：固定输入和交付守恒。
- [k6 分布式执行](https://grafana.com/docs/k6/latest/testing-guides/running-distributed-tests/) 与 [JSON 原始输出](https://grafana.com/docs/k6/latest/results-output/real-time/json/)：分片与原始合并。
- [PostgreSQL 16 统计](https://www.postgresql.org/docs/16/monitoring-stats.html) 与 [锁视图](https://www.postgresql.org/docs/16/view-pg-locks.html)：活动等待和统计增量。
- [Drogon 事务](https://github.com/drogonframework/drogon/wiki/ENG-08-2-Database-Transaction)：事务获取观测范围。
- [Google SRE 监控](https://sre.google/sre-book/monitoring-distributed-systems/)：延迟、流量、错误和饱和度联合解释。
- [Hi.Events k6](https://github.com/HiEventsDev/Hi.Events/blob/develop/misc/k6/README.md)、[pretix scaling](https://docs.pretix.eu/self-hosting/scaling/) 与 [Online Boutique](https://github.com/GoogleCloudPlatform/microservices-demo/blob/main/src/loadgenerator/locustfile.py)：参考旅程/带权行为，不借用其吞吐数字。
- [Stripe rate limits](https://docs.stripe.com/rate-limits)：本轮不向真实 Stripe 施压。模拟支付与真实渠道容量不能互相替代。

## 2026-09-10 获准停止旧项目后的更新

三个项目的 12 个容器经精确标签再次核验后仅用 docker stop 停止；3 个卷保留、其他容器内容和状态不变。宿主空闲后的两个新 60 秒窗口无换页增长，随后资源预检、G0、两轮 U1 和首轮 U2 功能预演通过。第二轮 U2 释放前再次出现 pswpin +12，按停止规则中止，没有继续压力运行。详见阶段报告及停止审计。

新增 `phase14_stop_approved_projects.py` 及测试，提供精确项目停止、原始/归一化状态核验、空闲与两窗口观察。Phase14 reset 保留容器和卷，源码挂载使用 Compose 合并文件；不执行 down/rm/prune/-v。H2 smoke 跨活动映射、资源预检和独立轻量 PG 采样已有离线测试；剩余端到端验证与采样开销仍未完成。

## 2026-09-10 smoke 停止语义续验

模式差异已提交；新 U2 因计划 10 次、实际 9 次而停止，尚未完成完整矩阵。57 项独立集成回归、真实指标及 exporter 夹具已通过，no-op 采样对照已完成。历史失败保留不变，详见 [续验记录](phase14_smoke_policy_followup.md)。

## v2 最终接线与运行方式

`phase14-targets.json` version 2 只增加非业务 `generator.scheduler_delivery_guard_seconds=1`。共享 `guard_delivery` 覆盖所有 constant/ramping arrival 场景；原业务曲线保存在 spec.deliverySchedule，吞吐分母来自 businessWindows。H3 per-vu 波次不作同类改动。新数据目录为 `performance/generated/phase14/smoke-v2`，不会覆盖 v1 数据或旧 Run ID。

`phase14_pg_stream.py` 在专用库中维持一个 read-only 监测连接，5 秒 statement timeout，正常关闭 psql；异常清理仅针对本连接 PID、backend_start 和 application_name。`LightPostgresSampler` 将连接从业务等待统计中排除，实际 H3 最大间隔约 219ms。历史已退出故障容器只保留为证据，不参与当前健康判断；意外运行的额外服务仍拒绝，已见本轮压力容器的退出/OOM 仍跟踪。

```powershell
python -X utf8 performance/scripts/run_phase14.py plan --smoke
python -X utf8 performance/scripts/run_phase14.py prepare --smoke --yes
python -X utf8 performance/scripts/phase14_delivery_probe.py
python -X utf8 performance/scripts/run_phase14.py campaign --smoke --yes --shards 2
python -X utf8 performance/scripts/phase14_sampling_overhead.py --formal-baseline-duration
```

开销命令仅把 no-op 对照腿时长设为配置已有的 60 秒空闲基线；输入仍为 smoke 的固定 20 请求/秒，不能称正式压测。浏览器校准先在没有其他 Phase14 压力运行时使用 `calibrate --smoke --yes` 恢复快照，再运行 `node performance/scripts/record_phase14_page_flow.mjs`。脚本使用独立 15174 端口，不加载环境凭据，缓存位于结果目录；记录请求时序及身份/CSRF 是否携带，不保存秘密值。

本地矩阵 25 条累计记录全部完成功能与数据库门禁，其中本轮新运行 21 条；另有单/双分片交付探针和 2 条 H3 采样复验。Python 框架 156 项通过，既有后端集成 57 项、真实 metrics 触发 5 项、exporter 故障检查 6 项通过。最终文档测试数见最终日志。没有重复前端门禁，前端树保持不变。

正式运行仍受隔离条件约束；当前 `campaign` 不会将共享主机运行提升为正式容量结果。已校准浏览器入口还包含固定核心 API 旅程以外的认证/通知/列表请求，若要测整页总流量，应在正式测量前明确新的模型版本，不能静默修改本批已冻结输入。
