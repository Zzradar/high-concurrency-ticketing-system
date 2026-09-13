# Phase18 修正后最终报告

本地交付门禁与完整 after-v2 均通过，等待原独立审查继续复验。默认 OFF；没有 merge、PR、amend、rebase 或 force push。

**当前 After SUT：`6807a01516a75cf834ca1fac46fb1ac9abcdc53e`。** 基线 SUT 始终为 `ed51447154418e05ed9e4c49728f3eb114713db9`。旧 After SUT `4dd48c177516caf950103ce3f7751cc0fb056029` 被 ETag 缺陷否定，不能作为最终交付；after/ 全部原始字节保留，旧最终报告和交付清单原样存入 [history/fc9e41a](history/fc9e41a/README.md)。[状态索引](AFTER_STATUS.json) 明确区分二者，旧数字未混入新结果。

[当前交付 Manifest](phase18-delivery.json)、[完整 A/B 数据与八份协议哈希](comparison-v2.json)、[字段来源与修复设计](../../../docs/phase18_layout_revision.md)、[最终回归证据](capabilities/layout-revision-final/manifest.json)。

## 根因与修正

v1 ETag 只编码 Session/公开身份，没有覆盖 price、标签、行列、Zone 等真实表示变化；200 又可能把第一次轻量查询的旧标签贴到第二次查询的新 body。独立审查的直接 PostgreSQL price 100→101 反例先在旧代码上确认失败，修复后原 mutation、finally 还原和断言全部保留并通过。

migration015 引入每 Session 的单调 revision、确定性回填和数据库语句级 transition-table 触发器，001～014 未变。触发器覆盖真实 DTO 和排序来源，去重每个受影响 Session，只处理静态变化；动态状态、formal_version、Reservation 与未进入 DTO 的字段不改变 revision。空变更集连零行 revision UPDATE 都不执行。跨 Session/Venue 定向、回滚、迁移失败与重复执行均有测试。Session 删除保留 revision 记录以防 ID 重用复活旧标签。

轻量 identity/revision 查询匹配才返回 304；不匹配时，一条完整 SQL 同时读取公开身份、revision 和 Layout，service 携带该快照标签，200 不再使用先前轻量查询的标签。弱标签升级 seat-layout-v2，旧 v1 不会误命中。空布局、DRAFT/不存在、跨 Venue、gzip、标签列表、星号和非法条件头继续受原门禁保护。

实际 ADMIN 发布测试覆盖每 Session 5000/10000 席、每次两个 Session：分别插入 10000/20000 库存行，每次只更新两个 revision 行。SQL 批量、跨 Session、并发读取、后期触发器故障及显式回滚测试另行通过。没有活动级库存大锁，库存最终归属仍由 PostgreSQL 判断。

## 正式 OFF A/B

同一份冻结协议重新创建 DB、Redis、API、前端与数据；镜像、限额、浏览器/二进制、Playwright、数据指纹、八份协议文件、请求顺序和统计方法全部通过身份门禁。每规模为一次首次 Layout、20 普通、20 条件、一次 gzip；一份冷 Snapshot 加各20份 Snapshot/Delta。量化方法仍是冻结统计脚本；未筛选或重跑样本以改善数字。

单位 ms，p50 / p95：

| 席位 | 请求 | Baseline | After-v2 |
|---:|---|---:|---:|
| 5000 | Layout 普通 | 38.01 / 55.06 | 48.09 / 66.48 |
| 5000 | Layout 条件 | 37.14 / 57.33 | 3.74 / 27.83 |
| 5000 | Snapshot | 15.10 / 31.23 | 30.06 / 34.09 |
| 5000 | Delta | 5.51 / 7.87 | 14.91 / 28.33 |
| 10000 | Layout 普通 | 78.18 / 115.96 | 91.38 / 102.17 |
| 10000 | Layout 条件 | 76.03 / 92.22 | 3.54 / 20.83 |
| 10000 | Snapshot | 31.10 / 44.94 | 20.81 / 43.54 |
| 10000 | Delta | 4.90 / 24.20 | 14.89 / 27.31 |

