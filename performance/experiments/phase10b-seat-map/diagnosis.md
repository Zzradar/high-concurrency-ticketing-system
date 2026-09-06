# Phase10B-3：Seat Map 大响应路径诊断

## 结论与范围

本轮只做诊断、观测与对照，**未进入真正 B-3 优化，未 push**。未修改接口、库存/支付逻辑、SQL、索引、连接池、压缩配置或前端。

最明显的长尾位置是 **Redis lookup 的客户端排队/回调往返段**，不能称为 Redis server execution。源码显示其成功回调继续同步执行 overlay、JSON 构造、Json::Value 拷贝和序列化，之后才交回 HTTP EventLoop；这提供了“Redis 客户端消费线程上的大响应计算挤压读回复”的强解释。尚无 CPU stack/heap profile，不能给这条解释分配精确 CPU 占比，也不能排除对象销毁/调度成本。

Drain 是 **B：部分恢复**，不是“证明无泄漏”，也不是“已证实泄漏”。在展开大规模 API 重构前，优先补 allocator/heap/生命周期取证。Layout/Availability split 是数据面首要候选，但不是已批准实施方案。

## 1. 起点、环境与 B-2 事实

起点 main，工作区 clean，HEAD `0f5b26cb1ae31b0f9f579cdf9efe73f961cbc835`；origin/main `2aec8a5ba492e5cdb64f91e33391f5c2c634f7e7`，ahead 9。未改写 B-1/B-2 提交。

B-2 报告记录 5k-seat 100/s 短测约 5.3s p50 / 9.9s p95；Mixed Read 100/100/60 长窗口中止时 Backend working set 约 9 GiB、Redis ordinary clients 约 591 MiB、Seat SQL mean 7.69ms。这些是上轮事实，不冒充本轮测量。

本轮使用同一台 Windows / Docker Desktop Linux VM（16 logical CPU、约 15.41 GiB 内存），同机 k6 2.2.0、单 Performance Backend、PostgreSQL 16、Redis 7.4。固定项目 `ticketing-phase10a`，HTTP 18080。普通开发项目没有被操作，未删除任何卷。完整环境快照：`performance/results/phase10b3-validation/environment.json`。

诊断开始至 Drain 结束 Backend 容器 ID `2432a0841f12a2469c49b2432d31167bdf419f05845bb6e386f5c34bf9bd7a4f`，StartedAt `2026-09-06T09:58:57.27323585Z`，RestartCount 0。之后为了普通配置回归才重建 Performance Backend，不把重启降内存当 Drain 恢复证据。

## 2. 当前真实调用链

```text
SeatController::listSessionSeats
  → 可选 authenticate + findByIdForUser（仅带 checkout 参数和 Cookie 时）
  → listWithOwnCheckout
  → SeatService::listSessionSeats
  → SeatRepository::listBySessionId
  → execSqlAsync：session_seats JOIN seats，按 row_no/seat_no/id 排序
  → 结果回调：SeatRow → Seat DTO → seatIds
  → SeatHoldService::readOwners
  → JSON 编码完整 keys → seat_holds Redis EVAL / MGET
  → RedisConnection::handleResult 直接调用结果 callback
  → owner parse → AVAILABLE 的临时 Hold overlay
  → Seat::toJson / Json::Value append
  → newHttpJsonResponse(body)：lvalue Json::Value 拷贝
  → lazy JSON serialization（诊断模式提前显式触发一次）
  → HTTP callback / PreSending / getCompressedResponse
  → conn EventLoop queueInLoop → sendResponses
```

匿名不带自己的 checkout 上下文；授权归属校验成功时才传 own checkout ID。overlay 仅覆盖 formal AVAILABLE，自己的 Hold 不遮蔽、其他人的 Hold 遮蔽，Redis 不可用时仍返回 PostgreSQL formal 状态，均保持既有语义。

`readOwners` 成功与失败 callback 均调用 Service completion，继续走响应构造。Drogon Redis 结果 callback 在 RedisConnection EventLoop 内同步执行，不是自动转移到 HTTP loop。当前超时配置 0.4s，但 EventLoop 忙时 timeout callback 自身也可能延后，不能把该值当严格 wall-clock 上界。

