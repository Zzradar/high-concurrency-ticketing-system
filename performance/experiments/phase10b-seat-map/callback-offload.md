# Phase10B-3：Redis 回调后处理迁移实验

## 范围与起点

本轮只改变 Seat Map 在 Redis reply 之后的重计算执行位置。未修改 frontend、API 成功响应、SQL、
PG pool=4、seat_holds Redis pool=2、timeout=0.4s、gzip 配置、数据模型或库存/支付/认证裁决。
未实施 Static Layout / Dynamic Availability split、缓存、Waiting Room 或下一项优化；未 push。

起点 main、工作区 clean，HEAD `1763c3d03326917b08626e2638cbcfc9a4c9e0bd`，
origin/main `2aec8a5ba492e5cdb64f91e33391f5c2c634f7e7`，ahead 13。
B-2 报告以独立提交 `049dc593e4d7562b64251c0ce35fb9ecc75d076e` 追加展示正确性校正，
保留全部原始运行数字；旧 60/s / 90% 的 HTTP/DB pass 不再代表完整展示 correctness，
不虚构 10~60/s 之间的边界。旧 diagnosis/calibration 文档及 JSON 未改写。

环境仍为 Docker 29.7.2、Linux/WSL 2、16 logical CPU、16,548,249,600 B VM memory。
仅操作 `ticketing-phase10a`（HTTP 18080），从 smoke 逻辑替换为 100k 用户、20k auth sessions、
20 sessions、每场 5000 seats 的既有诊断 profile；没有删除任何卷，未操作普通开发数据库。

## 固定框架线程与所有权核对

从现有 build-inspect 镜像实际读取 Drogon v1.9.13 源码，git rev-parse 为
`4c5430757ea5451a7c38fbbef4b4bef7dbb47f2f`。

```text
Before：PG callback → owned DTO/ids → Redis EVAL/MGET
  → RedisLoop：owner parse → overlay → JSON build → response tree copy
  → HTTP completion：自然 serialization / gzip → HTTP EventLoop queueInLoop → send

After：PG callback → owned DTO/ids → Redis EVAL/MGET
  → RedisLoop：owner parse → move owned data / trySubmit → return
  → dedicated compute worker：overlay → JSON build → response tree copy
  → HTTP completion：自然 serialization / gzip → HTTP EventLoop queueInLoop → send
```

- `RedisConnection.cc:300,335`：hiredis 在 connection loop 中读回复并直接调用业务 callback。
  `RedisClientImpl.cc:381`：reply/error/timer 通过 TaskTimeoutFlag 原子 done 竞争一次完成；
  0.4s timer 也在 RedisLoop 上执行，不是独立实时中断。迟到回复仍会被消费，但不重复完成业务请求。
- `RedisResult.h` 明确禁止离开回调后保存、copy 或 move 该包装对象。原 `readOwners` 在回调内
  将 reply 解析为 `vector<optional<string>>`；只把这个独立拥有内存的容器交给 worker，未传 RedisResult 引用。
- `SeatRepository` 已在 DB callback 内物化为拥有字符串的 SeatRow vector；Service 再转为 Seat vector。
  新 task 不持有 DB Result/Row/Field，也不持有 SeatService/Controller 的裸 this。
  原 DB callback 中的 this 仍依赖 Drogon 注册 Controller 的既有生命周期，本轮未引入短生命周期 Service 用法。
- checkout ID 按值保存，是此前归属验证后的字符串；没有跨线程保存 request 裸指针或修改 checkout。
  HTTP callback 由 shared_ptr 持有，Drogon 自己的 CallbackParamPack 持有 request、connection、parser。
- `HttpResponseImpl.cc:82,117`：新响应和 JSON tree 为每请求独立对象，writer builder 通过 call_once 初始化；
  不并发修改同一个响应。`HttpServer.cc:773,1241` 在调用 completion 的线程执行 PreSending 和
  getCompressedResponse；shouldBeCompressed 触发自然 getBody，之后才 queueInLoop。
  因此 worker 调用 completion 会将自然序列化/压缩留在 compute 线程，不是搬到 HTTP I/O 线程。
  `EventLoop.cc:273` 的线程安全队列 enqueue + wakeup 完成发送交接；项目未另行 queueInLoop 重计算。