首次 Layout 为 61.07→47.25 ms（5000）与102.72→90.43 ms（10000）。所有读取错误率为0。必须同时看到退化：两规模普通 Layout 中位数上升，5000 普通 p95 上升；5000 Snapshot 和两规模 Delta 的部分或全部延迟上升。不能声称全面提速。

| 每规模 Layout SQL | Baseline | After-v2 |
|---|---:|---:|
| 完整 Layout 调用 | 42 | 22 |
| 独立 metadata/revision 轻量查询 | 0 | 42 |
| 两类合计调用 | 42 | 64 |
| 5000 席完整查询返回行 | 210000 | 110000 |
| 10000 席完整查询返回行 | 420000 | 220000 |
| 5000 / 10000 席合计返回行 | 210000 / 420000 | 110042 / 220042 |

revision 已包含在轻量查询及完整查询中，没有额外的独立 revision SELECT。每规模42个 Layout请求：基线42个200，After-v2为22个200和20个304；304空 body，不执行完整 Layout SQL。**完整查询减少，但总SQL调用增加。** 行数是 pg_stat_statements 返回行数，不是物理扫描行/页；冻结协议未采集可比物理扫描量，不能冒称扫描下降。

200 Layout body 保持同一哈希：5000/10000席分别499636/1009237字节；gzip body分别28696/56831字节。全组响应体累计20513772→10521052、41435548→21250808字节。Snapshot/Delta因poll hint各增加19字节：50536→50555 / 536→555，102537→102556 / 537→556。这里的字节不含HTTP头部或TCP开销。

## 真实浏览器与流量

固定 headed Edge 152.0.4191.66、Playwright 1.63.0，二进制SHA-256 `02aaed8823a4e4bae8f672c620c9356bddebd68651d5bfd141ed9e6576d5f03c`。原启动参数及 CDP noDefaults=true 不变，单 Context、单真实窗口、两个真实标签页。context.newPage 创建中性页，bringToFront 完成原生可见性切换；记录 document.hidden、visibilityState、可信事件及两种时钟，未模拟事件或冻结生命周期。VITE_USE_MOCK_API=false，请求到本轮隔离 API。

| 指标 | Baseline | After-v2 |
|---|---:|---:|
| hidden epoch ms | 1789215545293 | 1789241936305 |
| restored epoch ms | 1789215555356 | 1789241946366 |
| 隐藏时长 ms | 10063 | 10061 |
| 前台 / 隐藏 / 恢复请求启动数 | 30 / 0 / 6 | 5 / 0 / 3 |
| 总请求 / 最大网络在途 | 36 / 2 | 8 / 1 |
| 首次恢复读取延迟 ms | 4 | 18 |
| 恢复后的权威 Snapshot 数 | 0 | 1 |

正式时段仍为60秒前台、10秒隐藏、10秒恢复。每个请求起止、状态及native时间线在 after-v2/browser.json。浏览器**解码后响应体累计增加69296→104440字节**，原因是恢复后执行权威 Snapshot；不能把请求减少当作带宽下降，也没有完整线速传输量证据。Redis EVAL 108→24，HGET 8304→12512。PG可见性读取36→8，同时新增42次事件registry查询（168行）与42次Session查询（294行）；OFF后台刷新有真实成本。

[同一冻结源码的91秒隐藏探针](capabilities/final-hidden-v2/manifest.json)另行通过：native hidden 1789242082112→1789242173163，共91051 ms；零隐藏请求、最大在途1、恢复一次权威Snapshot。延长时段只作能力门禁，不混入正式A/B。

## k6、争抢、资源和回归

k6配置均为8次到达/秒、15秒、预分配4/最大8 VU；**实际请求数121→120，检查242→240**，均零错误、零丢弃。配置相同不等于实际样本数相同，这一调度边界差异明确保留，不为凑121而重跑。中位2.263→2.190 ms，p95 3.291→3.246 ms。k6 PG可见性查询121→120；After-v2另有9次registry及9次Session刷新，原始查询与Redis计数见 query-feature-comparison-v2.json。

