# 座位图优化证据审计（Phase17 修复轮）

审计日期：2026-09-12。结论：核心分阶段优化数据已经进入正式记录，本轮把版本、接口含义和可比较范围集中列出。没有删除、覆盖或改写旧证据，没有计算跨阶段“总提升比例”。

## 原始记录与版本

|阶段|可追溯版本|配置与比较范围|正式记录 / 原始数据|
|---|---|---|---|
|Phase10B 完整 Seat → Layout/Availability|拆分前 gitHead `fbaa1575c1c357a5c6d41beb3422adcbd8ad2b71`，image `sha256:b4978f76b65fcddff15a5c40b36a6b5c32573421276048229f5f9a666388dc29`；后记录 HEAD `8365ef4a64526096fa12c1cd8a8250a9b2f985e9` / `44fba67542f23647abdfa33096164ee408d1eedb`，同一运行 image `sha256:aa359ea9ae8a874f3ce6a798f3c554757c7fcc05ce7eb9ed1e916c50d7e1abd6`、未重启|5000 席，scale-100k 的 3 个价格区，PG pool4、Redis pool2、compute4/queue16、Redis timeout0.4s；同机历史受控全量刷新对比，不是两个干净 SHA 重新构建的 A/B|[拆分记录](../performance/experiments/phase10b-seat-map/static-dynamic-split.md) / [完整原始 JSON](../performance/experiments/phase10b-seat-map/static-dynamic-split-measurements.json)|
|Phase16 旧全场 Availability → Zone Snapshot/Delta|记录的稳定基线 `9006ee822e557255e244364495fbe251a1a25b18`；同一实现内不同读模式|5000 席、5 区各1000席；16 CPU / 15.41 GiB Docker，PG16/Redis7.4，Release C++20；pool4/2、compute4/16、Hold300s；200/s ×20s，100 VU，每模式预热30次|[实施记录](phase16_availability_read_model_implementation.md) / [正式表](../performance/experiments/phase16-availability/README.md) / [warm 原始数据](../performance/experiments/phase16-availability/warm-evidence.json) / [查询增量](../performance/experiments/phase16-availability/summary.json)|
|Phase17 动态发布规模|证据随验收起点 `6c3d3994226f524fe44dde0522dee497203f5c7a` 保存；scale.json 未单独绑定运行二进制 SHA，不能把保存提交当作运行版本证明|5000/10000 席、各5区、1场次；顺序创建/发布，读请求各20次，浏览器5次；不是并发容量或生产 SLA|[实施记录](phase17_admin_event_publishing_implementation.md) / [规模 JSON](../performance/experiments/phase17-admin-publishing/scale.json) / [证据说明](../performance/experiments/phase17-admin-publishing/README.md)|

Phase10B 两个 after HEAD 的差异，原记录解释为并行前端提交；运行容器及镜像未变。这里保留镜像身份与历史对照限定，不提升为干净源码 A/B 证明。3 区依据原始版本的 `performance/data/profiles/scale-100k.json` 与 `prepare_profile(5000)`，不是用 Phase16 的5区配置反推。

## 响应和延迟对照

|阶段 / 接口与范围|raw / gzip bytes|p50 / p95 ms|样本口径|
|---|---:|---:|---|
|10B 旧完整 `/seats`，5000席、0% Hold|822421 / 44086|39.449 / 57.543|historicalBeforeRuns 第1轮，60/s、15s；HTTP统计含探针|
|10B Layout，5000席|542466 / 41507|22.63 / 25.50|10/s、15s；首次静态读取，不能与60/s行直接算提升|
|10B 全场 Availability，5000席、0% Hold|265046 / 12966|15.735 / 19.782|after 第1轮，60/s、15s；已有Layout后的刷新对照|
|16 legacy **全场 Availability**，5000席|260046 / 13114|22.193 / 53.526|200/s、20s，0错误/0 dropped|
|16 Zone Snapshot，1000席|52546 / 2901|541.167 / 681.112|同负载，164错误/737 dropped，**失稳结果**|
|16 no-change Delta|546 / 546|1.264 / 1.982|同负载，0错误/0 dropped|
|16 controlled Delta，1次变化|591 / 591|1.302 / 2.060|反复读同一变化游标，不是持续写入200/s|
|17 Layout，5000席|824766 / 31732|59.011 / 64.846|顺序20次，本地gzip|
|17 Layout，10000席|1653966 / 63183|105.022 / 117.024|顺序20次，本地gzip|
|17 Zone Snapshot，1000席|119586 / 2859|29.839 / 32.518|顺序20次，本地gzip|
|17 Zone Snapshot，2000席|239506 / 5343|42.702 / 47.160|顺序20次，本地gzip|
|17 no-change Delta，5000 / 10000 席|566 / 241；566 / 240|4.735 / 21.249；15.622 / 17.263|每种规模顺序20次，本地gzip|