实际构建的 Drogon commit 为 `4c5430757ea5451a7c38fbbef4b4bef7dbb47f2f`（项目指定 v1.9.13），构建树无修改。取证源：
`lib/src/HttpServer.cc:773`、`:1241`；
`lib/src/HttpResponseImpl.cc:82`、`:117`、`:1175`；
`nosql_lib/redis/src/RedisConnection.cc:335`；
`lib/inc/drogon/HttpResponse.h:526`、`:547`。
这比按最新版框架说明猜调用线程更可靠。

## 3. Performance-only 指标及边界

新增固定 12-stage histogram `ticketing_seat_map_stage_duration_seconds{stage}`、未压缩 bytes histogram `ticketing_seat_map_response_bytes`、Seat Map gauge `ticketing_seat_map_requests_in_flight`。复用既有规范化 route HTTP counter 作为 response count，HTTP histogram 作为应用总耗时。无任何业务 ID / thread ID label。

| stage | 实际边界 |
|---|---|
| db_fetch_and_materialize | execSqlAsync 发起前到结果 callback 入口；含 pool 等待、传输/libpq result materialization，不等于 PG server SQL |
| row_build | Result 字段读取与 SeatRow vector 构造 |
| dto_build | SeatRow 转 Seat DTO vector |
| seat_ids_build | Seat DTO 提取完整 seat ID 列表 |
| redis_input_build | keysFor、Json::Value key array、输入 JSON writeString |
| redis_lookup | execCommandAsync 前到成功/错误 callback 入口；含队列、服务端、传输和投递 |
| owner_parse | asArray、nil/owner 字符串解析；只在成功解析路径采样 |
| overlay | formal + temporary overlay 循环；降级时也采样但无 owner 数据 |
| json_build | Seat::toJson 与 array append |
| response_create | newHttpJsonResponse(body)，含 lvalue JSON tree copy |
| json_serialize | response->getBody() 触发 Drogon 首次序列化 |
| response_callback | 调用 HTTP callback 到其返回；非 socket flush |

计时开启通过 Performance 配置注册并发布固定 histogram handles；普通配置不注册，getBody 的提前求值也不执行。普通路径仍有 no-op 指标方法调用，不声称零指令开销。未加 micro-benchmark，因为真实 HTTP 路径已能直接测序列化。

重要局限：

- 提前 getBody 仍在同一个 callback 线程，Drogon 正常也在 getCompressedResponse → shouldBeCompressed 中求 body；但本轮 PreSending 总耗时因而**包括序列化**，与 B-2 未插桩应用 histogram 的边界不同。k6 HTTP 指标可对照，不能盲比应用 histogram。
- 阶段分位数来自本轮前后 histogram bucket delta 的插值，不是逐请求 tracing，不能相加；粗桶可能让估计 p95 高于真实样本 max。原始 buckets 保存在 ignored artifacts。
- HTTP 总耗时在 PreSending 结束，不含完整 socket flush；Seat Map in-flight 也不跟踪所有底层 Redis 队列残留或 socket 未发送字节。客户端提前断连时框架可能在 PreSending 前 return，这套 gauge 也不是独立于框架的绝对活跃对象计数。本轮短测最终归零。
- 采样约每 2.2s（命令开销 + 1s sleep），不是精确 1Hz；峰值只是采样峰值。**PromExporter.cc:32 对 /metrics 设置 5 秒缓存**，不同 HTTP loop 的缓存还可能不同龄，因此 gauge/counter/histogram 不是即时全局快照，不能精确对齐另行读取的 Redis/RSS。PG locks 是结束快照，不证明全程每一瞬间都无锁等待。
- 2.5k 10/s 的 histogram samples / SQL calls 实测为 **151 / 153**，其余九轮相同。这与缓存响应导致前后快照窗口偏移相容；不把 151 改成 153，也不由此认定丢失请求。本轮分位数只能解释为该观测窗口近似分布，不声称逐请求精确配对。后续若要求严格窗口，需处理 exporter 缓存或在静默期等待缓存过期，不能仅添加 query string 假定绕过 handler cache。
- 每轮阶段/SQL 样本包含 runner fixture HTTP 检查及 k6 setup；k6 HTTP 统计含 setup，不含外部 gzip 探针；gzip 探针在 metrics-before 前。矩阵只做每格一次 15s，不能宣称长期稳定容量。