8用户争抢仍为1成功、7 SEAT_CONFLICT、无基础设施错误；通用原始errorRate=0.875包含预期409，不能解释为系统错误率。65项原有DB不变量均零违反，检查15000个Redis座位；额外Phase18审计/命名空间及Layout revision完整性检查也通过。

资源采样46→43份，无采集错误；VmHWM 237556→232564 KiB，采样RSS峰值173976→168672 KiB，线程155→163；采样cgroup内存峰值183541760→178114560字节，pids157→165。API仍2CPU/1GiB/256pids，无OOM。采样峰值不等于全时段绝对峰值，VmHWM自身为进程高水位。回归中的本地在途16/库存1达限、释放归零、回滚与金融/恢复通路均通过；双API总PG池预算8，未提高max_connections。

最终Release C++20/CTest36/36；Vitest288/288与production build；Python253/253（含交付测试）。OFF回归57/57，Phase15/17/18 Schema 4/8/2，revision Schema 6（含既有2项），Policy HTTP7、Admission5、Layout3、新revision HTTP7、实际大规模发布1、Waiting Lua7、Token Lua3、Auth/Zone5，限流/过载、真实Checkout exit88、Availability exit86/87、指标与verifier均通过。支付11、支付崩溃11、买家退款38、退款verifier3、双实例1全部通过。capabilities/layout-revision-final保存最终原始日志和已关闭夹具诊断。

## 身份、限制与复验

| 清单 | SHA-256 |
|---|---|
| Stage0交付 manifest.json（不变） | `19f394034d74e027a19e62f3e61f2ab82c9806b542604d666dc24d948640f338` |
| baseline/manifest.json（不变） | `c0891851436eb997e3414c4d2b6b5525a72c38b7fe635a9cb582e46d77b2e402` |
| 旧after/manifest.json（失效、字节保留） | `b1585c91e4cdb4e3aae915dc75552fb8ad2b591dd00fdf02d62af2716a7ac369` |
| 新after-v2/manifest.json | `67c848d55a499ec4d9fd898c2f34eb0fe6434e4bbd0926ebf68f4270b1117b33` |
| 归档的旧交付清单 | `3526dd8424d4ae9a6f33959d2840e8643a480d7d4a07f61ecc960ee65e10fc59` |

当前交付清单是 phase18-delivery.json，其SHA与交付Git提交一起回报。冻结runner保留历史STAGE0_VALID标签，当前清单明确其角色为AFTER_V2，没有改写原始manifest。6807a01之后只有派生分析、测试、文档与证据变化，生产文件未变。新增派生脚本只计算计数/资源峰值，测试用冻结基线黄金值校验，未修改延迟统计方法；其Git blob SHA单独记录。

这是共享16CPU主机上的一次匹配OFF试验，**不代表生产SLA**。采集前全主机Docker CPU约0.301核，没有专用CPU绑定；2～4秒采样可漏短峰。其他阶段及独立审查资源未操作。OBSERVE/ENFORCED证据单列，不算旧OFF提升比例。策略约2秒传播、15秒过期保护，不是全局线性化切换；只读认证缓存及共享认证PG池的限制、固定容量、Redis Cluster/Sentinel和多机未验证等原设计限制仍有效，见实施文档。静态修正会串行化受影响revision行；高频库存动态写不会触碰revision UPDATE。会话revision删除记录保留需要常规数据库容量规划。

原失败checkpoint和旧After都不作为可部署版本。预采集准备未计入正式结果；空UPDATE、网段池、共享故障环境、peer传播等待等诊断已关闭。自动审批曾拒绝无配套测试/commit的派生脚本写入，补齐3项测试并独立提交后已获准完成，无待处理批准。

复验：`python performance/scripts/phase18_ab_gate.py --after performance/experiments/phase18-admission-overload/after-v2`；`python -m unittest discover -s performance/tests -v`。独立审查的price反例可按能力证据脚本在新隔离数据库运行。专用after-v2 API/前端仍在18182/18183，生产默认OFF；原独立审查继续完成其剩余门禁。
