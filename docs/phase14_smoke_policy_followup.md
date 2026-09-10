# Phase14 smoke 停止语义续验记录（2026-09-10）

状态：**尚未完成工程验收。新的第二轮 U2 因 planned/started 不一致停止，等待超出“只调整 smoke 停止语义”的调度修复范围确认。** 本地特征不构成万人正式容量证明。

## 已实施的模式差异

- `fdc9ff7`：仅缩小 smoke 的孤立 `pswpin` 增长记 `host_swap_activity` 警告，预检、主运行与 E1 均接入；测量有效性 fail，capacity not_applicable。警告不再使功能 smoke 失败。
- 正式模式及达到正式人数的输入不享有例外；任何换页增长仍停止。smoke 的换出、OOM/重启、错误、dropped、卡死与原安全线保留停止保护；换出继续采取保守停止，没有放宽为可忽略。
- smoke 单个系统/契约错误即时进入停止路径，正式错误窗口保持原规则。新增断点续跑只读旧记录，以新 Run ID 重跑首个未完成任务。
- `phase14-targets.json` 未修改；第二轮旧失败 `phase14-smoke-u2-20260910T014409Z-495ad3` 未改写。旧失败目录及正式配置共 102 个文件 SHA256 复核一致。

## 新 U2 失败事实与范围边界

Run ID：`phase14-smoke-u2-20260910T021810Z-70c707`。使用完整 smoke 快照恢复、Redis 清空、全新幂等命名空间及独立原始分片证据。

| 计划 | planned | started | completed |
|---|---:|---:|---:|
| enter_0 | 20 | 20 | 20 |
| refresh_0 | 10 | 9 | 9 |
| refresh_1 | 40 | 40 | 40 |
| control_health | 24 | 24 | 24 |
| control_auth | 24 | 24 | 24 |
| control_availability | 24 | 24 | 24 |
| payment | 12 | 12 | 12 |

错误为 `refresh_0: planned != started`；dropped=0，数据库不变量及该轮业务对账通过，资源 stopReasons=[]，warnings=[]。本轮不能算 U2 通过，未继续剩余压力矩阵。三层判定依次为 fail / not_applicable / not_applicable。该失败与先前的换页停止是两份独立事实。

定位到 `performance/scripts/run_phase14.py` 的 U2 `refresh_i` 每段独立 `ramping-arrival-rate` 执行器，以及 `phase14-flow.js` 的逻辑次数上界。两分片 refresh_0 分别启动 5/4 次，没有被上界过滤的多余 tick。冻结速率积分为 10，末次积分到达时间恰为 2 秒的执行器结束边界。

[k6 2.2.0 实际执行器源码](https://github.com/grafana/k6/blob/v2.2.0/lib/executor/ramping_arrival_rate.go#L219) 在积分达到整数时安排迭代，运行循环同时监听正常期限取消；取消返回发生在尝试分配 VU 及 dropped 计数之前（L423–453）。因此末次发车与结束取消重合是当前有源码支持的原因，尚未通过新的独立调度夹具修复验证。不能靠降低 planned、容忍少 1、补发额外业务请求或盲目重跑使结果变绿。

已请求的最小扩展范围：修复 U2 的刷新边界调度，实现确定性计划与实际交付校验，保持冻结人数、速率、时长、积分、身份隔离和严格守恒；先补调度回归，再用新 Run ID 继续。此项会改变调度实现，超出本次用户明确限定的停止语义，尚未实施。

## 独立工程检查

`f76e3f9` 增加专用回归、真实 exporter 和采样开销检查脚本及行为测试。结果见 [机器可读续验汇总](../performance/experiments/phase14-capacity/smoke-policy-followup.json)。

- Python performance：150/150，1.235 秒，日志 `performance/results/phase14-engineering/policy-followup-final-tests.log`。
- 既有集成回归：10 组 56/56，包含 HTTP、预订、checkout、临时占座、订单读取/取消、到期、模拟支付/退款、生命周期、认证及多客户端；各组用时和日志目录见汇总。
- 独立 simulation 强制 FAILURE 服务：1/1，4.343 秒；原成功后端停止后运行，结束即停止故障服务并恢复原后端。库存保持与新支付重试原断言不变。未访问 Stripe。
- 真实 `/metrics`：5 个既有小夹具全部通过；HTTP auth/seat_read/checkout/reservation、事务、Redis hold/auth/login 与 expiry 有真实样本；标签检查无动态值，在途计数全部归零。夹具后全局数据库 14 项不变量均为 0。
- 真实 exporter：6/6。空闲 ClientRead 排除、监控连接排除、真实 PgSleep 活动等待计入、idle transaction 单列、未授予咨询锁与阻塞链、aborted transaction 单列。关闭后自有连接剩余 0。
- 采样开销：固定 20 次/秒、4 秒、ABBA 四腿，每腿 80/80 请求，错误/dropped=0。比较两腿分位数的中位数（这是对照统计，不是分片全局百分位汇总），p95 增幅 -0.749%，p99 -7.154%，低于 5%。开启腿包含独立 200ms PG 采样。短时 no-op 对照样本不足以建立正式上界，measurement_validity=fail、capacity=not_applicable。
- backend 生产代码本次未改，沿用已成功的标准构建、CTest 30/30 和观测契约 4/4、3/3；本次没有重复构建。

回归适配仅改变运行位置和夹具执行方式：旧 psql helper 路由至专用 Phase14 SQL 入口；Redis kill/rm/up 夹具改为 tmpfs stop/start，保留容器与原业务断言。没有执行 down/rm/prune/-v，未停止其他项目容器或宿主 Stripe CLI/Vite。源码及前端文件未被格式化或回退，未 push。

尚未完成：第二轮 U2 及剩余完整压力矩阵（O/H/L/E/S 等），H3 真正同时发车与轻量采样窗口验证，当前浏览器请求图校准。Phase11/12 Stripe 协议专属集成测试本次未运行；已运行的模拟支付测试覆盖共享支付/退款服务，但不声称替代 Stripe 协议验收。正式容量运行仍缺压力机与 SUT 的 CPU/资源隔离。

后续用户已批准共享调度边界修复；本文作为当时的失败与范围确认记录保留，最新结果见 [v2 交付报告](../performance/experiments/phase14-capacity/report.md)。