## 4. Seat Count Scaling Matrix

仅复制 scale-100k profile 的 name、seatsPerRow：10 行 × 100/250/500，实际 SQL 数据量分别为 1k/2.5k/5k 座位。其他维度保持 100k registered users、20k active sessions、2 events、20 sessions 和三个价格区。每次生成后立即 verifier 14/14，离线 Session /auth/me 200。

每轮 700 preallocated VU，默认 k6 编码，0% temporary hold fixture，15s fixed arrival；未添加 API limit。所有 run 0 dropped、0 unexpected、verifier 14/14。5k 60/s 出现积压后未继续 100/s；只以相同速率执行一次有限 Drain。

| seats | req/s / duration | HTTP p50 / p95 / p99 ms | sampled in-flight peak | PG SQL mean ms | iterations / dropped | run ID |
|---|---|---|---|---|---|---|
| 1000 | 10 / 15s | 8.73 / 10.43 / 12.02 | 1 | 2.01 | 150 / 0 | `20260906T100121Z-seat-map-read-steady-d267` |
| 1000 | 30 / 15s | 8.91 / 10.73 / 12.21 | 1 | 1.63 | 451 / 0 | `20260906T100327Z-seat-map-read-steady-4ea8` |
| 1000 | 60 / 15s | 8.58 / 9.82 / 10.34 | 1 | 1.47 | 900 / 0 | `20260906T100718Z-seat-map-read-steady-0caa` |
| 2500 | 10 / 15s | 22.93 / 25.41 / 26.70 | 1 | 4.20 | 151 / 0 | `20260906T100822Z-seat-map-read-steady-2374` |
| 2500 | 30 / 15s | 22.00 / 24.68 / 28.29 | 1 | 3.70 | 450 / 0 | `20260906T100938Z-seat-map-read-steady-a365` |
| 2500 | 60 / 15s | 21.65 / 25.11 / 28.34 | 2 | 3.55 | 901 / 0 | `20260906T101026Z-seat-map-read-steady-1936` |
| 5000 | 10 / 15s | 48.65 / 52.51 / 54.40 | 1 | 8.24 | 150 / 0 | `20260906T101142Z-seat-map-read-steady-5c9c` |
| 5000 | 30 / 15s | 48.87 / 56.07 / 66.55 | 1 | 7.19 | 450 / 0 | `20260906T101229Z-seat-map-read-steady-0449` |
| 5000 | 60 / 15s | 501.11 / 655.28 / 678.51 | 38 | 7.45 | 901 / 0 | `20260906T101328Z-seat-map-read-steady-5a29` |
| 5000 | 60 / 30s | 593.94 / 1306.14 / 1429.67 | 77 | 7.45 | 1800 / 0 | `20260906T101428Z-seat-map-read-steady-6cca` |

完整每格 12 个 stage 的 p50/p95/p99、HTTP waiting/receiving、SQL、response bytes 和 scoped resources 在同目录 [measurements.json](measurements.json)；它是去掉敏感内容的真实 artifact 摘录，不是模拟数据。

以下为 1k/2.5k/5k 低载及 5k 积压对照；所有值为 histogram 估计 ms：

