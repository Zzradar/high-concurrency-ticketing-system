# Phase10B-3：Seat Map 诊断校准

## 范围与测量边界

起点 `main`，工作区 clean，HEAD `d9a81004249535560be0eb6a2aa11a8228fff5c0`，
origin/main `2aec8a5ba492e5cdb64f91e33391f5c2c634f7e7`，ahead 11。
旧 `diagnosis.md`、`measurements.json` 保留，不把历史观测改写成新结果。
本轮只校准诊断，不实现 API 拆分、缓存、singleflight、线程迁移、连接池调整、限流、多实例或压缩配置优化。

本轮删除 Controller 内仅用于测量的提前 `response->getBody()`，仍以原来的 lvalue
`newHttpJsonResponse(body)` 构造响应，未改变 DTO、SQL、库存裁决、Redis fallback 或线程调度。
保留 11 个阶段和 in-flight 指标。`json_serialize` 为
**not directly measured in production-equivalent path**；没有单独 micro-benchmark，
不拿旧 serialization 数字冒充当前阶段成本。
响应 bytes 改由压力窗口外 identity/gzip HTTP probe 测量，删除会诱导提前序列化的在线 bytes histogram。
`response_callback` 现在包含自然序列化/可能的压缩及框架同步工作，不能与旧 callback 阶段直接比较，
也不能解释成 socket-flush 时间。PreSending 和 in-flight 终点在自然序列化之前，
旧插桩版本则提前完成了序列化；in-flight before/after 存在这一观测边界差异。

独立 `seat-map-calibration.js` 保持 steady arrival-rate、700 preallocated VUs、没有 maxVUs 或 pacing sleep。
原 `seat-map-read.js` 未修改。0% 压测仍丢弃 body，setup 校验完整数组；90% 场景逐响应解析并统计
HELD/AVAILABLE/SOLD（这会增加 k6 CPU，不能把两个密度的生成器开销视为完全一致）。
identity 明确发 `Accept-Encoding: identity`，历史默认是不发该请求头，两者均不压缩。
每个 run 含一个 k6 setup 请求；fixture 检查和 bytes probe 在 metrics-before 之外。
PromExporter 的 5 秒缓存仍保留，前后静默 6 秒再取累计 counter/histogram 差值，
运行中的 in-flight 是有缓存、非连续的抽样值，不是精确最大并发或 socket 在途数。
阶段分位数是固定 histogram bucket 插值，HTTP 分位数来自 k6；不能简单相加，也不是 CPU profile。
CPU 使用 cAdvisor 30 秒 rate 的最大观测值（cores）；15 秒短测受平滑窗口影响。
同机 Docker/k6、单次运行、非交错重复实验，数值波动不能全部归因于这次微小代码差异。

所有操作限定现有 `ticketing-phase10a`，不删除卷，不操作普通开发项目。
每个 run 核对 formal inventory 为 5000 AVAILABLE，fixture 的临时持有者为其他 owner，TTL 600 秒，
不会在 15 秒压力窗口内自然过期。逐样本检查健康状态和 3 GiB Backend working-set 保守停止线；
无自动扩压。每次完成后运行 14 项数据库 verifier，结束前再做完整回归。

## 固定 Drogon 版本与线程事实

实际构建树版本为 v1.9.13 对应 commit `4c5430757ea5451a7c38fbbef4b4bef7dbb47f2f`。
通过已有 build-inspect 镜像中的源码核对，而非依据最新版实现猜测：

```text
SeatController → SeatService → SeatRepository / PostgreSQL async query
→ rows / DTO / ids → SeatHoldService::readOwners → EVAL / MGET
→ RedisConnection::handleRedisRead / hiredis / handleResult（RedisLoop）
→ owner parse → overlay → JSON build → response create（保留 lvalue copy）
→ HTTP callback → HttpServer::handleResponse
→ PreSending → getCompressedResponse → shouldBeCompressed → getBody（自然 lazy serialization）
→ 按 Accept-Encoding 压缩（若适用）
→ connection EventLoop 的 queueInLoop → sendResponses
```

