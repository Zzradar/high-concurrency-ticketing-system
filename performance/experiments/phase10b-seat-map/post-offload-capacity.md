# Phase10B-3：callback offload 后容量边界

## 范围与复现口径

本轮只寻找已实现的 Seat Map 后处理迁移的新边界，不继续优化业务实现。
起点 main / clean，HEAD `fbaa1575c1c357a5c6d41beb3422adcbd8ad2b71`，
origin/main `2aec8a5ba492e5cdb64f91e33391f5c2c634f7e7`，ahead 16。
旧 diagnosis、calibration、callback-offload 文档和 JSON 均保留。

运行对象仅为 `ticketing-phase10a`，HTTP 18080；每轮检查实际容器命令、镜像、
StartedAt 和 RestartCount，固定 workers=4 / queue=16、PG pool=4、
seat_holds Redis pool=2 / timeout=0.4s。没有重启干预测量或 Drain，没有删除任何卷。

主场景为 browser-equivalent gzip；identity 仅作对照。`--prepare` 使用既有 generator
生成 100k registered users、20k offline auth sessions、20 个场次、每场 5000 seats。
正式目标场次始终 AVAILABLE=5000。90% fixture 每轮重建，4500 HELD / 500 AVAILABLE / 0 SOLD，
TTL=900s，覆盖 15s discovery 或 300s observation + 180s Drain。

新 workload 与旧实验的区别必须保留：本轮包括 0% 在内的每个 Seat Map 压力响应都解析并检查展示；
旧 0% calibration 只在 preflight 检查正文。因此不能把两个脚本的 k6 CPU 开销视为相同。
Mixed 使用独立 public/auth/seat scenarios，auth 只循环使用已预热的前 100 个 Session；
旧 synthetic-mixed-read 虽预热一部分，实际轮转完整 Session 池。新实验是明确的 warm auth 口径，
不将其视为对旧 B-2 冷暖混杂场景的完全等价复刻。Mixed 使用 90% hold，逐响应检查展示。

每 scenario 700 preallocated VU；15s 固定 arrival，允许 k6 边界额外 iteration，
但必须至少交付 rate×duration，dropped=0。503 既计 system_error，也单独计
`ticketing_seat_map_503_total`，不能被通用 business summary 中 capacity_rejection=0 掩盖。
HTTP 200 的 complete formal fallback 记 degraded，不算展示准确或稳定。

采集边界：阶段/compute 分位数是前后 histogram bucket delta 插值，不是逐请求 tracing；
HTTP 全局分位数包含一个 k6 setup 请求，独立 scenario 自定义 Trend 不含 setup。
Redis/compute 总计包含 setup，不含 metrics-before 之前的 fixture 和 gzip 探针。
PromExporter 有 5s 缓存，采样为多条顺序命令，时间不原子；峰值是采样峰值。
CPU 为 cAdvisor 30s rate，15s 短测会被窗口稀释，不能直接等同瞬时 CPU 饱和度。
Backend 资源按本次精确 container ID 过滤，k6 按本轮唯一名称过滤。
container networkTransmit包含Backend与Redis/PG的内部流量，不能直接当作HTTP输出带宽。
HTTP p95 时间线来自 k6 Remote Write Trend gauge 快照，不是多个窗口 p95 的平均或总体 p95。
Seat Map in-flight 在 PreSending 结束，不代表完整 socket flush。

单轮硬门槛通过后仍人工审查 queue/in-flight/buffer/memory 时间趋势才允许升档。
一旦明确失稳，仅进行指定重复确认，不插值中间容量，不调 worker/queue/pool。

## 实际浏览器与 15s Discovery / 固定确认

现有 Playwright Chromium 153.0.8010.12 的真实请求自动携带 `gzip, deflate, br, zstd`；
后端 HTTP200、Content-Encoding=gzip、Content-Length=42236，5000 seats / 4500 HELD。
0% 独立 identity/gzip 探针为 822421 / 44086 bytes；90% 为 799921 / 42236 bytes，
解压后正文一致。identity 探针在压力窗口之外，不作为主容量测试。

所有以下运行均为 gzip / 15s。iterations 是压力请求，不含一个 setup；
HTTP 分位数含 setup。`exact/degraded/invalid` 只计压力响应；失败的 HTTP503 单独列出。