| stage | 1k 10/s | 2.5k 10/s | 5k 10/s | 5k 60/s 15s | 5k 60/s 30s Drain |
|---|---|---|---|---|---|
| db_fetch_and_materialize | 2.08 / 4.59 / 4.92 | 4.11 / 8.89 / 9.78 | 7.57 / 9.88 / 19.30 | 7.52 / 9.79 / 9.99 | 7.52 / 9.78 / 9.98 |
| dto_build | 0.04 / 0.09 / 0.14 | 0.17 / 0.24 / 0.25 | 0.18 / 0.36 / 0.47 | 0.19 / 0.46 / 0.80 | 0.19 / 0.50 / 0.91 |
| json_build | 0.91 / 2.31 / 2.46 | 2.03 / 4.54 / 4.91 | 3.92 / 7.89 / 9.58 | 4.86 / 23.12 / 24.62 | 10.73 / 23.57 / 24.71 |
| json_serialize | 0.76 / 1.08 / 2.21 | 1.92 / 4.33 / 4.87 | 7.50 / 9.75 / 9.95 | 7.49 / 9.75 / 9.96 | 7.49 / 9.75 / 9.95 |
| overlay | 0.01 / 0.03 / 0.05 | 0.03 / 0.05 / 0.06 | 0.08 / 0.10 / 0.22 | 0.01 / 0.10 / 0.16 | 0.01 / 0.10 / 0.19 |
| owner_parse | 0.02 / 0.02 / 0.02 | 0.04 / 0.08 / 0.10 | 0.08 / 0.11 / 0.22 | 0.07 / 0.10 / 0.22 | 0.07 / 0.10 / 0.20 |
| redis_input_build | 0.38 / 0.62 / 0.92 | 0.76 / 0.98 / 1.75 | 1.75 / 2.43 / 2.48 | 1.75 / 2.43 / 2.49 | 1.75 / 2.43 / 2.49 |
| redis_lookup | 1.57 / 2.41 / 2.48 | 1.95 / 4.68 / 8.11 | 3.78 / 4.92 / 7.47 | 403.34 / 930.96 / 986.19 | 577.61 / 2096.57 / 2419.31 |
| response_callback | 0.03 / 0.05 / 0.06 | 0.04 / 0.05 / 0.07 | 0.04 / 0.05 / 0.14 | 0.03 / 0.05 / 0.08 | 0.04 / 0.05 / 0.09 |
| response_create | 0.75 / 0.97 / 0.99 | 1.76 / 2.44 / 3.11 | 3.76 / 4.89 / 4.99 | 3.81 / 4.98 / 9.83 | 3.88 / 7.72 / 13.25 |
| row_build | 0.39 / 0.68 / 0.94 | 0.81 / 2.12 / 2.42 | 1.81 / 3.42 / 4.68 | 1.75 / 2.43 / 2.49 | 1.75 / 2.43 / 2.49 |
| seat_ids_build | 0.02 / 0.04 / 0.05 | 0.04 / 0.09 / 0.10 | 0.08 / 0.22 / 0.24 | 0.08 / 0.20 / 0.25 | 0.08 / 0.22 / 0.25 |

PG server mean 在 5k 高载约 7.45ms，Backend db_fetch p50 约 7.52ms、p95 约 9.78ms，没有出现 100ms+ 的 DB fetch 放大。因此本轮不能把长尾归因于整个 DB read path；静态重复取数仍有成本，但不是此次几百毫秒等待的主要来源。

5k 60/s 15s 的 redis_lookup 903 samples，而 owner_parse 402；Drain 分别 1802 / 708。501 / 1094 个 lookup 没有进入成功 owner parse。源码存在错误/解析异常降级路径；没有 outcome metric 或逐次错误分类，不能把这个差数全部武断叫“Redis timeout 次数”。它证明不能把所有 HTTP 200 解释为 temporary hold 读取全成功。0%-hold fixture 下回退不改变本轮 payload，但不能外推 90%-hold 显示结果。

## 5. 资源与 Redis 客户端

CPU 为采样到的 30s rate 最大值（单位核，短测被平均窗口摊薄），内存为 cAdvisor working set 采样最大值 MiB；不是瞬时 CPU 峰值。按本轮 k6 shortRunToken 对应容器名查询，不能累加仍留在 cAdvisor 的旧 one-off k6 series。原有 service 汇总文件保留供复核，报告使用 `scoped-resources.json`。Backend 前两格仍可见旧同名容器的内存序列，取独立 series 最大值、未求和；当前样本高于旧小容器。后续均单 series。