因此必须修正“去掉提前 getBody 就必然把序列化移出 Redis callback 线程”的假设：
当前 JSON 响应正常路径中，`shouldBeCompressed()` 在检查请求是否接受 gzip 之前会读取 body 长度，
而 `getCompressedResponse()` 位于 HTTP EventLoop handoff 之前。成功 reply 分支自然序列化依然在
Redis callback 线程内；超时 fallback 则继续在执行 timeout 的 RedisLoop 上构造响应。
本轮恢复了框架调用时机，并没有把序列化迁到其他线程。早读仍会改变阶段归属和 PreSending 边界，
应当移除，但不能预先声称它制造了整个线程归属问题。

核对位置：[RedisConnection.cc](https://github.com/drogonframework/drogon/blob/4c5430757ea5451a7c38fbbef4b4bef7dbb47f2f/nosql_lib/redis/src/RedisConnection.cc#L300)、
[HttpResponseImpl.cc](https://github.com/drogonframework/drogon/blob/4c5430757ea5451a7c38fbbef4b4bef7dbb47f2f/lib/src/HttpResponseImpl.cc#L117)、
[HttpServer.cc](https://github.com/drogonframework/drogon/blob/4c5430757ea5451a7c38fbbef4b4bef7dbb47f2f/lib/src/HttpServer.cc#L773)。
官方线程文档也说明，EventLoop 逐项处理任务，客户端 callback 不保证回到原 HTTP handler 线程，
重计算会推迟其他任务；这是框架原则，不是本项目的 CPU 占比证据。
[Drogon threading model](https://github.com/drogonframework/drogon/wiki/ENG-FAQ-1-Understanding-drogon-threading-model)。

## Redis timeout 与 outcome 语义

当前 non-fast seat_holds client 配置 2 connections、0.4s timeout；构造函数创建 RedisLoop 池。
`execCommandAsyncWithTimeout()` 为每次请求在 `loops_.getNextLoop()` 选择的 loop 上建立
TaskTimeoutFlag；这不保证与该命令所选 connection 是同一个 loop，但都属于该客户端的 RedisLoop 池。
`runAfter()` 不是独立实时看门狗，loop 正在执行长 callback 时计时器也可能延迟。
正常 reply/error wrapper 和 timer 都调用 `done()`，用 `isDone_.exchange(true)` 争夺一次性完成权。
所以先执行的 callback 获胜，并非 wall clock 达到 400ms 时强制中断正在执行的任务。
timeout 会尝试移除尚未发出的 buffered task；已经发出的命令不能据此从 Redis 撤销。
迟到 reply 仍由连接消费、弹出 callback 队列，但 wrapper 看到已完成标志就返回，不再次进入业务完成回调。
在迟到 reply 被消费前，相关 callback 捕获仍可能保留对象；本轮未将其量化为 live-object leak。
[RedisClientImpl.cc](https://github.com/drogonframework/drogon/blob/4c5430757ea5451a7c38fbbef4b4bef7dbb47f2f/nosql_lib/redis/src/RedisClientImpl.cc#L381)、
[TaskTimeoutFlag.cc](https://github.com/drogonframework/drogon/blob/4c5430757ea5451a7c38fbbef4b4bef7dbb47f2f/lib/src/TaskTimeoutFlag.cc)。

新指标 `ticketing_seat_map_redis_lookup_total{outcome}` 只接受四个固定枚举。
success 指 reply 及 owner 数组解析成功；timeout 根据 `RedisException::code()==kTimeout` 判断，
不是匹配错误文本；error 是其余 Redis exception/同步提交异常；parse_error 是 reply/owner 解码异常，
并不特指 JSON 文法错误。下游 completion 抛异常不重复记成 parse_error；原 fallback 边界未变。
空 seat list 不提交 Redis，也不计一次 lookup。普通配置未开启 metrics 时仍为空操作。

Redis CLIENT LIST 的 omem 是输出缓冲内存、oll 是输出列表长度；客户端消费跟不上生成输出时会增长，
但单凭它们不能断言 Redis server CPU 是瓶颈。本轮保存连接原始字段，空 name 不伪造名字，
不把 connection id 放进 Prometheus label。
[CLIENT LIST](https://redis.io/docs/latest/commands/client-list/)、
[Redis client handling](https://redis.io/docs/latest/develop/reference/clients/)。

## 外部设计参考（不是本项目已实施架构）

k6 v2.2.0 的 Go HTTP transport 设置 `DisableCompression: true`，不会自动替请求协商 gzip；
本轮显式设置 Accept-Encoding。`data_received` 是接收数据计数，不能直接等同解压后的 JSON 大小；
本轮同时记录 wire body probe、Content-Encoding 和 k6 数据，以实测区分。
[固定 k6 runner](https://github.com/grafana/k6/blob/v2.2.0/internal/js/runner.go#L188)、
[k6 metrics](https://grafana.com/docs/k6/latest/using-k6/metrics/reference/)。

Ticketmaster Discovery 提供 static seatmap URL，Partner Availability 提供可用性信息；
pretix 分别公开 seating plan layout 和具体 event/subevent seat 资源；
Eventbrite API 分列 Seat Map 与 Inventory Tiers。
这些支持“静态布局与动态库存分开思考”的后续候选，不证明其内部线程实现，也不构成本项目容量承诺。
核对来源：[Ticketmaster Discovery](https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/)、
[Availability](https://developer.ticketmaster.com/products-and-docs/apis/partner/availability/)、
[pretix plans](https://docs.pretix.eu/dev/api/resources/seatingplans.html)、
[pretix seats](https://docs.pretix.eu/dev/api/resources/seats.html)、
[Eventbrite API](https://www.eventbrite.com/platform/new/api)。
Eventbrite 直接打开曾遇 429，本轮通过该官方页面的搜索抓取重新核对资源说明，未用第三方容量文章替代。

## 校准运行与 Redis outcome

原始日志、HTTP/k6 summary、SQL、CLIENT LIST 和 samples 均在 `performance/results/<runId>/`；
已脱敏可版本管理数值见同目录 `calibration-measurements.json`。全部 7 个 run 的
正式库存前后都是 AVAILABLE=5000，数据库 verifier 14/14、dropped=0、system_error=0、unexpected=0。
这里 HTTP read 的通用 `business_success` counter **只代表 HTTP 读检查成功，不代表临时占座展示准确**，
90% 高载的展示校验并未通过；必须同时读取 display counters。

| runId | rate / 时长 / density / encoding | success | timeout | error | parse_error | owner_parse |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 20260906T110720Z-seat-calibration-60-0-identity-983628c3 | 60/s / 15s / 0% / identity | 323 | 579 | 0 | 0 | 323 |
| 20260906T110834Z-seat-calibration-60-0-identity-df26f59f | 60/s / 30s / 0% / identity | 179 | 1623 | 0 | 0 | 179 |
| 20260906T111249Z-seat-calibration-10-90-identity-88b39af2 | 10/s / 15s / 90% / identity | 152 | 0 | 0 | 0 | 152 |
| 20260906T111405Z-seat-calibration-60-90-identity-2da8d065 | 60/s / 15s / 90% / identity | 190 | 712 | 0 | 0 | 190 |
| 20260906T111604Z-seat-calibration-30-0-identity-d46b9975 | 30/s / 15s / 0% / identity | 452 | 0 | 0 | 0 | 452 |
| 20260906T111647Z-seat-calibration-30-0-gzip-fe89c611 | 30/s / 15s / 0% / gzip | 452 | 0 | 0 | 0 | 452 |
| 20260906T111735Z-seat-calibration-60-0-gzip-96ad0591 | 60/s / 15s / 0% / gzip | 201 | 700 | 0 | 0 | 201 |

累计 success=1949、timeout=3614、error=0、parse_error=0。每个 run 的 success 与 owner_parse samples 相等，
四种 outcome 总和与 lookup、SQL calls 和 k6 http_reqs 完全相等。
error/parse_error=0 是这组压力实验的观测，不代表已经通过人为 generic-error/解析故障注入。
旧统计没有 outcome，不能事后把旧 lookup-owner_parse 差额全部断言成 timeout。

## 5k60 Before / After

下列全部为 0% hold、无 gzip；分位数按 p50 / p95 / p99，单位 ms。

| 指标 | 旧 15s | 校准 15s | 旧 30s | 校准 30s |
| --- | --- | --- | --- | --- |
| HTTP | 501.11 / 655.28 / 678.51 | 565.48 / 931.74 / 999.69 | 593.94 / 1306.14 / 1429.67 | 2973.87 / 4445.51 / 4556.98 |
| Redis lookup | 403.34 / 930.96 / 986.19 | 515.05 / 951.51 / 990.30 | 577.61 / 2096.57 / 2419.31 | 2706.21 / 4770.62 / 4954.12 |
| owner_parse samples | 402 | 323 | 708 | 179 |
| JSON build | 4.86 / 23.12 / 24.62 | 10.45 / 23.57 / 24.74 | 10.73 / 23.57 / 24.71 | 16.10 / 24.42 / 36.75 |
| response_create | 3.81 / 4.98 / 9.83 | 3.87 / 7.56 / 12.70 | 3.88 / 7.72 / 13.25 | 4.29 / 9.58 / 19.37 |
| DB fetch/materialize | 7.52 / 9.79 / 9.99 | 7.52 / 9.79 / 9.99 | 7.52 / 9.78 / 9.98 | 7.88 / 19.36 / 23.92 |
| PG server mean | 7.45 | 7.05 | 7.45 | 7.79 |
| cached in-flight peak | 38 | 48 | 77 | 241 |
| Backend CPU cores（30s rate max） | 1.87 | 1.78 | 2.91 | 2.89 |
| RSS peak MiB | 212.67 | 237.57 | 385.92 | 963.94 |
| direct working set peak MiB | 214.39 | 237.93 | 397.34 | 965.43 |
| Redis client max omem / oll | 1220816 / 94 | 3580432 / 278 | 3919000 / 305 | 2734048 / 212 |
| Redis used_memory peak bytes | 4745464 | 9506632 | 7574728 | 7662024 |

校准后仍属于情况 B：长尾没有消失，Redis 输出缓冲仍有积压。结果支持生产等价路径的
Redis client/callback loop 排队候选，而不是“上轮提前 getBody 才造出了整个瓶颈”。
本轮数值甚至更差，但单次、不同 allocator 热状态、同机环境和采样开销等因素没有被完全控制，
不能将差值因果归为删除 getBody，也不能将单个函数认定为已经证实的全部根因。
本轮第一条 run 刚重建进程，旧 5k run 则此前已经跑过 1k/2.5k 等矩阵，绝对 RSS 不可当成严格随机 A/B。

calibration 汇总按实际容器 ID `1471db478e00105186160bf96fb826daa6dd37f5dd64dbec532922d22e24bba7` 过滤 cAdvisor；
前两个 run 的原始 working-set 查询各含一个旧容器残留序列，保留原始证据并剔除它，不相加。
实验容器 StartedAt=2026-09-06T11:07:14.038777313Z、RestartCount=0；
负载和 Drain 全程没有重启，之后为普通配置回归才重建 Backend。

## 90% Temporary Hold 展示正确性

| 控制点 | 压力响应数 | 预期 HELD / AVAILABLE / SOLD | 完全符合 | fallback 展示退化 | 其他异常状态 |
| --- | ---: | --- | ---: | ---: | ---: |
| 10/s、15s | 151 | 4500 / 500 / 0 | 151 | 0 | 0 |
| 60/s、15s | 901 | 4500 / 500 / 0 | 189 | 712 | 0 |

高载退化比例 79.02%。712 次 timeout 对应 712 个完整 formal fallback 响应：
HELD=0、AVAILABLE=5000、SOLD=0；不是只看 HTTP 200 后声称“正确”。
高载 min/max HELD=0/4500、AVAILABLE=500/5000，SOLD 始终 0。
正式数据库在前后均是 5000 AVAILABLE，没有制造 Reservation/Order；该只读矩阵不能证明整个
Reservation/Confirm 并发正确性，更不能从展示退化推断超卖。正式裁决路径另由现有集成测试覆盖。
匿名 fixture 未携带 own checkout；own/other 语义由 Seat Hold integration 单独验证。

高载客户端 max omem=20027488 B、oll=1028，
Redis used_memory peak=43046984 B，说明高密度回复积压更加显著。
发现退化后不继续提高密度场景速率；仅按要求执行独立 0% gzip 对照。没有调整 fallback 设计。

## gzip A/B 与真实浏览器

0% hold 的 out-of-load bytes probe：identity=822421 B、gzip=44086 B，Content-Length 与实读一致，
解压后内容完全相同（5000 seats），压缩比约 18.65:1。
90% probe 的长度因 HELD 字符串变化而不同，详见 artifact，不能把 0% bytes 套用到 90%。

| 条件 | HTTP p50/p95/p99 ms | waiting p50/p95/p99 ms | receiving p50/p95/p99 ms | data_received B |
| --- | --- | --- | --- | ---: |
| 30/s identity | 49.20 / 56.95 / 65.82 | 30.10 / 35.74 / 46.73 | 18.65 / 22.13 / 23.39 | 371802092 |
| 30/s gzip | 33.71 / 38.37 / 52.26 | 33.57 / 38.17 / 52.09 | 0.07 / 0.14 / 0.20 | 20005068 |
| 60/s identity | 565.48 / 931.74 / 999.69 | 546.59 / 931.51 / 999.48 | 19.03 / 23.34 / 33.13 | 741959042 |
| 60/s gzip | 993.06 / 1907.21 / 2048.15 | 992.84 / 1907.08 / 2047.97 | 0.09 / 0.16 / 0.21 | 39877359 |

| 条件 | Backend CPU cores | direct WS peak MiB | Redis lookup p50/p95/p99 ms | omem / oll | in-flight peak | k6 CPU cores / WS MiB |
| --- | ---: | ---: | --- | --- | ---: | --- |
| 30/s identity | 0.93 | 462.50 | 3.75 / 4.88 / 4.98 | 0 / 0 | 1 | 0.03 / 242.96 |
| 30/s gzip | 0.99 | 438.85 | 3.77 / 4.91 / 6.77 | 0 / 0 | 2 | 0.04 / 246.68 |
| 60/s identity | 1.78 | 237.93 | 515.05 / 951.51 / 990.30 | 3580432 / 278 | 48 | 0.06 / 279.29 |
| 60/s gzip | 2.03 | 496.83 | 949.05 / 2342.48 / 2468.50 | 938688 / 72 | 91 | 0.10 / 284.87 |

30/s 下 receiving 明显下降，HTTP 改善，Redis lookup 仍为毫秒级。
60/s gzip receiving 同样很低，但 lookup 仍长（201 success、700 timeout），HTTP 并未改善。
不能说“gzip 加速 Redis”；压缩本身也在框架交接前执行，可能增加 callback 所在线程计算，
但本轮没有 CPU 栈，不能把 gzip 点变慢全部归因于压缩计算。
60/s identity 复用首个已测 run，两个点不相邻且内存热状态不同；两条 run 分别 902/901 HTTP 请求，
比较 data_received 时需注意这个数量差异。没有额外升压寻找更好看的容量结论。
k6 CPU 观测未接近机器总核数，没有 dropped，未观察到 generator-limited；
90% 全量 body 校验的 k6 CPU 高载约 1.08 cores，仍应作为测量开销单独说明。

真实 Chromium 153.0.8010.12（未设置请求头）请求 5000 seats：
Accept-Encoding=`gzip, deflate, br, zstd`，Content-Encoding=`gzip`，
HTTP 200、Content-Length=44086，JSON 可解析且 seatCount=5000。
`probe_seat_map_browser.mjs` 检查浏览器直接 Backend 请求；页面购票功能另由真实模式 Playwright 覆盖。
因此旧 k6 默认无压缩与浏览器常见 gzip 条件不同，后续 baseline 应明确 encoding，
但不能跳过 Redis 展示退化或把网络改善当作正式线程优化。

## Drain / Recovery

参数为 5k、0%、identity、60/s、30s，k6 完成后持续观察至少 180 秒，无 restart、无清理 allocator。

| 指标 | 旧 before / peak / after | 校准 before / peak / after |
| --- | --- | --- |
| RSS MiB | 212.67 / 385.92 / 321.22 | 237.45 / 963.94 / 586.05 |
| direct working set MiB | 208.40 / 397.34 / 316.67 | 231.73 / 965.43 / 581.00 |
| Redis used_memory B | 3131440 / 7574728 / 3131440 | 3315248 / 7662024 / 3315712 |

最后一次观测到非零 in-flight 后，首次观测 0 的时间为
2026-09-06T11:09:21.243Z；
这不是精确归零时刻。末尾 2026-09-06T11:12:27.056Z 的
in-flight=0、sumClientOmem=0，PG connections 最大 6。
取样为串行 HTTP/Docker/SQL 快照，并非同时采样；完整时序在 JSON 中。
分类仍是 **B：部分恢复**。高水位之后部分释放，但未回到本轮 before；不能宣称无 leak，也未证实 live-object leak。
后续较低负载的 RSS 又有所下降，也提示不能只凭静止 RSS 给对象泄漏定性。

## 结论、profile 与下一轮候选（未实施）

1. **第一候选：Redis callback 快速返回 / 后处理工作迁移受控实验。**
   去掉早读后仍有 lookup 长尾、真实 timeout、output buffer 和 90% 展示退化。
   应另行评审线程/对象所有权和队列界限；本轮未改变 queueInLoop、HTTP loop、Redis loop 或 pool。
2. **第二候选：Static Layout / Dynamic Availability split。**
   大量静态字段重复传输与构造仍存在；gzip 不替代数据面拆分，但当前线程排队证据更直接。
3. **gzip 定位：真实压测默认网络条件校准。** 明确与 identity 的差别，不作为已经完成的瓶颈修复。
4. **heap/allocator/lifecycle 诊断优先级提升。** Drain 仍为 B，应在宣称内存问题已解决前补取证。

本轮没有开启 CPU profile 或 heap/allocator profiler，也没有 micro-benchmark。
虽然已达到“允许有限 profile”的触发条件，但现有证据足以确定下一轮实验优先级；
暂不通过重型工具改变运行行为。没有函数级 CPU 占比、retained arena 数量或 live-object 泄漏证据，
这些都明确留为后续验证事项，而不是已证明的机制。本轮到此停止，不进入真正优化。

## 真实回归、异常记录与交付状态

| 验证 | 实际结果 | 本地原始证据 |
| --- | --- | --- |
| Docker / CMake / C++ / link | 成功，GNU 13.3、C++20、Release | performance/results/calibration-build.log |
| Dockerfile CTest full | 20/20 | 同上 |
| Performance Python | 77/77（包含校准脚本与证据契约） | `python -m unittest discover -s performance/tests -p 'test_*.py'` 实际输出 |
| Seat Hold integration | 9/9，64.410s，含 own/other、Redis down/restart | performance/results/calibration-seat_hold_integration_test.py.log |
| Checkout integration | 6/6，19.541s | performance/results/calibration-checkout_session_http_integration_test.py.log |
| Auth integration | 7/7，59.201s | performance/results/calibration-phase9_auth_http_integration_test.py.log |
| Database verifier | 每个压力点及最终均 14/14、0 violations | 各 run 的 verifier.txt；performance/results/calibration-final-database.log |
| Observability verifier | PASS、0 failed checks | performance/results/calibration-final-observability.log |
| Playwright Chromium | 4/4，22.5s | performance/results/calibration-playwright.log |
| 默认浏览器网络条件 | HTTP 200、gzip、5000 seats | performance/results/calibration-browser.log |
| 最终 health | HTTP 200，`{"database":"up","status":"ok"}` | 最终真实 curl 输出 |

Seat Hold / Checkout / Auth 在普通 `config.docker.json` 下回归，不把仅诊断配置成功当成普通配置验证。
Playwright 使用现有 forced SUCCESS 测试参数；结束后已恢复默认 Performance 配置和非强制支付结果。
Performance 数据恢复到 smoke，服务仍运行，Backend/PostgreSQL/Redis healthy；镜像和全部卷保留。
未操作 `backend_ticketing_postgres_data`，没有 volume rm/prune/down -v，未修改 frontend。

本轮遇到的非业务异常：

- 沙箱首次 Docker 只读请求返回 named-pipe permission denied；通过受批准的 Docker 执行权限继续，未绕过访问控制。
- 第一次构建在测试尚未同步完成时抓取了旧测试快照：C++ 已编译链接，但 CTest 19 仍期待旧
  `ticketing_seat_map_response_bytes`，20 项中 1 项失败。同步测试至 outcome counter 后重新完整构建，20/20；
  未跳过 CTest、未修改 Dockerfile 或业务实现以规避失败。
- 临时分析命令第一次按 Windows GBK 读取含中文路径的 JSON，报 UnicodeDecodeError；改为显式 UTF-8 后成功。
  提交的汇总脚本始终显式按 UTF-8 读取；未修改实测数据。
- 外部网页部分直接抓取失败/429，保留限制，框架行为优先由实际镜像内固定 commit 源码核对。

复现实测（只针对隔离 Performance 栈；会替换 perf fixture，不适用于开发库）：

```powershell
docker compose -f performance/docker-compose.performance.yml build backend
docker compose -f performance/docker-compose.performance.yml up -d --wait backend
python performance/scripts/calibrate_seat_map.py --rate 60 --prepare
python performance/scripts/calibrate_seat_map.py --rate 60 --duration 30 --drain-seconds 180
python performance/scripts/calibrate_seat_map.py --rate 10 --density 90
python performance/scripts/calibrate_seat_map.py --rate 60 --density 90
python performance/scripts/calibrate_seat_map.py --rate 30 --encoding identity
python performance/scripts/calibrate_seat_map.py --rate 30 --encoding gzip
python performance/scripts/calibrate_seat_map.py --rate 60 --encoding gzip
node performance/scripts/probe_seat_map_browser.mjs
```

每条命令完成后先检查停止条件再决定下一条，不是一键自动扩压计划。
汇总脚本要求显式提供该组实验真实 Backend container ID，过滤旧 cAdvisor 序列；
旧容器即使同名也不会叠加到当前进程。
所有运行均使用本轮未提交的已验证源码快照（manifest 的 gitHead 是起点，不冒称运行的是后续 commit）。
交付采用诊断代码和证据两个独立提交，不 amend、rebase、reset 或 push。
诊断代码提交：`a04a436c761b475adcd052802b3ccb90b5f0bd54 perf: calibrate seat map diagnostics`。
提交前 `git diff --check`、`git diff --cached --check` 和该代码提交的 `git log -1 -p --check` 均通过。
