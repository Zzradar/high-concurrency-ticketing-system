# Phase14 v3 本地工程交付

**冷启动模型、smoke 判定语义、代码测试及本地功能预演已完成。正式万人容量验证尚未执行；当前没有证据证明或否定万人容量。**

起点为干净 main `84a0acd`，实现提交 `af4ebee`，文档提交见 Git 日志。本次没有修改 frontend、后端业务代码、状态机、数据库迁移、连接池/线程池/队列或正式阈值；未 push。最终工作区及提交检查记录位于 `performance/results/phase14-engineering/v3-final-git-audit.json`。

## 模型与独立浏览器证据

新独立记录 `performance/results/phase14-browser-v3-cold-20260910/browser.json` 确认正常已登录冷启动10个GET：认证2、通知2、场次/活动/布局/余票各1、可恢复checkout列表1、订单列表1。认证、通知、三项页面读取、两个列表四组均观察到请求区间重叠。源码依赖边与实现详见 [v3实施说明](../../../docs/phase14_v3_closeout.md)。两次浏览器记录中通知与场次的交错略有不同，负载复现异步因果关系，不强行串行为一条固定完成顺序。

U1/U2/J1/S1每个身份仅首次进入执行一次启动；新固定startup_*标签与持续availability分开，原page指标仍覆盖原页面业务窗口。60/25/15比例、思考时间、购买次数、刷新速率、业务人数及窗口未改；例如双分片U2仍为12个浏览、5次放弃、3次确认。O1不增加页面成本，H/E不增加启动调用。通知的后续定时/焦点事件不是本次一次性启动模型的一部分，没有把它循环加入整个十分钟。

L1两轮各84个背景身份、840个启动HTTP；L2两轮各68个、680个启动HTTP。均在releaseAtMs之前约8.5秒完成，原背景预热和登录窗口随后执行。独立background-startup目录保存计划、原始分片、校验和及守恒，计时内startup计数为0；启动洪峰不混入登录隔离比较。

配置version3仅新增pageStartup描述并提升版本；hash为 `e7dc8c8cb899a6a1b3166b48bb877edcce2ab806b918e15dd6c11bc22cd6d1aa`。与v2逐项比较后，所有其他业务/安全/正式标准字段相同。使用独立smoke-v3数据和快照；历史v1/v2配置、运行与失败不变。共享1秒非业务保护尾段仍保留，吞吐分母不含尾段；边界tick在HTTP与身份访问之前退出。

## 本次增量矩阵

12条最终增量记录全部功能/调度/数据库检查通过。另有修复前2条通过的U1及1条失败的U2记录，完整保留在首批campaign中，不用最终结果覆盖。每轮完整恢复快照、清空Redis，使用新Run ID与幂等命名空间。

以下主负载计数排除control/payment，L包含原背景；闭合模型planned为—。启动列为HTTP数（每用户10），预热列不计入主负载计时。三层判定依次为正式测量资格/容量/过载保护，N/A即not_applicable，不是pass。

| 场景/参数 | Run ID | 主planned/started/completed | 计时内启动HTTP | 计时前启动HTTP | dropped | 功能/正确性 | 三层判定 |
|---|---|---|---:|---:|---:|---|---|
| U1 {"round":0} | phase14-smoke-u1-20260910T042116Z-5d3d70 | —/59/59 | 200 | 0 | 0 | pass | fail / N/A / N/A |
| U1 {"round":1} | phase14-smoke-u1-20260910T042208Z-9ceeff | —/60/60 | 200 | 0 | 0 | pass | fail / N/A / N/A |
| U2 {"round":0,"shards":1} | phase14-smoke-u2-20260910T042300Z-ce9ddf | 70/70/70 | 200 | 0 | 0 | pass | fail / N/A / N/A |
| U2 {"round":1,"shards":2} | phase14-smoke-u2-20260910T042348Z-4b696c | 70/70/70 | 200 | 0 | 0 | pass | fail / N/A / N/A |
| J1 {"window":0} | phase14-smoke-j1-20260910T042440Z-3c60ea | 20/20/20 | 200 | 0 | 0 | pass | fail / N/A / N/A |
| J1 {"window":1} | phase14-smoke-j1-20260910T042532Z-54fd52 | 20/20/20 | 200 | 0 | 0 | pass | fail / N/A / N/A |
| J1 {"window":2} | phase14-smoke-j1-20260910T042620Z-57f742 | 20/20/20 | 200 | 0 | 0 | pass | fail / N/A / N/A |
| S1 {} | phase14-smoke-s1-20260910T042705Z-5587bc | —/130/130 | 200 | 0 | 0 | pass | fail / N/A / N/A |
| L1 {"control_only":true} | phase14-smoke-l1-20260910T042804Z-bf7172 | 224/224/224 | 0 | 840 | 0 | pass | fail / N/A / N/A |
| L1 {"control_only":false} | phase14-smoke-l1-20260910T042915Z-ffa048 | 244/244/244 | 0 | 840 | 0 | pass | fail / N/A / N/A |
| L2 {"control_only":true} | phase14-smoke-l2-20260910T043024Z-5efb56 | 168/168/168 | 0 | 680 | 0 | pass | fail / N/A / N/A |
| L2 {"control_only":false} | phase14-smoke-l2-20260910T043128Z-e90134 | 188/188/188 | 0 | 680 | 0 | pass | fail / N/A / N/A |