| seats / rate / seconds | Backend cores / MiB | Redis cores / MiB | k6 cores / MiB | max client omem B / oll | PG connections peak |
|---|---|---|---|---|---|
| 1000 / 10 / 15s | 0.06 / 57.64 | 0.02 / 21.29 | 0.01 / 224.18 | 0 / 0 | 7 |
| 1000 / 30 / 15s | 0.15 / 64.57 | 0.03 / 20.11 | 0.03 / 233.64 | 0 / 0 | 6 |
| 1000 / 60 / 15s | 0.29 / 63.91 | 0.04 / 19.88 | 0.05 / 259.66 | 0 / 0 | 6 |
| 2500 / 10 / 15s | 0.15 / 69.87 | 0.03 / 22.09 | 0.01 / 215.09 | 0 / 0 | 6 |
| 2500 / 30 / 15s | 0.40 / 75.06 | 0.04 / 22.69 | 0.04 / 231.04 | 0 / 0 | 6 |
| 2500 / 60 / 15s | 0.80 / 74.16 | 0.06 / 21.89 | 0.05 / 255.16 | 0 / 0 | 6 |
| 5000 / 10 / 15s | 0.31 / 86.26 | 0.04 / 24.14 | 0.01 / 227.25 | 0 / 0 | 6 |
| 5000 / 30 / 15s | 0.91 / 90.68 | 0.06 / 24.11 | 0.07 / 236.17 | 0 / 0 | 6 |
| 5000 / 60 / 15s | 1.87 / 214.31 | 0.11 / 26.36 | 0.10 / 258.81 | 1220816 / 94 | 6 |
| 5000 / 60 / 30s | 2.91 / 384.05 | 0.16 / 30.61 | 0.10 / 259.22 | 3919000 / 305 | 7 |

Redis CLIENT LIST 保存全部实际字段：id/addr/name/cmd/omem/oll/obl/qbuf/qbuf-free/age/idle/flags，允许版本新增字段。诊断中两个 Backend `172.19.0.6` 连接持续执行 EVAL（id 28772、28773），另两条 GET/SET 对应 auth 路径。本轮没有并发写测试；结合 `seat_holds` 的唯一 readOwners EVAL 调用、固定两连接及客户端地址，可将此次大缓冲高可信度定位到 seat_holds EVAL 路径。**没有 client name，不能把此证据当作对 B-2 历史 591 MiB 客户端的唯一事后证明。**

Drain 最大记录：id 28772、addr `172.19.0.6:39466`、name 空、cmd eval、flags N、omem 3,919,000 B、oll 305、obl 0、qbuf 39,323、qbuf-free 353,883、idle 0。两个连接 omem 之和的采样峰值也是 3,919,000 B。15s 高载最大 omem 1,220,816 B、oll 94；其他矩阵点采样 omem/oll 为 0，不能解释成任何瞬间都为 0。

Redis server used_memory 在 Drain 从 3,131,440 B 到 7,574,728 B，再回到 3,131,440 B。这里用时序值，未拿 Redis 累计 used_memory_peak（包含 B-2 历史）冒充本轮峰值。

## 6. gzip 与传输字节

Drogon 默认 use_gzip=true、brotli=false；Performance config 没有覆盖。显式 Accept-Encoding: gzip 的真实 HTTP 响应都带 gzip，Content-Length 等于实际原始读取到的压缩 body 字节，Transfer-Encoding 缺省，解压后与 identity byte-for-byte 相等。

| seats | raw JSON B / identity Content-Length | gzip body B / gzip Content-Length |
|---|---|---|
| 1000 | 163621 | 6961 |
| 2500 | 410671 | 22773 |
| 5000 | 822421 | 44086 |

**当前 k6 2.2.0 默认 Seat Map 请求不接受 gzip。** 独立 probe 比较默认 headers 与显式 gzip，前者无 Content-Encoding、Content-Length=822421；后者 gzip、Content-Length=44086。两者解码 body 长度均 822421，不能用解码长度作线传输压缩量。k6 runner 的 DisableCompression=true 与项目没有显式 Accept-Encoding 一致。B-2 使用同一 workload/config，因此代码和当前实测支持 B-2 未协商压缩；未保存 B-2 逐包抓包，不冒充历史 packet capture。

曾用 --http-debug 看到请求转储显示 gzip，但响应没有 gzip；该显示与实际 probe 不一致，不能单靠 debug header 下结论，本报告以两个对照请求响应及 Transport 源码为准。

k6 data_received 是传输统计、含响应头等开销，不等同 body；5k 60/s 15s 为 741,959,042 B / 902 HTTP（每个 body 822,421 B），Drain 为 1,481,450,371 B / 1801 HTTP。没有根据压缩比猜 bytes；未测 TCP retransmission 总线字节或精确 socket flush。

