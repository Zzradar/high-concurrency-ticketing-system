# Phase18 after-v3 交付报告

migration016 已修复 Layout revision 的 search_path 遮蔽问题，完整回归与重新采集的 OFF A/B 门禁通过，等待原独立审查继续剩余门禁。默认 OFF。本报告只比较 baseline 与 after-v3，不引用失效 After 的指标计算收益。

## 身份与不可变证据

| 项目 | SHA / 状态 |
|---|---|
| Baseline SUT | `ed51447154418e05ed9e4c49728f3eb114713db9` |
| Stage0 交付 manifest.json SHA-256 | `19f394034d74e027a19e62f3e61f2ab82c9806b542604d666dc24d948640f338` |
| baseline/manifest.json SHA-256 | `c0891851436eb997e3414c4d2b6b5525a72c38b7fe635a9cb582e46d77b2e402` |
| 新 After SUT | `3a9e0c1311add748c7faec956bb6c9266ed7d5ba` |
| after-v3/manifest.json SHA-256 | `d1614a9761f8f0819be6e9da71677f096cc76d5beadf093e52915580f6f56440` |
| 当前交付 Manifest | [phase18-delivery.json](phase18-delivery.json)，独立 SHA 见 [DELIVERY_HASHES.json](DELIVERY_HASHES.json)，不是上面的 After 或 baseline Manifest |
| 旧 after | SUT `4dd48c177516caf950103ce3f7751cc0fb056029`；ETag v1 直接 SQL 变更缺陷，失效历史证据 |
| 旧 after-v2 | SUT `6807a01516a75cf834ca1fac46fb1ac9abcdc53e`；015 search_path 遮蔽缺陷，失效历史证据 |
| 上一交付 Manifest | [原字节归档](history/8a62d57/phase18-delivery.json)，SHA `b3690ca98faf5f588cd5428809a9ea98b4c42e0811bf104f3c752e1ea8ef1126` |

baseline、原八份协议、diagnostics、after、after-v2 和 migration001～015 均未修改。完整保留两个历史 After 的原始字节。新源码只追加016，不改写历史。八份测量脚本 SHA、数据指纹、镜像 digest、容器限额、预热、请求顺序和重复数均在 [after-v3 manifest](after-v3/manifest.json) 和 [comparison-v3](comparison-v3.json)，身份门禁全部相同。无预热、单轮、nearest-rank 统计方法保持冻结。

## 根因与修复

015 的六个 INVOKER 函数继承调用者 search_path，永久表和 helper 未限定 schema。修复前原反例得到 public revision=4、temporary revision=5，price100→101 后 body 改变、旧 ETag 却304。016 通过 CREATE OR REPLACE 保留六个函数和触发器绑定 OID；全部固定 `search_path=pg_catalog`，触发器按 TG_TABLE_SCHEMA 引用业务表和 helper；原 helper 的永久引用在安装时绑定其函数所属 schema。保持 INVOKER，不提升权限，不引入活动级锁。

修复后同一反例为 public revision=5、temporary revision=4，旧 ETag200、新 ETag304；还原价格后 body 恢复、revision 继续递增。完整 [函数审计](../../../docs/phase18_layout_resolution.md)、[真实安装定义/proconfig](capabilities/layout-resolution/installed-functions.json)、[修复前后证据与全部回归](capabilities/layout-resolution/manifest.json) 可复查。013、014 没有新增 SQL/PLpgSQL 函数，015 的六个函数全部覆盖。

测试覆盖默认路径临时表、前置普通 schema、同名 helper、其他来源表及 transition relation 遮蔽、不兼容临时结构、非 public 全迁移、014→015→016、已安装015升级、OID保持、重复016、失败回滚、最小业务角色实际提交及权限不足失败回滚。原全部 DTO/Zone/INSERT/DELETE/动态状态/同值零行/多Session/ID复用/并发body与ETag同快照/gzip/标签/DRAFT测试保持。真实 ADMIN 5000/10000 席、各两场 Session，10000/20000 inventory rows 分别只执行2次 revision 行更新。动态状态更新不执行 revision UPDATE；会执行静态投影比较，不能声称触发器成本为零。

## 正式 OFF 延迟与载荷

单位 ms；每个 ordinary/conditional/Snapshot/Delta 各20次，首请求单列且不计算分位提升。所有请求错误率0。正百分比表示延迟增加。

