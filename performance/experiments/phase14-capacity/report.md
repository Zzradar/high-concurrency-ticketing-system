# Phase14 阶段性证据：工程实现未完成验收

**本地特征不构成万人正式容量证明。** 当前按冻结的宿主交换停止条件暂停；不得把下表 smoke 或百万注册数据规模写成万人容量通过。

## 最近一次批次停止

`phase14-smoke-u1-20260910T001313Z-90e143` 在第二轮 U1 检测到宿主 VM `pswpin: 322787 → 322791`，`pswpout: 537116 → 537116`。该轮数据库全局不变量全为 0、dropped=0；仍判测量无效并停止后续场景。运行器只停止本 Run ID 的 k6，未操作其他项目。

未证实后端容量瓶颈。共享宿主无专属 CPU 核，存在其他项目进程；仅能确认交换发生，不能将其归因于 Phase14 或某个业务组件。

## 所有实际启动的负载轮次

| Run ID | 场景 | 功能 smoke | 测量有效性 | 稳定容量 | 过载保护 | dropped | DB 校验 |
|---|---|---|---|---|---|---|---|
| phase14-smoke-e1-20260909T170528Z-12a45d | E1 | True | fail | not_applicable | not_applicable | — | True |
| phase14-smoke-g0-20260910T001135Z-0fa1cf | G0 | True | fail | not_applicable | not_applicable | 0 | True |
| phase14-smoke-h1-20260909T170120Z-bf934b | H1 | True | fail | not_applicable | fail | 0 | True |
| phase14-smoke-j1-20260909T164500Z-9c83c5 | J1 | 未完成 | 未完成 | 未完成 | 未完成 | — | 未完成 |
| phase14-smoke-j1-20260909T165206Z-6e1f3c | J1 | True | fail | not_applicable | not_applicable | 0 | True |
| phase14-smoke-u1-20260909T165520Z-f0856a | U1 | True | fail | not_applicable | not_applicable | 0 | True |
| phase14-smoke-u1-20260909T170651Z-a52876 | U1 | True | fail | not_applicable | not_applicable | 0 | True |
| phase14-smoke-u1-20260909T170740Z-eb9b9d | U1 | False | fail | not_applicable | not_applicable | 1.0 | False |
| phase14-smoke-u1-20260909T171208Z-2c296f | U1 | False | fail | not_applicable | not_applicable | 1.0 | False |
| phase14-smoke-u1-20260910T001227Z-f79044 | U1 | True | fail | not_applicable | not_applicable | 0 | True |
| phase14-smoke-u1-20260910T001313Z-90e143 | U1 | False | fail | not_applicable | not_applicable | 0 | True |

每轮完整 planned/started/completed/interrupted、五类步骤计数、原始合并 p95/p99、恢复判定和错误列表见 [evidence-summary.json](evidence-summary.json)。原始 JSON/gzip、SHA256、PostgreSQL 快照、采样与命令记录保留于 `performance/results/<Run ID>/`，不进入 Git。

早期通过轮不代表当前全部新增核对项已运行：H1 临时占座首次预演验证的是 2 胜/18 冲突和全局数据库不变量，随后增加的 Redis owner/TTL 对账仅完成单元测试，待新轮执行。短 smoke 保留正式恢复窗口，因此不作为“五分钟恢复通过”。

## 数据及认证预检

- 实际生成 1,000,000 注册用户、100,000 预置会话、20 个场次、100,000 场次座位。生成耗时 6.093 秒；进程峰值工作集 25395200 bytes；Python 跟踪峰值分配 489784 bytes。
- 已将正式数据导入 Phase14 独立数据库并生成快照。数据文件大小、哈希及源配置哈希见证据汇总内 generation.manifest。
- 1000 cold + 1000 hot `/auth/me` 全部身份匹配，分别耗时 16.578 秒、14.188 秒。预热 10000 身份后，100000 会话仍覆盖 300 个写回秒桶，桶计数范围 296–385。
- 敏感随机 token 只在被忽略的生成目录；上述生成统计来自独立 formal-memory-proof 输出，token 随机性导致它与实际导入 formal 数据文件哈希不同，均保留各自 manifest，不混用。

## 失败记录与处理

- 首次 smoke 数据库校验器因 psql 默认分隔符不匹配失败；改为显式 Tab 分隔，保留原日志。
- k6 时间戳小数位解析失败：9 位截断后仍漏掉 5 位情形，导致批次中止；现在统一兼容 RFC3339Nano 1–9 位，增加边界测试。中止轮仍失败，未用重新分析将其改成成功。
- 支付探针 VU 在边界 tick 耗尽，产生 1 dropped；已添加压力机端边界余量，实际 HTTP 计划数量不变。后续完整 U1 轮 dropped=0。
- 认证预检曾发生自动权限审核超时及一次 HTTP 超时；失败日志保留，增加抽样进度后实际完成冷/热与预热。
- 最新批次遇宿主交换，保持停止，不关闭停止规则，不以重跑碰运气。

## 尚未完成

- U2、O1、H1 正式预订与重复、H2、H3、L1/L2（含完全同速对照）、S1 的完整缩小矩阵未运行。J1 只执行过首档；U1 第二轮最新批次因交换停止。
- G0 已执行缩小 no-op 调度，但正式规模 no-op 和有/无采样的开销对照未完成。H3 200 ms 轻量采样及开销证明未实现。
- 本次真实浏览器少量页面请求图校准、被观测接入触及的全部后端集成回归、真实等待/idle ClientRead exporter 故障夹具验证未运行。
- login 背景对照汇总、Redis 热点 owner/TTL 运行核对等新增分支尚未取得端到端证据；最终规范门禁未全通过。
- 正式隔离环境未建立，正式 U1/U2 万人及 S1 30/60 分钟容量场景未运行。

Phase14 未修改前端，沿用合入主分支前端门禁；本阶段不包含真实 Stripe 万级支付、电子票或验票。

## 工程检查

- Python performance 回归：128/128，1.003 秒；日志 `performance/results/phase14-engineering/python-tests-checkpoint-final.log`。
- 既有 metrics 源码契约：4/4，0.008 秒；Phase14 契约：3/3，0.134 秒。
- 标准 Dockerfile 构建成功，CTest 30/30，测试段 0.96 秒；日志 `performance/results/phase14-engineering/backend-build-first.log`。
- `git diff --check` 通过；前端文件未改动；未 push。