本轮没有修改 Accept-Encoding workload 或 gzip/brotli 配置。额外 probe 只测协商，不声称“启用 gzip 后容量提升多少”。

## 7. Drain / Recovery：B（部分恢复）

参数：5k seats、0%-hold、60 req/s × 30s、700 VU，结束后额外观察 180s（从 runner 完成计时，实际新 arrival 更早停止），共 98 个约 2.2s 间隔样本。1800 iterations 全完成，0 dropped、0 unexpected。选择此前已出现积压的 60/s，不尝试更高 rate，不复刻 9 GiB。过程无重启、无内存清理、无 malloc_trim。

| 时点 | Seat Map in-flight | RSS MiB | working set MiB | Redis client omem |
|---|---|---|---|---|
| pre-test | 0 | 212.67 | 208.40 | 0 |
| sampled RSS peak，10:14:59.729 UTC | 77 | 385.92 | 此行与独立 WS 峰值不强行对齐 | 最高 3,919,000 B |
| 首个后续零值，10:15:01.945 UTC | 0 | 321.22 | 随后约 316–317 | 0 |
| 观察末尾，约 t=214s | 0 | 321.22 | 316.67 | 0 |

direct cgroup working set 采样最大 397.34 MiB，cAdvisor 较低频最大 384.05 MiB；二者不是同一时间采样，保留区别。最后一个显示 busy 的采样与首个显示 zero 相距 2.22s，但 exporter 5 秒缓存使它们不能界定真实归零的精确区间；这里只报告首次观察到零的墙钟时间，持续三分钟零值和完整 k6 completion 共同支持已经排空。98 点完整 timeline（含带缓存延迟的 completion counter、PG connections、Redis used_memory）已纳入 measurements.json。

RSS 明显从峰值下降约 65 MiB，但仍高于 pre-test 约 109 MiB，之后三分钟无进一步明显下降。因此分类 B，可能包含 allocator/framework retention 或真实 leak；本轮无 heap 活对象/分配调用栈，不能二选一。Redis output buffer 与 used_memory 已恢复，但并不能由此证明后端所有对象已销毁。

## 8. Output / backpressure 与瓶颈解释

低载 5k 的 k6 receive p50 约 17–18ms，传输 822kB 有可见成本。60/s 15s 的 receive p95 22.37ms，Drain receive p95 21.41ms，远小于 HTTP p95 655ms / 1306ms。应用 redis_lookup 长尾和 CLIENT LIST 消费积压同时出现，response_callback p95 约 0.05ms。**有明显 Redis-client output/backpressure evidence，但没有证据证明客户端 HTTP socket flush 是主导长尾。**

源码中的 JSON build、copy、serialize 在 Redis callback 线程连续执行；其局部时长并不会把“等待其他请求计算”归到 JSON stage，而会体现在后续请求 redis_lookup 等待中。对象析构、RedisResult/hiredis 解码、线程调度及内核缓冲均未单独计时，尚不能把余量全归 socket。

Drogon 有 newStreamResponse / newAsyncStreamResponse 能力，但当前控制器不用；当前代码也没有 per-response 最后一字节发送完成指标。没有修改框架核心或伪造 socket flush duration。

## 9. 官方资料与候选依据（2026-09-06 重新核对）

以下明确区分框架官方行为与外部设计参考；外部系统的资源划分不是本项目优化收益证明。