| 场景 | rate | iterations | HTTP p50/p95/p99 ms | Redis success/timeout/error/parse_error | accepted/rejected | exact/degraded/invalid | 结论 |
|---|---:|---:|---|---|---|---|---|
| R1 0% | 60 | 901 | 39.45/57.54/66.48 | 902/0/0/0 | 902/0 | 901/0/0 | 短测稳定 |
| R2 0% | 100 | 1500 | 259.09/313.08/337.78 | 1501/0/0/0 | 1112/389 | 1111/0/0 | 失稳 |
| R3 0% | 60 | 901 | 38.22/57.36/68.49 | 902/0/0/0 | 902/0 | 901/0/0 | 短测稳定 |
| R4 0% | 60 | 901 | 40.19/60.68/70.17 | 902/0/0/0 | 902/0 | 901/0/0 | 短测稳定 |
| R5 0% | 100 | 1501 | 260.47/319.73/361.44 | 1502/0/0/0 | 1098/404 | 1097/0/0 | 失稳 |
| R6 90% | 60 | 901 | 42.19/65.76/79.73 | 902/0/0/0 | 902/0 | 901/0/0 | 短测稳定 |
| R7 90% | 100 | 1501 | 259.84/311.00/328.46 | 1502/0/0/0 | 1135/367 | 1134/0/0 | 失稳 |
| R8 90% | 60 | 901 | 40.68/65.14/94.00 | 902/0/0/0 | 902/0 | 901/0/0 | 短测稳定 |
| R9 90% | 60 | 901 | 42.06/62.64/77.18 | 902/0/0/0 | 902/0 | 901/0/0 | 短测稳定 |
| R10 90% | 100 | 1501 | 262.94/319.56/348.00 | 1502/0/0/0 | 1108/394 | 1107/0/0 | 失稳 |
| R11 Mixed2× | 150 | 8251 | 22.39/408.89/520.05 | 2252/0/0/0 | 876/1376 | 875/0/0 | 失稳 |

每轮 dropped=0、unexpected=0，system_error 与上述 rejected 数一致，HTTP503=compute rejected；
每轮 formal AVAILABLE=5000 不变、Database verifier 14/14、最终 queue/active/in-flight=0。
失败运行保留 k6 exit99 和 runner 失败状态，不因数据库正确或 HTTP200 中无 degraded 而改称成功。

| 编号 | 原始 run ID |
|---|---|
| R1 | `20260906T130815Z-capacity-60-0-d64fb3c6` |
| R2 | `20260906T131009Z-capacity-100-0-67a4ec9e` |
| R3 | `20260906T131122Z-capacity-60-0-dcf82378` |
| R4 | `20260906T131205Z-capacity-60-0-d35d75e7` |
| R5 | `20260906T131249Z-capacity-100-0-b6d675c0` |
| R6 | `20260906T131349Z-capacity-60-90-4b821621` |
| R7 | `20260906T131537Z-capacity-100-90-d74b45a1` |
| R8 | `20260906T131703Z-capacity-60-90-a3e5307c` |
| R9 | `20260906T131807Z-capacity-60-90-ceb14693` |
| R10 | `20260906T131910Z-capacity-100-90-afd7d0a7` |
| R11 | `20260906T132044Z-capacity-150-90-06fd8c15` |

0%：60→100 后停止升压，60 再两次、100 再一次；90% 独立同样执行。
两种密度最高 confirmed stable 均为 **60/s（三次15s）**，first observed unstable 均为 **100/s（两次）**。
未运行 150/200/300/400/500 单项 Discovery，未插值中间容量，更不是生产容量/SLO 保证。
当前粗档位不能证明 90% 完全没有容量损失，只能说尚未观察到不同档位的边界。

## Compute、资源与新瓶颈