Phase16 benchmark 源码的 legacy 是不带 zone 参数的 `/seat-availability`，不是完整 `/seats`。Phase16 小响应没有 Content-Encoding，546/546 和591/591是实际未压缩传输，不能宣称压缩收益；Phase17 gzipBytes 是本地压缩，不能与其等同。Phase10B identity/gzip 解压正文逐字相同。

## 查询、初始化、浏览器与正确性

|阶段|PG 查询与范围|Redis 初始化 / EVAL|浏览器与正确性|
|---|---|---|---|
|10B|旧刷新每次完整 `session_seats JOIN seats`；拆分后 Layout 读取静态字段，Availability 每次仍全场 `id,status`，不 JOIN seats；原JSON有精确 calls/rows/SQL|此阶段没有 formal read-model 初始化；仍读取临时 Hold，不能把缺少 init 指标写成0ms|首次页面必须 Layout+Availability 合并，不可只计后者；稳定轮 exact、verifier14/14、无reject；300/s Availability已失稳|
|16 warm，4000请求窗口|legacy全场id/status查询4000次；Snapshot/Delta全量初始化0次；Delta无全场库存读；失稳Snapshot有26次目标区+26次Summary降级查询|冷48请求/并发24只执行1次PG初始化，批次391.25ms；独立冷请求80.32ms，PG7.35ms，init Lua50.343ms|静态5000，当前区DOM1000；[真实浏览器记录](../performance/experiments/phase16-availability/playwright.json)覆盖跨区/ownership/TTL/confirm；[cold](../performance/experiments/phase16-availability/cold-timing.json)、[init race](../performance/experiments/phase16-availability/init-race.json)、故障恢复与verifier原记录保留|
|17，5000 /10000|冷全场formal查询各1次，12.747 /29.954ms；20次no-change Delta全场库存查询0，公共可见性EXISTS各20次，不能称零PG|冷HTTP128.123 /235.197ms（各1次，不能解读统计p95）；EVAL12.280 /19.446ms|当前区DOM1000 /2000；navigation→两次RAF p50/p95为400/470及598/653ms；[5000浏览器原始](../performance/experiments/phase17-admin-publishing/browser-5000.json)、[10000](../performance/experiments/phase17-admin-publishing/browser-10000.json)|

查询增量包含后台任务，不能把SQL表所有calls之和称作单请求roundtrip。浏览器时间包含网络与框架更新，不是纯绘制耗时。Phase17 5000/10000 Venue 创建281.323/523.813ms、发布230.561/486.563ms，各为单次顺序样本。

## 可比较范围和缺口

- Phase10B 同规模、同配置的受控旧完整刷新与新动态刷新已有核心证据；Phase16 同运行实现的四种读模式已有核心证据。无需重复长时间容量矩阵。
- Phase10B 3区、Phase16 5区、Phase17 动态长ID/标签和不同响应字段不是同payload；不能跨阶段算总加速比，也不能把Phase16失稳Snapshot说成稳定能力。
- [Phase17旧夹具对照](../performance/experiments/phase17-admin-publishing/layout-comparison.json)的基线是现存含Phase16的Phase15镜像 `sha256:c7d9f990bcf1701995d474dd3d39a6c54dfd16af8261bac09b5c55934cb82430`，非固定基线重建。两侧5000席Layout均509646/28706 bytes；p50/p95为42.162/60.735与46.466/60.805ms，只能参考，不能归因于012 JOIN。
- 仍缺少“跨所有阶段、同payload、干净准确SHA构建”的单一全链路A/B，以及Phase17 scale原始运行SHA绑定。这里不补造版本、不宣称因果提升。核心分阶段证据已具备，本轮仅修复金额/迁移兼容/前端异常，不改读模型；因此未启动额外性能复测。若以后要发表跨阶段收益或Phase17迁移性能结论，必须另做准确版本、同配置的小型A/B。
- Phase14 smoke不是容量资格；Fake Stripe/后端simulation不是生产支付；本轮不重跑无关联支付退款全矩阵、Phase14 G0/U1/U2、Phase16完整故障矩阵或Phase17全量规模测试。