- Redis 官方 [client handling](https://redis.io/docs/latest/develop/reference/clients/) 与 [CLIENT LIST](https://redis.io/docs/latest/commands/client-list/)：当回复产出快于客户端消费，output buffer 会增长；omem 是输出缓冲内存，oll 为输出链表长度，cmd 是最近命令，不能单独代表连接用途。本轮用地址、数量、源码和时间关联补充归因。
- Drogon [HttpServer 固定版本源码](https://github.com/drogonframework/drogon/blob/4c5430757ea5451a7c38fbbef4b4bef7dbb47f2f/lib/src/HttpServer.cc)、[HttpResponseImpl](https://github.com/drogonframework/drogon/blob/4c5430757ea5451a7c38fbbef4b4bef7dbb47f2f/lib/src/HttpResponseImpl.cc)、[HttpAppFrameworkImpl](https://github.com/drogonframework/drogon/blob/4c5430757ea5451a7c38fbbef4b4bef7dbb47f2f/lib/src/HttpAppFrameworkImpl.h)：对应真实 gzip 默认、lazy body、HTTP loop 交接行为，非最新文档臆测。
- k6 [v2.2.0 runner Transport](https://github.com/grafana/k6/blob/v2.2.0/internal/js/runner.go)：DisableCompression=true；[HTTP request](https://github.com/grafana/k6/blob/v2.2.0/js/modules/k6/http/request.go) 解析调用者 headers。本轮另有真实默认/显式 gzip 对照。
- Ticketmaster [Discovery](https://developer.ticketmaster.com/products-and-docs/apis/discovery-api/v2/) 暴露 seatmap.staticUrl，[Partner Availability](https://developer.ticketmaster.com/products-and-docs/apis/partner/availability/) 是独立 availability 资源。仅作为静态图/动态可用性分离候选依据，不将图片 API 等同本项目交互座位布局。
- pretix [Seating Plans](https://docs.pretix.eu/dev/api/resources/seatingplans.html) 与 [Seats](https://docs.pretix.eu/dev/api/resources/seats.html) 分开，Seats 有 is_available、zone_name/row_name 筛选；[Conditional Fetching](https://docs.pretix.eu/dev/api/fundamentals.html) 提供条件请求思路，但并非证明所有 Seats endpoint 都支持相同 validator。作为数据拆分、区域加载、条件请求参考。
- Eventbrite [Platform API](https://www.eventbrite.com/platform/new/api) 区分 Seat Maps 与 Inventory Tiers 资源；仅支持语义拆分思路，不声称它们内部如何缓存或承载多少 QPS。
- Go [singleflight](https://pkg.go.dev/golang.org/x/sync/singleflight) 同 key 的并发重复调用去重；仅为公共快照计算减少候选，own checkout overlay 不能无差别共享。
- Envoy [circuit breaking](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/circuit_breaking) 区分 pending requests 和 outstanding requests 上限；只作为未来有界在途保护参考，不在此项目引入 Envoy。

## 10. 下一步候选排序（等待审查，未实施）

1. **先补 heap / allocator / 生命周期诊断**：Drain B 保留高位内存尚未解释；也需 CPU profile 验证 Redis callback 线程上的 JSON/析构成本与调度等待。不是立刻上大型 API 重构。
2. 数据面第一候选：Static Layout / Dynamic Availability split，减少重复完整对象树、静态读取和响应字节；证据支持进入方案审查，但不能宣称它已解决长尾或内存保留。
3. Layout Cache 可随静态拆分进入候选；DB fetch 本轮不主导长尾，所以不是直接加 Redis cache 或扩大 pool。
4. Compression 候选是先做默认 k6 与真实浏览器编码条件的受控容量对照；服务端 gzip 已可用，不是“尚未开启”。Brotli 暂缓，未测额外 CPU 成本。
5. Singleflight / short snapshot reuse 是减少公共重复计算候选，需隔离身份/own hold overlay、明确失效与正确性边界。
6. bounded in-flight 是后续过载保护候选，不替代消除单请求瓶颈；本轮只限制诊断 arrival，不修改服务保护逻辑。
7. Zone/block loading 有成熟资源设计依据，但未采集本项目用户可视区域行为，优先级低于当前已测得的完整响应成本。

不选择 SQL/index/PG pool/Redis pool 优化；不实施多实例、MQ、waiting room、缓存、streaming、pagination 或其他业务变化。

## 11. 验证、异常与复现

- Docker 实际 CMake configure、GNU C++ 13.3 编译/链接通过；构建阶段 CTest 20/20，通过后另在同一 build image 重跑 CTest 20/20（0.72s）。
- Seat Map smoke：`20260906T095903Z-seat-map-read-smoke-860f`，3 business success、0 unexpected/drop。
- 九格 matrix + 一次 Drain，runner 均 exit 0，verifier 均 14/14；每次新 profile 生成后的额外 verifier 也通过。所有 10 轮 samplingErrors=0。
- gzip 的 identity/显式 gzip 解压一致性覆盖三种 seat count；真实 k6 默认/显式编码 probe 覆盖 1k 和 5k。CLIENT LIST 证据在每轮 samples.jsonl。
- Drain 后 verify_observability.py 全通过、所有 targets up、flight=0。
- 普通 config 真实健康检查 200，/metrics 404；Seat Hold integration **9/9**、Checkout integration **6/6**、Auth integration **7/7**，包括 own/other hold 显示、Redis 故障、confirm 状态与认证撤销语义；日志位于 phase10b3-validation。均用 COMPOSE_FILE 指向 Performance compose、COMPOSE_PROJECT_NAME=ticketing-phase10a、TICKETING_BASE_URL=http://127.0.0.1:18080，不访问开发数据库。
- Performance Python **71/71**；新增采集与报告测试保留 151 / 153 实测差异、验证低基数/数据维度、按当前 k6 容器隔离资源和完整 Drain 时间序列。
- Playwright Chromium **4/4（15.9s）**：checkout-smoke、payment-smoke、order-deeplink、multi-client；只启动测试用 Vite，frontend 源码零改动。此前用现有 generator 切回 smoke fixture，未删除卷，生成后 verifier 14/14。
- E2E 后恢复默认 Performance 配置及默认支付模拟参数；最终 verifier **14/14**、verify_observability **PASS**、/health 200。Performance Stack 保持运行，最终 fixture 为 smoke；未清理或修改普通开发卷，镜像和卷保留。

遇到的非业务问题：初次 profile 生成后打印 UTF-8 输出触发 Windows GBK UnicodeDecodeError（失败目录 `20260906T100015Z-seat-diagnosis-1000-10`）；数据库生成已成功，尚未开始负载。改用既有 print_console 并设置 PYTHONIOENCODING=utf-8 后重新生成、验证、完成全部实验。保留失败 artifact，不把它统计成容量失败。一次早期 http-debug probe 未配置 summary 目录而无法写 summary，只作临时响应观察，未纳入正式 matrix。

本轮额外按 k6 容器名取资源证据，避免把旧 one-off 残留相加；没有去修改既有 B-2 报告或公共 runner 语义。报告测试第一次严格要求 SQL calls = histogram samples 时失败，源码核对发现 exporter 5 秒缓存；随后改为校验已披露的实际窗口差异，未修改任何采样值。一次误写 verifier 路径的调用未执行成功，随后改用仓库真实 performance/verification/verify_database.py 并通过。构建现有的 missing-field-initializers 警告非本轮新增，不绕过任何业务测试。

复现（只针对隔离 Performance 项目；--prepare 会重建 performance fixture，不用于开发数据）：

```powershell
$env:PYTHONIOENCODING = "utf-8"
docker compose -f performance/docker-compose.performance.yml build backend
docker compose -f performance/docker-compose.performance.yml up -d --wait
python performance/scripts/diagnose_seat_map.py --seats 1000 --rate 10 --prepare
python performance/scripts/diagnose_seat_map.py --seats 1000 --rate 30
python performance/scripts/diagnose_seat_map.py --seats 1000 --rate 60
# 2500 / 5000 同理；每格先审查积压，再决定后续，不盲目串跑升压
python performance/scripts/diagnose_seat_map.py --seats 5000 --rate 60 --duration 30 --drain-seconds 180
```

诊断工具限制 rate/duration，但没有自动 RSS kill guard；运行时仍需像本轮一样观测安全线，不能无人值守外推更长窗口。普通回归会停止 Redis，不得与诊断并行。

完整 raw artifacts 在 ignored `performance/results/<evidenceDirectory>/`，包括 baseline、metrics-before/after、stages、samples、gzip、PG SQL/locks/activity、Prometheus 和 verifier；子 run 含 k6 summary/console/manifest。可分享的数值和 Drain 时间序列已提交到 measurements.json；不提交 cookie、token、生成的用户认证池或原始 credentials。

## 12. 提交与交付边界

诊断指标提交：`ad2fa42022bfdf44ba9e806207ac2b11efd4f87a perf: add seat map diagnostic metrics`。本报告、证据摘录、编码 probe 与资源采集测试由后续独立 `perf: characterize seat map response path` 提交保存。没有 amend、reset、rebase 或 push。最终 hash / ahead / status 以交付时 Git 命令为准。