| 运行 | lookup p95 ms | queue wait p95 ms | execution p95 ms | peak queue/active/in-flight | Backend/Redis/k6 CPU cores (30s) | Backend RSS before/peak/after MiB | PG seat SQL mean ms |
|---|---:|---:|---:|---|---|---|---:|
| R1 | 6.48 | 0.23 | 49.13 | 0/2/2 | 2.00/0.12/1.07 | 77.67/123.88/115.66 | 8.49 |
| R2 | 9.65 | 246.59 | 96.07 | 16/4/20 | 2.82/0.19/1.74 | 118.64/194.11/183.57 | 10.03 |
| R3 | 6.18 | 0.24 | 49.02 | 0/2/3 | 2.20/0.12/0.92 | 181.15/183.99/180.07 | 8.62 |
| R4 | 6.94 | 0.23 | 49.39 | 0/2/2 | 2.28/0.13/1.06 | 181.45/181.46/171.74 | 8.70 |
| R5 | 9.45 | 249.12 | 96.23 | 16/4/21 | 3.29/0.21/1.73 | 174.66/199.46/190.97 | 10.16 |
| R6 | 9.77 | 0.25 | 49.82 | 0/4/3 | 2.23/0.17/1.33 | 193.78/193.78/192.85 | 8.88 |
| R7 | 20.93 | 243.77 | 95.38 | 16/4/20 | 3.38/0.30/1.29 | 191.06/211.44/201.92 | 10.02 |
| R8 | 9.89 | 0.48 | 49.70 | 0/3/2 | 2.30/0.18/0.95 | 196.20/196.52/196.52 | 8.78 |
| R9 | 9.76 | 0.24 | 49.65 | 0/2/2 | 2.17/0.19/0.97 | 196.60/196.60/196.60 | 8.74 |
| R10 | 20.36 | 249.20 | 95.87 | 16/4/21 | 3.42/0.31/1.71 | 199.27/209.16/205.25 | 10.14 |
| R11 | 202.15 | 479.10 | 175.34 | 16/4/40 | 3.55/0.53/1.81 | 203.73/247.90/235.75 | 11.92 |

所有短测峰值、完整 Backend/Redis/k6 working set / network / CPU series、HTTP waiting/receiving、
11 个阶段与 compute p50/p95/p99、PG SQL 和连接采样见配套 `post-offload-capacity-measurements.json`。

0%/90% 单项 Redis omem/oll 采样均为0/0；Mixed2×出现瞬时峰859168B/44，结束归0，
没有 timeout，但 lookup p95 增至202.15ms。这发生在 compute queue 已饱和的整体积压中，
不支持“callback offload 失效”或扩 Redis pool 的结论。

新 first observed unstable 的直接证据是 **compute capacity / bounded queue**：100/s 时4个worker忙、
queue接近16、queue wait约244–249ms p95，367–404次拒绝；Redis timeout始终0。
单项 PG SQL mean约10ms，没有与数百ms HTTP尾延迟同量级的数据库执行放大。
Backend CPU开销上升，但30s短测窗口和缺少CPU stack不能证明整台16逻辑CPU主机已饱和，
也不能把 compute execution 的wall time全部叫纯CPU时间。

## Mixed Read 2×

独立 scenarios：public200/s、warm auth200/s、seat150/s；90% hold / gzip。
Public成功3000/3000，p50/p95/p99=5.57/55.68/90.23ms；
Auth成功3000/3000，17.10/77.16/114.71ms；
Seat成功875/2251（875 exact，1376 HTTP503，0 degraded/invalid），133.52/506.29/583.61ms。
三类均交付目标，dropped=0；失败主导仍是Seat Map compute capacity。
Public/Auth没有正确性失败，但存在55–77ms p95尾延迟，不能声称完全不受共享资源影响；
缺少同轮同配置的无Seat对照，不能精确归因其增量。

2×已失稳，**4×与8×均未执行**。单项100/s已失稳，也没有理由机械执行seat600/s的Mixed8×。

## 5 分钟 observation 与 180s Drain

选择90% hold / gzip / 60/s，run `20260906T132336Z-capacity-60-90-e7c232dc`。
18,001/18,001 压力响应 exact，degraded/invalid/503/dropped/system_error/unexpected均0；
Redis success=18,002、timeout/error/parse_error=0；compute accepted=18,002、rejected=0，verifier14/14。
HTTP p50/p95/p99=42.50/65.55/87.82ms；lookup p95=9.80ms；
queue wait p50/p95/p99=0.048/0.326/7.660ms，execution=38.06/50.72/90.63ms。
采样queue峰1、active峰3、in-flight峰3，无持续增长，Redis omem/oll全程采样0/0。
Backend/Redis/k6 CPU 30s峰3.98/0.296/1.98cores；k6 working set峰500.20MiB；PG连接采样6、Seat SQL mean8.84ms。

时间趋势摘录（相对runner start最近采样，非精确整分；Redis为本轮success累计delta）：