| 场景 | 基线 p50 / p95 | after-v3 p50 / p95 | p50 / p95变化 |
|---|---:|---:|---:|
| 5000 Layout普通200 | 38.01 / 55.06 | 48.71 / 63.45 | +28.15% / +15.24% |
| 5000 Layout条件请求 | 37.14 / 57.33 | 3.24 / 28.25 | -91.26% / -50.72% |
| 10000 Layout普通200 | 78.18 / 115.96 | 88.58 / 102.92 | +13.30% / -11.24% |
| 10000 Layout条件请求 | 76.03 / 92.22 | 13.49 / 24.15 | -82.26% / -73.81% |
| 5000 Snapshot | 15.10 / 31.23 | 29.99 / 32.60 | 退化 |
| 5000 Delta | 5.51 / 7.87 | 15.27 / 26.07 | 退化 |
| 10000 Snapshot | 31.10 / 44.94 | 30.58 / 43.98 | 小幅降低 |
| 10000 Delta | 4.90 / 24.20 | 3.71 / 23.46 | 降低 |

5000/10000 首次 Layout 分别61.07→45.05、102.72→97.89 ms。普通 Layout body 完全一致，499636/1009237 bytes；gzip 压缩 body 28696/56831 bytes，均未变。每组原42个200变为22个200及20个304，304 body=0。包含一次 gzip 的本组响应 body 总量20513772→10521052、41435548→21250808 bytes（均约减48.71%）。Snapshot/Delta 因 pollAfterMs 字段分别增加19 bytes；5000为50555/555，10000为102556/556。

## SQL、Redis 与 Registry 成本

每组 Layout 完整 SQL42→22次；新轻量 identity/revision SQL42次，返回42行；Layout相关总 SQL42→64次。5000返回行210000→110042，10000为420000→220042。完整 SQL 与 metadata SQL 均保留在 [comparison-v3](comparison-v3.json)。这是 pg_stat_statements 返回行，不是物理扫描行或 buffer-page 扫描次数。

包含调度、采样和嵌套 SQL 的 Layout时间段全部计数另列于 [layout-total-sql-v3](layout-total-sql-v3.json)：5000为67→85次、210005→110069返回行；10000为85→95次、420007→220080返回行。这一口径不得与上面的请求相关64次混用。

[查询特征](query-feature-comparison-v3.json) 显示：浏览器期间可见性检查 SQL36→8，但新增42次策略Registry扫描（168返回行）和42次Session Registry扫描（294行）；包括后台工作和观测的全部SQL416→477次。k6期间可见性检查121→121，新增9次策略扫描（36行）和9次Session扫描（63行），全部SQL197→220次。Registry并非免费，也不是每请求都去查策略表。

浏览器Redis EVAL108→24，HGET8304→12512；额外恢复Snapshot使HGET增加。k6 EVAL363→363、HGET7744→7744。Redis只是准入/派生读取模型，库存最终归属与金融不变量仍由PostgreSQL确定。

## 真实浏览器时间线

Edge152.0.4191.66、Playwright1.63.0；二进制 SHA `02aaed8823a4e4bae8f672c620c9356bddebd68651d5bfd141ed9e6576d5f03c`，固定启动参数、headed、原 CDP noDefaults 连接。一个Context、一个窗口（windowId628380634）、两个真实Page；第二页用 context.newPage()，原生 bringToFront。详细 target/window/context 与事件记录在 [browser.json](after-v3/browser.json)。没有人工事件、属性重定义、冻结或暂停定时器。

真实 trusted hidden=`1789270028344`，恢复visible=`1789270038395`，隐藏10051 ms。前台/隐藏/恢复请求数30/0/6→5/0/3，总数36→8（-77.78%）；最大在途2→1。恢复后11 ms启动一次权威Snapshot。基线恢复4 ms但为Delta，不能将4→11 ms说成恢复更快，也不能将基线隐藏0请求说成隐藏轮询数量的进一步下降。

