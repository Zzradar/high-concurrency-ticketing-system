# Phase16 Availability 性能与验收证据

测试于 2026-09-12（Asia/Shanghai）；稳定基线 `9006ee822e557255e244364495fbe251a1a25b18`。所有容器与工作树均为 Phase16 专用。

## 环境与判据

Docker/WSL2 可见 16 CPU、15.41 GiB 内存，PostgreSQL 16、Redis 7.4、C++20 Release、k6 2.2.0。5000 席、5 区，每区 1000 席。PG pool=4、seat_holds Redis pool=2、SeatMapComputeExecutor=4 workers / 16 queue；Hold 默认 300 s。simulation 测试失败率为 0，生产默认配置未改。共享主机上其他任务容器保持运行；完整名称见 warm-evidence.json。

每模式预热 30 次，constant-arrival-rate=200/s、20 s、100 preallocated/max VUs。稳定判据：0 HTTP system error、0 dropped iteration、0 新增 compute reject，最终 outbox/lease/compute active/queue=0、库存 verifier 通过。k6 http_req_duration 含 setup 探针，查询计数窗口不含前置预热。controlled 模式重复读取同一个包含 1 次变化的游标，度量变化响应编码成本，不等于持续写入 200/s。

## Warm 请求

|模式|p50 ms|p95 ms|p99 ms|raw/gzip bytes|HTTP 错误|dropped|
|---|---:|---:|---:|---:|---:|---:|
|legacy|22.193|53.526|116.442|260046/13114|0|0|
|snapshot|541.167|681.112|746.141|52546/2901|164|737|
|delta|1.264|1.982|3.571|546/546|0|0|
|controlled|1.302|2.060|4.214|591/591|0|0|

小于服务器压缩阈值的响应没有 Content-Encoding；空 Delta 与 1/10-seat Delta 的 gzipBytes 是实际未压缩传输长度，不能解释为压缩效果。1/10/50 个变化分别 591/1015/2895 bytes；50-seat gzip 为 394 bytes。

legacy、no-change Delta、controlled Delta 达到本次稳定判据。Snapshot 在此负载下首次观察到失稳：164 个 5xx/compute reject、737 dropped；Redis 接近一个核饱和，发生 26 次 degraded 请求（各执行目标区查询与分组 Summary 查询）。保留结果，不将失败档写成稳定能力。初次 legacy 使用 30 预分配 VU，出现 3 rejects、28 dropped，原始记录保存在 initial-legacy/；最终四档统一改为 100 VU 并充分预热，未调整服务端容量。

## PostgreSQL 与执行池

|模式|旧全场 id/status 查询|全量 formal 初始化查询|ownership 查询|degraded Zone/summary 查询|
|---|---:|---:|---:|---:|
|legacy|4000|0|0|0|
|snapshot|0|0|0|26 + 26|
|delta|0|0|0|0|
|controlled|0|0|0|0|

warm-evidence.json 保存 pg_stat_statements 前后全量记录；summary.json 保存增量。真实 ownership 测试先通过 PG 填缓存，再重复请求三次验证 findByIdForUser 计数不变；同时测试匿名、他人、跨场次、错误缓存映射与缓存命令失败回退。

各模式 metrics-before/after.txt 保存 SeatMap executor 提交/拒绝/活跃/队列及 Phase16 低基数指标。Delta 两档新增拒绝为 0，收尾 active/queue 为 0；warm-evidence.json 中 outbox=0、activeLeases=0。Snapshot 拒绝是本次有界过载保护的真实观测。

## 容器资源

CPU 为 docker stats 百分比，100% 表示一个核。约每秒触发一次采样，命令自身有延迟；下表是采样均值/最大值，不是请求级 CPU 测量。完整内存序列、网络和 Redis INFO CPU/commands/memory 均在原始 JSON。

|模式|Backend CPU 均值/峰值|PG CPU 均值/峰值|Redis CPU 均值/峰值|
|---|---:|---:|---:|
|legacy|276.79%/338.78%|166.45%/221.58%|53.40%/56.98%|
|snapshot|36.30%/46.32%|0.14%/0.19%|85.65%/98.39%|
|delta|11.21%/19.64%|0.10%/0.19%|9.05%/14.85%|
|controlled|10.67%/12.39%|0.14%/0.21%|10.27%/15.11%|

## Cold 与恢复

48 次冷请求、并发 24：总批次耗时 391.25 ms，只有 1 次全量 PG init 查询，所有请求同一 generation。这个数是整个批次耗时。独立单次冷请求 80.32 ms，PG 执行 7.35 ms，初始化 Lua 50.343 ms（Redis SLOWLOG，仅保存耗时，不保存命令载荷）。冷初始化一次原子发布会占用 Redis 主线程约 50 ms；应避免大量场次同时冷启动。

init-race.json 使用真实 PG 捕获 5000 行后，在 Redis 发布前执行 Hold 和正式库存写入，验证最新 Hold 导入、初始化中 outbox 保留与发布后版本收敛。fault-and-cold.json 包含 projector 在 apply 后/ack 前退出 86、initializer 在 PG 后/publish 前退出 87、Redis outage/restart/FLUSH、PG rollback；恢复均通过。fault 测试专用 init lease=2 s，默认仍为 15 s。

## 验收与复现

- final-tests.json 与 *-final.log：CTest 31、Vitest 188、performance unit 211、migration 5、Redis 11、API 7、refund verifier 3。
- playwright.json：真实浏览器 2/2；覆盖跨区选择、A/B ownership、release、自然 TTL 到期、Confirm、simulation pay、cancel、BUYER refund，无页面 reload。browser-zone.png 是实际截图。
- phase14-and-expiry.json：真实 HTTP 创建订单、worker 自然处理到期、Delta 释放和原 Phase14 verify_run；verifier.json：PG/Redis formal/version/members/summary/hold/业务不变量全为 0。
- API 测试写入 12000 条变化触发真实 approximate MAXLEN 裁剪，验证长度 <=10100、旧游标 reset 和精确状态；1002 事件验证分页、去重与 cursor。

在已按实施文档准备的 Phase16 隔离容器中，从独立工作树运行：

```powershell
python backend/tests/phase16_migration_test.py
python backend/tests/phase16_read_model_test.py
python backend/tests/phase16_api_test.py
python performance/scripts/phase16_system_test.py
python performance/scripts/phase16_init_race_test.py
python performance/scripts/phase16_final_gates.py
python performance/scripts/phase16_degraded_confirm_test.py
python performance/scripts/phase16_benchmark.py
python performance/verification/phase16_verify.py
```

故障脚本只用于本轮命名的 phase16-api-* 独立容器，会停止/启动服务并清空该测试 Redis。不要指向既有 main 或生产容器。真实浏览器的测试密码从现有 auth_test_support 在运行时注入 PHASE16_TEST_PASSWORD，仓库不保存认证 cookie、trace 或新增明文凭据。

这是共享主机、短窗口、单场次的特征测试，不是生产 SLA、最大容量、长稳测试或 Redis Cluster 验证。未执行真实 Stripe 资金动作；本轮支付/退款浏览器验证使用真实后端 simulation provider。

停机期间真实 Confirm 成功与恢复见 degraded-confirm.json。停机时临时 Hold finalize 失败可能保留原 key 至 TTL，正式状态始终优先；测试清理按原 owner 显式释放自身 key。

交付日志只规范化行尾空白与末尾空行；Playwright 报告移除了宿主机环境变量，测试结果、数值和时间线未改。