每个新增启动步骤均逐项planned=started=completed；U2单/双分片各20个启动用户、200个启动HTTP，主业务70/70/70，control和payment也守恒。每步成功/冲突/拒绝/错误计数、p95/p99、原业务吞吐和资源峰值见 [机器可读汇总](v3-evidence-summary.json)，原始点与源代码副本仍在各Run ID目录。

## smoke判定与诊断

新smoke只以功能、调度、正确性与证据链作为工程门禁。capacity、overload_protection、formal_recovery统一not_applicable；measurement_validity仍说明本机、小样本不具备正式测量资格。恢复计算仍使用原正式窗口，并将实际缺口放入diagnostic，未改成通过。

本次L1/L2背景余票p95倍率分别为1.00和2.00；L2的2倍仍超出原1.5倍比较线，作为诊断保留。背景占座倍率分别约0.738/0.670，下单倍率约1.086/1.305。启动与预热都在比较窗口之前，原背景输入相同。不能把L1诊断符合某条阈值解释为正式升档门禁通过。

只做一次既定60秒×4腿、20rps的ABBA开销对照：每腿1200/1200，错误与dropped均0；p95增幅−4.19%、p99增幅−3.65%，诊断比较落在原5%内。顶层status和capacity仍not_applicable，measurement_validity为fail。证据 `performance/results/phase14-sampling-overhead-20260910T043854Z`。历史持久采样4秒对照失败（+5.60%/+39.06%）及后续独立60秒记录均不改动，见v2汇总。

## 首次失败与观测修复

保留 `phase14-smoke-u2-20260910T041640Z-096c7d` 的失败：主负载70/70/70、dropped=0，但CLI时钟采样估计105.85ms触发原100ms停止线；该样本不确定范围320.54ms。全局14项数据库不变量均0、12笔支付已完成且invalid=0，但终止造成客户端支付终态证据缺失，原payment terminal reconciliation失败仍保留。

修复是在SQL计时前建立只读psql连接，避免将不对称CLI启动耗时算入偏移，随后关闭该精确连接。没有降低时钟门槛、容忍dropped或改写旧结果。新轮次保存偏移/不确定范围和连接关闭记录。普通测试首败（旧比较字段及clock mock缺少配置）日志也保留，修复没有删除原断言。

## 工程门禁与证据沿用

- 全部performance测试（包括原Phase10相关数据、证据、数据库与观测测试）及新增异步图、一次性执行、切片/分片、守恒和smoke语义测试，实现提交前162/162通过，3.874秒；日志 `performance/results/phase14-engineering/v3-precommit-tests.log`。包含最终报告回归的全套测试163/163通过，3.947秒，日志 `performance/results/phase14-engineering/v3-final-tests.log`。
- 本次后端集成56/56，10模块，测试累计261.141秒，0失败/错误/跳过；数据库不变量通过。日志 `performance/results/phase14-engineering/v3-regression.log`，逐模块结果位于 `phase14-regression-20260910T043303Z`。
- 后端源码观测契约4/4，0.011秒，日志 `v3-source-contract.log`。标准Dockerfile构建与CTest日志为 `v3-backend-build.log` / `v3-ctest.log`，均在 `performance/results/phase14-engineering` 下。构建成功；新构建镜像全部CTest 30/30通过，1.11秒。
- 沿用O1三档、H1/H2/H3及E1共12条v2本地功能记录：业务输入、实际HTTP写链、映射和不变量未变；新增async等待通过真实模块测试覆盖。共享时钟采样修复已由本次全部混合场景验证，但不把旧O/H/E重新标为v3正式测量。
- 原G0、单/双分片保护尾段探针、H3持久采样集中度、真实exporter六类故障夹具与metrics真实触发记录保留。exporter查询与后端观测生产代码本次未变，故不机械重跑这些夹具；本次重新执行受影响集成和采样开销对照。
- 百万注册/十万会话的真实生成、1000冷/热身份校准、文件哈希和约24.2MiB生成峰值沿用 [初始证据](evidence-summary.json)，数据生成逻辑未变；本次仅新生成smoke-v3。数据规模不代表并发人数。
- 审计25份v2 verdict及94个原始分片校验和不变，40个历史运行的配置与manifest哈希匹配。历史报告另存 [v2原文](report-v2-checkpoints.md) 和 [v1阶段原文](report-v1-checkpoints.md)，不重写旧判定。

只读核验89个非Phase14容器的状态、端口与挂载均与原审计一致，三个已批准停止项目的数据卷仍存在。只关闭本会话拥有的浏览器、Vite和Phase14测试进程；未停止其他项目，未执行down/rm/prune或卷删除。

## 三项独立结论

1. Phase14代码、测试及本地功能预演完成情况由上述新旧明确区分的证据支持；冷启动增量矩阵已完成。
2. 正式万人容量验证仍缺压力机与被测系统的隔离条件、资源/时钟资格证据和正式G0。正式万人U1/U2、长期S1未运行。
3. 当前没有证据证明或否定万人容量。本机小样本的相对延迟或采样开销不能外推万人通过或失败。

不宣称已定位后端万人容量瓶颈。已定位并修复的是负载模型缺少确定的启动读取以及时钟采样混入CLI启动耗时；Phase14不包含真实Stripe万级支付、电子票或验票。