| 相对秒 | RSS MiB | working set MiB | queue/active/in-flight | Redis success | HTTP p95 ms | PG连接 |
|---:|---:|---:|---|---:|---:|---:|
| 0 | 222.75 | 217.81 | 0/0/0 | 33 | 未产生 | 6 |
| 60 | 223.30 | 221.48 | 0/3/1 | 3460 | 61.78 | 6 |
| 120 | 223.86 | 222.04 | 0/2/2 | 7260 | 63.30 | 6 |
| 181 | 225.88 | 223.78 | 0/3/2 | 10910 | 65.56 | 6 |
| 241 | 225.93 | 223.84 | 0/2/2 | 14246 | 65.99 | 6 |
| 301 | 225.96 | 221.74 | 0/2/2 | 18002 | 65.56 | 6 |
| 360 | 225.96 | 220.95 | 0/0/0 | 18002 | 65.55 | 6 |
| 420 | 225.96 | 221.04 | 0/0/0 | 18002 | 65.55 | 6 |
| 479 | 225.96 | 220.86 | 0/0/0 | 18002 | 65.55 | 6 |

表内各点 timeout/error/parse_error/omem/oll 均0。HTTP p95列是截至该时刻的k6 Trend快照，
300s之后是最终快照残留，不是Drain期间仍有压力请求。
k6 Summary的自定义`*_ms`值为ms；Remote Write适配器把time Trend转换为秒，
虽然自定义series名称仍含`_ms`，此表已乘1000转换，JSON scope明确两种单位，不能直接混用。
共167个观测点；7个相邻queue-wait interval遇到不同龄缓存的非单调bucket，明确记unavailable，
不补0、不伪造分位数，下一有效区间继续从最后有效快照计算。全程总delta来自静默6秒的严格快照。

Backend始终为同一container `d817944fcfc577163b4471e01b3269a406e0cd63d1b9bf16103891f0b530e31d`，
image `sha256:b4978f76b65fcddff15a5c40b36a6b5c32573421276048229f5f9a666388dc29`，StartedAt=2026-09-06T12:27:51.344856889Z，RestartCount=0。
runner完成约303.31s，之后继续采集到final/end超过180s；没有restart或allocator干预。

暖baseline RSS/working set=222.75/218.41MiB；
峰值=225.96/225.23MiB；
最终=225.96/221.77MiB。
RSS比before高3.21MiB（1.44%），约180s后接近平台，负载结束后不再上涨；
working set比before高3.36MiB（1.54%），Drain期间在暖水平附近波动。

Drain归为 **A（接近暖基线，带限定）**：queue/active/in-flight归0，Redis缓冲为0，
没有历史B/C那种数百MiB的高水位残留；但RSS不是精确返回before，且本轮没有制造大幅内存在途放大。
这个分类只描述相对暖基线的本次观测，不设置事后硬百分比阈值，不据此证明无retention/leak，
也不抹去旧实验的B和冷→暖高水位。保留3.21MiB小幅平台事实供外部审查。

## 下一候选与边界

- 新首要瓶颈证据是compute queue/capacity。Static Layout / Dynamic Availability split应提升为下一阶段第一候选，
  目标是减少5k全量请求的计算与响应成本；本轮没有实施，也没有提前批准具体API设计。
- 更多workers可能提高吞吐，但没有6/8-worker实验或CPU profile，不声称必然有收益；由用户比较增加计算资源与减少单请求工作。
- 更大queue只容纳更多等待，没有增加service capacity的证据；本轮保持16，不靠扩大队列掩盖503。
- heap/allocator不在本轮进入实现；这次暖水平附近平台降低紧迫性，但残留与历史B仍是独立后续取证事项。
  若更长测试中无queue/in-flight仍持续增长或再次出现明显B/C，应提高优先级。
- 没有观察到generator先受限：所有目标arrival已交付、dropped0，k6峰CPU低于同机16 logical CPU总量。
  Mixed k6 working set约1.40GiB；同机竞争仍存在，不能据此宣称压力机影响为零。
- gzip下receiving相对compute queue wait很小：Mixed seat receiving p95约2.24ms，对比queue wait p95约479ms，
  不支持HTTP output是本轮首个边界。未做Brotli/Streaming、缓存、singleflight或pool调整。

## 实际回归与遇到的问题