- [官方 threading model](https://github.com/drogonframework/drogon/wiki/ENG-FAQ-1-Understanding-drogon-threading-model)
  也说明非 HTTP 线程产生响应后交接发送，以及 compute-heavy callback 会阻塞所属 loop。
  以上是源码与接口契约核对，不是 CPU profile。

引用关系：main/Service 注册槽 → shared executor → bounded tasks → owned Seat/owner/context/HTTP callback。
task 不捕获 executor、Service 或 Controller；不存在 executor → task → executor 自引用环。
Redis callback 捕获 executor，但在 submit 后 Seat vector 被 move 出；原 readOwners 的 catch/fallback
边界由一次性 claimed 标志防止重复提交 moved-from 请求。错误 completion 不会在 worker 中重试重计算。

## 执行器及保护边界

`SeatMapComputeExecutor` 固定线程、deque 有界等待队列、mutex + condition_variable。
初始对照仅 2/4 workers，queue capacity 固定 16；不是 logical CPU 自动扩线程。
构造参数守卫限制 1..4 workers、1..64 slots，拒绝零值；本实验不把 queue 调整为吞吐旋钮。
每个等待任务只持有 DTO/owners 和 callbacks，JSON tree 在 worker 开始后才构造。

trySubmit 不等待空槽、不执行 inline fallback。满队列或 executor 已停止时返回 false，Controller
返回 HTTP 503，统一错误 body 的 code 为 `SEAT_MAP_BUSY`。没有静默丢 callback。
普通异常由 worker 的 onError 返回既有 INTERNAL_ERROR，worker 继续处理后续任务。
任务及其大捕获在 worker 内、queue mutex 外销毁；拒绝时未入队的 DTO 析构仍发生在提交线程，
这不是零成本回调，也未声称所有 O(N) 操作均移出 RedisLoop。

main 通过显式 shutdown 和异常退出 RAII guard 停止接收、排空已接受计算、join 线程；
构造部分线程失败时也 shutdown/join。shutdown 必须由应用 owner 的非 worker 线程调用。
这是计算执行器 drain，不是整个 HTTP 服务的优雅停机承诺：固定 Drogon quit 会先关闭 listener、
Redis/DB manager 和 I/O loops，连接可能已断开；不能保证停机中的响应最终送达客户端。
队列只限制 Redis 后处理这一段，不限制之前的 HTTP/DB/Redis 在途请求或框架发送缓冲。

保留所有 Redis 四 outcome 指标和原 11 stages。新增固定低基数 compute queue_depth、active_workers、
submissions_total{accepted,rejected}、queue_wait_seconds、execution_seconds。
观测在 queue mutex 下按状态变更顺序发布，避免多个 worker 的旧 gauge 覆盖新状态；不执行 I/O。
execution 包含 overlay、JSON/response、HTTP completion 同步段及 task 捕获释放，不含 socket flush。
普通配置没有 exporter 时为 no-op；performance 配置在开始接受请求前预注册所有 metric handles。

## 测量边界

Before 在任何线程代码改动前运行，二者 manifest HEAD 为仅追加文档的 `049dc59`；
进程仍为旧 calibration 镜像，container `946a97f2b1b8a38fb1f08ebc3a2e1b024a4d42bb070b459f0d3885efa472db1f`，
StartedAt `2026-09-06T11:23:56.686703784Z`，RestartCount 0。
After 保持相同 5000-seat fixture、700 VUs、steady arrival 和 identity/gzip workload。
0% 压力响应丢弃 body，90% 每响应校验 HELD/AVAILABLE/SOLD；两者 k6 计算开销不同。
每次 fixture TTL 600s，预期其他 owner 的 4500 HELD/500 AVAILABLE/0 SOLD，formal DB 仍为 5000 AVAILABLE。

PromExporter 5s 缓存仍在，before/after 静默 6s；queue/in-flight 为有缓存、离散采样峰值，
不是绝对瞬时最大值。阶段与 compute 分位数用 histogram delta 插值，HTTP 用 k6；不可相加。
CPU 为当前 Backend 容器的 cAdvisor 30s rate 最大观测值，15s 短测会被平滑。
所有实验同机、单次、非随机交错；重建进程改变 allocator 热状态，绝对 RSS 不是严格随机 A/B。
CPU profile 未执行：runtime 容器未安装 perf/gdb，perf_event_paranoid=2；没有安装工具或改变权限。
不能提供函数 CPU 占比、栈迁移实测或 heap 活对象结论，线程迁移依据源码和受控 outcome 对照。

## 实测结果与回归

### 显式运行清单与 worker 选择

全部原始证据在被忽略的 performance/results/<runId>/ 中；脱敏聚合为同目录
`callback-offload-measurements.json`，只按以下显式 ID 读取，不混入旧 run。
计数含 k6 setup 的一次请求，因此 902 lookup 对应 901 个压力 iteration；450/451 等也按实际记录，不假定边界 iteration 数。

| 阶段 | runId | Redis success/timeout/error/parse_error | HTTP p50/p95/p99 ms |
|---|---|---|---|
| before | 20260906T114631Z-seat-calibration-60-0-identity-d83a69c9 | 498/404/0/0 | 382.45/612.46/637.69 |
| before | 20260906T114743Z-seat-calibration-60-90-identity-6fddd824 | 158/744/0/0 | 987.71/1799.89/1845.03 |
| workers2 | 20260906T120016Z-seat-calibration-60-0-identity-bf4f2d0b | 902/0/0/0 | 失败：97 次 503，不作为成功延迟 |
| workers4 | 20260906T120229Z-seat-calibration-60-0-identity-58d3efef | 902/0/0/0 | 53.10/71.89/82.84 |
| workers4 | 20260906T120537Z-seat-calibration-60-90-identity-e7f9ace4 | 902/0/0/0 | 58.26/83.17/97.96 |
| workers4 | 20260906T120729Z-seat-calibration-30-0-identity-b60e5021 | 451/0/0/0 | 51.04/64.63/71.91 |
| workers4 | 20260906T120813Z-seat-calibration-10-90-identity-0a6667d1 | 152/0/0/0 | 51.40/55.75/59.15 |
| workers4 | 20260906T120954Z-seat-calibration-30-0-gzip-c0b1d396 | 451/0/0/0 | 33.73/36.78/53.15 |
| workers4 | 20260906T121038Z-seat-calibration-60-0-gzip-a563ed1a | 902/0/0/0 | 36.00/43.75/53.66 |
| workers4 | 20260906T121513Z-seat-calibration-60-0-identity-39768aed | 1802/0/0/0 | 37.26/65.62/75.07 |

2 workers、queue=16 的第一组 60/s 虽然 timeout=0，但 accepted=805/rejected=97，
901 iterations 中 804 success/97 system_error（HTTP 503），k6 exit=99。队列采样达到 16，
queue wait p50/p95/p99=349.59/484.96/496.99ms。没有扩大 queue，也未继续该候选的长测；
按预定唯一另一配置 4 workers 对照。该失败是有界执行器的可见容量不足，不是 pass。

此失败暴露采集器先抛错而尚未保存 verifier/final 的证据完整性问题。本轮仅调整采集顺序：
先保存数据库 verifier 再返回失败，不放宽失败判定；新增 90% candidate 的逐响应 display guard。
原失败 manifest 不覆盖，稍后只读补查 DB 14/14、formal AVAILABLE=5000、health ok；
补查日志 `callback-offload-workers2-failed-verifier.log` 和 supplemental-final.json 明确不是原边界。

4 workers、queue=16 的七点矩阵全部：dropped/system_error/unexpected/rejected=0，
最终 in-flight/queue/active=0，verifier exit=0，formal AVAILABLE=5000 未变。
全矩阵同一 Backend 进程，StartedAt `2026-09-06T12:02:23.084390684Z`、RestartCount=0。
镜像 `sha256:0194629a0d4467809fa53cfef32988b81dd02cd020eb4e961bf79867d9294ed5`。
镜像最初默认 2，通过只改 workers 的挂载配置实际使用 4；选定后源码默认改为 4 并再次完整构建，
不是拿重建后不同进程混入 Drain。队列未调参。

### 高载 Before/After：60/s、15s、identity

| 指标 | 0% Before → After | 90% Before → After |
|---|---|---|
| Redis success/timeout | 498/404 → 902/0 | 158/744 → 902/0 |
| lookup p50/p95/p99 ms | 310.78/848.66/969.73 → 3.78/4.93/7.95 | 927.63/2333.78/2466.76 → 4.77/9.79/20.33 |
| HTTP p50/p95/p99 ms | 382.45/612.46/637.69 → 53.10/71.89/82.84 | 987.71/1799.89/1845.03 → 58.26/83.17/97.96 |
| owner_parse p50/p95 ms | 0.066/0.099 → 0.077/0.153 | 0.183/0.389 → 0.183/0.381 |
| JSON build p50/p95 ms | 4.50/22.37 → 6.35/9.66 | 14.98/24.66 → 7.27/10.65 |
| response_callback p50/p95 ms | 7.50/9.77 → 7.52/9.79 | 7.59/9.92 → 7.70/14.90 |
| max single-client omem B / oll | 1225960/95 → 0/0 | 31364848/1610 → 0/0 |
| in-flight sampled peak | 33 → 2 | 101 → 3 |
| Backend CPU cores, 30s rate max | 1.86 → 1.91 | 1.95 → 2.14 |
| RSS peak MiB | 204.64 → 135.35 | 446.65 → 137.38 |
| working set peak MiB | 199.78 → 133.54 | 447.70 → 138.44 |

owner_parse 只对成功 reply 计样本，Before 分别 498/158，After 均 902，不能把样本集合不同当成纯 CPU 对照。
90% expected 为 HELD=4500、AVAILABLE=500、SOLD=0。Before exact=157/901、
degraded=744/901；After exact=901/901、degraded=0、invalid=0；10/s 控制 exact=151/151。
0% read 不做全部逐响应 HELD 断言；gzip probe 比较完整 5000-seat body 一致。
全部 11 个阶段的三个分位数及计数在 JSON 中，PG server 均保持毫秒级；没有把效果解释为 Redis server 本身变快。

### Compute 资源

| After 条件 | queue 采样峰值 | active 采样峰值 | wait p50/p95/p99 ms | execution p50/p95/p99 ms | CPU cores max |
|---|---|---|---|---|---|
| 60/s 0% identity 15s | 0 | 2 | 0.07/0.22/0.24 | 35.89/48.59/49.72 | 1.91 |
| 60/s 90% identity 15s | 0 | 2 | 0.05/0.30/3.84 | 37.03/48.89/49.94 | 2.14 |
| 30/s 0% identity 15s | 0 | 1 | 0.07/0.22/0.24 | 33.17/48.32/49.66 | 0.97 |
| 10/s 90% identity 15s | 0 | 1 | 0.08/0.23/0.25 | 35.38/48.54/49.71 | 0.33 |
| 30/s 0% gzip 15s | 0 | 1 | 0.07/0.22/0.25 | 37.50/48.75/49.75 | 1.28 |
| 60/s 0% gzip 15s | 0 | 2 | 0.05/0.19/0.24 | 37.01/48.70/49.74 | 2.07 |
| 60/s 0% identity 30s | 0 | 2 | 0.07/0.21/0.24 | 36.04/48.60/49.72 | 3.20 |

采样 queue=0 不等于从未排队；queue-wait histogram 已记录非零等待。
四 worker 的等待没有持续增长，所有 accepted 样本与 execution 完成数相等；
2-worker 饱和样本表明有界拒绝真实生效，不能用该样本宣称零错误容量。
30s run 的 CPU 3.20 cores 高于短测平滑值，不能声称总体计算量下降；
优化改变了执行位置/并行度，没有减少每请求的 JSON、复制或压缩成本。

### gzip 与 Chromium

此处 Before gzip 使用已有 calibration 的历史 run，不伪称本轮重新跑了这两点：
30/s `20260906T111647Z-seat-calibration-30-0-gzip-fe89c611`；
60/s `20260906T111735Z-seat-calibration-60-0-gzip-96ad0591`。

| gzip 条件 | Before HTTP p50/p95/p99 ms | After HTTP p50/p95/p99 ms | Before → After timeout |
|---|---|---|---|
| 30/s | 33.71/38.37/52.26 | 33.73/36.78/53.15 | 0 → 0 |
| 60/s | 993.06/1907.21/2048.15 | 36.00/43.75/53.66 | 700 → 0 |

低载没有普遍延迟收益（identity30 历史 p95=56.95，本轮64.63ms），不夸大每点都更快。
高载 gzip 不再伴随大量 Redis timeout；不是“gzip 无用”，也不是禁用压缩换性能。
本轮真实 Chromium 153.0.8010.12 默认 Accept-Encoding=gzip, deflate, br, zstd，
返回 HTTP200、Content-Encoding=gzip、Content-Length=44086、5000 seats。
probe 未设置 Accept-Encoding；原始 JSON822421 B，解压后的 bodyEquality=true。

### Drain / memory

历史 Before Drain：
`20260906T110834Z-seat-calibration-60-0-identity-df26f59f`，30s+180s，未重跑、未改原证据。
RSS before/peak/after=237.45/963.94/586.05MiB；in-flight peak241，timeout1623；
是 B 类部分回收，不能删去历史高水位问题。

本轮 After Drain：
`20260906T121513Z-seat-calibration-60-0-identity-39768aed`，同一已暖进程，
RSS=134.68/139.78/134.19MiB，working set=129.38/137.75/130.25MiB。
1802 success、0 timeout，HTTP37.26/65.62/75.07ms；in-flight peak2；
最后活跃采样之后首次观察零时间为 epoch1788696955.7346094，
最终采样与完整时间轴见 JSON；从 runnerFinished 到 end 超过180s。
queue/active最终0；omem峰41056B、oll3，无持续增长；Redis used memory回到3319648B。
本轮分类 **A：回到暖进程负载前水平**，不是“回到冷启动 RSS”。
没有 restart、malloc_trim 或 GC 干预。4-worker第一点冷进程RSS75.39→130.59MiB、
短测后的新高水位仍存在，不能靠后续暖 Drain A 证明没有 allocator retention/leak。

### 回归与交付边界

全部以下结果均为实际执行，不是静态解析代替运行：

| 验证 | 结果 | 本地 ignored 证据 |
|---|---|---|
| 两次 Docker CMake Release / GNU13.3 / C++20 编译、链接 | 成功 | callback-offload-build.log / callback-offload-final-build.log |
| 最终镜像 CTest full | 21/21，0.83s，含真实 executor unit | callback-offload-final-build.log |
| Performance Python | 84/84 | `python -m unittest discover -s performance/tests` |
| Seat Hold integration（普通 config） | 9/9，65.580s；own/other、outage/restart | callback-offload-seat-hold.log |
| Checkout HTTP integration（普通 config） | 6/6，19.702s | callback-offload-checkout.log |
| Auth HTTP integration（普通 config） | 7/7，59.924s | callback-offload-auth.log |
| Smoke dataset + offline /auth/me | PASS，HTTP200 | callback-offload-smoke-dataset.log |
| Playwright Chromium | 4/4，19.5s；下单、支付、深链、双客户端 | callback-offload-e2e.log |
| Observability verifier | PASS，0 failed；5 targets up、PG4连接、19 panel queries | callback-offload-observability.log |
| Formal DB verifier | 各成功矩阵点及 E2E 前后14/14，全部 violation=0 | 各 run/verifier.txt、callback-offload-db-before-e2e.log、callback-offload-db-final.log |

最终 build 镜像 `sha256:b4978f76b65fcddff15a5c40b36a6b5c32573421276048229f5f9a666388dc29`。
实现独立提交 `94e6dbb0387434e3dcc62a9fa8ddd63403037241`（perf: offload seat map post-processing）。
普通模式 /metrics=404；最终已恢复 config.performance.json、workers4/queue16、
TICKETING_PAYMENT_FORCE_OUTCOME 为空，/health=HTTP200 `{"database":"up","status":"ok"}`。
Performance Stack 留在运行状态，backend/postgres/redis healthy，数据集为 smoke（保留 E2E 产生的测试记录）。
保留全部镜像/卷，尤其 backend_ticketing_postgres_data，未执行 down -v、prune 或任何卷删除。
frontend、SQL/repositories、SeatHoldService、DTO、Dockerfile 及原 diagnosis/calibration 文档/JSON 零 diff。

关键复现实验命令（在已有隔离5000-seat fixture和镜像下，不能直接拿最终smoke数据压测）：

```powershell
python performance/scripts/configure_seat_map_experiment.py --workers 4
python performance/scripts/calibrate_seat_map.py --rate 60 --compute-workers 4
python performance/scripts/calibrate_seat_map.py --rate 60 --density 90 --compute-workers 4
python performance/scripts/calibrate_seat_map.py --rate 60 --encoding gzip --compute-workers 4
python performance/scripts/calibrate_seat_map.py --rate 60 --duration 30 --drain-seconds 180 --compute-workers 4
```

回归通过 COMPOSE_FILE 的绝对 performance Compose 路径、COMPOSE_PROJECT_NAME=ticketing-phase10a、
TICKETING_BASE_URL=http://127.0.0.1:18080 指向隔离资源，未指向普通开发数据库。
E2E 用既有测试配置临时强制支付 SUCCESS，运行后撤销；不是业务代码修改。

### 结论与下一候选

- 4-worker 在指定矩阵满足情况 A：timeout 消失、90% display 恢复、HTTP/omem/in-flight改善。
  与固定源码线程证据共同支持 callback/EventLoop 排队是主要瓶颈之一，不声称唯一根因或 Redis server 慢。
- 2-worker 出现情况 B 的计算资源不足/显式拒绝；没有扩大队列掩盖。
- 下一项功能性能候选仍是 Static Layout / Dynamic Availability split，目的是减少单请求计算和响应体；
  本轮60/s已健康，不意味着找到上限，也不授权现在实现 split。
- heap/allocator/lifecycle 是独立后续诊断候选：本轮暖 Drain A 降低了其即时优先级，
  但旧 B 和冷→暖高水位没有被 CPU profile 或 heap 活对象证据解释。若长测复现 B/C，应提高优先级。
- 未解决更高载、长时间/冷启动内存归因、全 HTTP 优雅停机、Redis 真正故障时的 display fallback。
  bounded queue 仅限制后处理；拒绝时会返回503，不能保证任意请求率无退化。
- 本轮不进入下一优化，不 push，不删除任何数据卷。