| 阶段/模式 | 开始 epoch ms | 结束 epoch ms | HTTP | 解码body bytes |
|---|---:|---:|---:|---:|
| 前台Snapshot | 1789269968194 | 1789269968244 | 200 | 50555 |
| 前台Delta | 1789269970244 | 1789269970304 | 200 | 555 |
| 前台Delta | 1789269975362 | 1789269975402 | 200 | 555 |
| 前台Delta | 1789269987360 | 1789269987399 | 200 | 555 |
| 前台Delta | 1789270010793 | 1789270010832 | 200 | 555 |
| 恢复Snapshot | 1789270038406 | 1789270038453 | 200 | 50555 |
| 恢复Delta | 1789270040499 | 1789270040539 | 200 | 555 |
| 恢复Delta | 1789270045954 | 1789270045992 | 200 | 555 |

浏览器解码响应量69296→104440 bytes（+50.72%），请求减少不等于流量减少。此口径是 response.body() 解码body；不是压缩后网络流量，不含HTTP头/TCP。独立 [91秒隐藏门禁](capabilities/final-hidden-v3/manifest.json) 也通过，真实隐藏覆盖至少3个30秒周期，隐藏0新轮询、恢复一次Snapshot、最大在途1；不混入80秒正式A/B。

## k6、资源与正确性

同一8 arrivals/s、15秒、4预分配/最多8 VU协议，两次均121请求、242检查，错误率0、dropped iterations0。延迟median2.26331→2.256985 ms，p953.291461→3.170409 ms；仅单次小样本，不作为容量承诺。8用户争抢恰1次201、7次预期409，无内部错误；65项数据库不变量全0，15000席Redis校验通过；额外 [Phase18 verifier](after-v3-phase18-verifier.json) 9项全0，OFF无活动策略，不能据此替代单列的ENFORCED能力证据。

[资源与载荷](resource-and-payload-comparison-v3.json)：46→43个采样点；API VmHWM237556→233892 KiB，VmRSS173976→169964 KiB，cgroup memory183541760→179326976 bytes；线程155→163、cgroup pids157→165，线程和pid数量增加。PG pool4保持不变；同镜像及cgroup限额，API2CPU/1GiB/pids256、构建2CPU/4GiB等完整限额见Manifest。资源采样、连接状态、Dockerstats和指标均保存；离散采样可能遗漏短峰。

Release C++20/CTest36、Vitest288及production build、performance Python262；迁移、Policy/Admission、Waiting Room、Token Bucket、Bulkhead、Layout及Phase15/16/17回归通过。OFF旧业务57项、Stripe11、崩溃窗口11、退款38、退款verifier3、双实例1及鉴权/Zone5、Phase17负向verifier3均通过。独立过载能力测试32请求中16个按Bulkhead拒绝、峰值16并排空到0，金融/恢复200；双实例16个重复加入只有1个位置，9位置减5离开剩4、cap1实测峰值1。这些不是OFF A/B改善比例。

## 限制与交接

只代表单次共享主机实验，不代表生产 SLA。未停止或改动其他阶段资源；本阶段旧after-v2服务在采集前停止，两个无端点的旧after网络释放地址池，容器、卷和历史证据保留。无CPU独占/亲和性，主机页缓存不清空，首请求仅指本轮新API上的首读。普通200、5000 Snapshot/Delta、浏览器解码body和Registry成本的退化如上，不选择性省略。

首轮新schema夹具使用Windows默认GBK读取UTF-8迁移失败，已明确UTF-8后通过。能力Availability首轮auto-threaded夹具在Redis停机步骤遇到503；定向停机诊断返回200，固定4线程、单API后全门禁通过；没有改变产品或正式A/B配置。首个503的具体响应错误码未捕获，不能声称已证明其精确内部根因。该失败执行已由完整复跑替代，作为已关闭的本地夹具诊断保留。原search_path阻断反例已由相同断言确认关闭。旧checkpoint、两个失效After和失败日志均不是可部署版本。

016在可信迁移会话中明确选择安装schema；helper将该schema嵌入限定引用，未来任意schema重命名需要重跑016生成helper。支持非public安装；不声称支持运行时任意重命名schema。运行能力测试二进制与最终全新构建SHA相同（`a9a1278319f8ea231c075ebe658d80895b9246221405ec622d995bff849764f0`）；本轮生产变化是016，C++源码未变。

按职责追加修复、身份门禁、证据、报告提交；最终普通push，不merge main、不创建PR、不force push。最终提交SHA/Git状态和交付Manifest SHA见交付回复及DELIVERY_HASHES，等待原独立审查继续剩余门禁。