| 验证 | 实际结果 | ignored本地证据（performance/results/ 下） |
|---|---|---|
| Docker build target | 成功，既有CMake/C++层缓存命中，本轮未重新编译C++ | post-offload-capacity-build.log |
| CTest full独立执行 | 21/21，0.80s，非缓存测试输出 | post-offload-capacity-ctest.log |
| Performance Python | 95/95 | unittest discover，包括新harness及证据校验 |
| Seat Hold integration | 9/9，64.943s | post-offload-capacity-seat-hold-retry.log |
| Checkout integration | 6/6，20.195s | post-offload-capacity-checkout.log |
| Auth integration | 7/7，61.131s | post-offload-capacity-auth.log |
| Playwright | 4/4，18.7s | post-offload-capacity-e2e.log |
| Seat Map smoke | 3/3，0错误、p95=2.17ms；18-seat smoke，不混入5k容量表 | post-offload-capacity-smoke-retry.log |
| Database verifier | 12个正式容量run分别14/14、E2E前后及最终14/14 | 每轮verifier.txt、post-offload-capacity-db-final.log |
| Observability verifier | PASS，0 failed，5 targets up、19 panel queries通过、PG backend pool4 | post-offload-capacity-observability-final.log |
| 最终health | HTTP200，`{"database":"up","status":"ok"}` | 实际curl响应 |

完整保留的失败与最小处理：

1. 容量100/s与Mixed2×的k6 exit99是预期被记录的失稳证据，没有修业务代码，也没有改成通过。
2. 汇总过早读取未写完的manifest曾报KeyError；新工具明确标记incomplete，等待runner结束后重读。
   相邻histogram缓存回退则标unavailable，原始sample不改，whole-run delta仍严格检查。
3. 新证据测试最初按Windows默认GBK读取UTF-8 JSON失败；显式UTF-8后全套95通过。
4. 第一轮Seat Hold回归在setUpClass把4500个本轮临时hold key一次性传给Windows，WinError206，0 tests执行。
   原失败日志`post-offload-capacity-seat-hold.log`保留。使用现有`run_k6.clear_seat_holds()`在隔离Redis内扫描清理
   本轮4500个临时fixture key后，原测试9/9通过；没有修改backend测试。
5. E2E留下一条正式HELD后，Seat Map smoke前置检查因expected0/actual1正确拒绝。
   原`post-offload-capacity-smoke.log`保留。用既有generator重新生成隔离逻辑smoke dataset后重跑通过，
   没有删除卷、直接改状态或弱化fixture校验。

## 最终状态、文件与复现

仅新增7个performance文件：本报告、配套`post-offload-capacity-measurements.json`、
`k6/diagnostics/post-offload-capacity.js`、`scripts/characterize_seat_map_capacity.py`、
`scripts/summarize_seat_map_capacity.py`、`tests/test_seat_map_capacity.py`、`tests/test_seat_map_capacity_evidence.py`。
没有修改backend、frontend、SQL、Dockerfile、Compose、旧报告或其他设计文档。
原提示所称`workloads/seat-map-calibration.js`在仓库中的真实位置是`diagnostics/seat-map-calibration.js`，已按真实文件阅读，未移动旧文件。

实验期间所有12轮是同一未重启的backend；容量与Drain结束后，才为普通配置回归/E2E按既有测试流程重建Performance backend。
最终恢复`config.performance.json`、4/16、默认支付模拟（强制SUCCESS环境为空），普通模式/metrics实测404。
Performance Stack继续运行，backend/postgres/redis healthy；最终fixture为重新生成的smoke。
所有镜像/数据卷保留，包括`backend_ticketing_postgres_data`和3个`ticketing_phase10a_*`卷。
未执行down -v、volume rm、prune、reset/rebase/amend或push；清理仅涉及隔离测试fixture。

复现需先准备5k数据，不能直接用最终18-seat smoke fixture跑新capacity脚本：

```powershell
python performance/scripts/characterize_seat_map_capacity.py --rate 60 --density 0 --prepare
# 审查上一轮完整证据后，才运行下一档；不要自动串跑升压
python performance/scripts/characterize_seat_map_capacity.py --rate 100 --density 0
python performance/scripts/characterize_seat_map_capacity.py --rate 60 --density 90
python performance/scripts/characterize_seat_map_capacity.py --rate 150 --density 90 --mixed 2
python performance/scripts/characterize_seat_map_capacity.py --rate 60 --density 90 --duration 300 --drain-seconds 180
```

边界已经找到，本轮止于取证；等待用户审查下一阶段，不继续堆优化。

工具独立提交：`81a76f7c3c476bd9538c7bdf0f74171b65fc2f94`，
`perf: extend seat map capacity characterization`。报告、脱敏证据与证据测试另作独立提交。
