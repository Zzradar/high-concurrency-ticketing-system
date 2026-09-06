# Phase10B-3.3：静态 Layout 与动态 Availability 拆分

## 目标、口径与外部校准

旧 `GET /sessions/{sessionId}/seats` 每次状态刷新都会重复做完整
`session_seats JOIN seats`、完整 Seat DTO/JSON 和 gzip。Phase10B-3.3 将首次加载所需的静态描述与
高频变化的展示状态拆开，同时保留旧接口兼容。性能比较的含义是“页面已有 Layout 后的旧 full refresh
与新 Availability refresh”，不是把只取 Availability 描述成完整首次加载。

官方资料只用于职责校准，没有照搬其数据模型：pretix 分别提供
[Seating plans](https://docs.pretix.eu/dev/api/resources/seatingplans.html) 与
[Event/Subevent seats](https://docs.pretix.eu/dev/api/resources/seats.html)，Seat 含 zone/row/number 且动态占用与
订单、购物车相关；Ticketmaster 分别提供
[静态 Event Seatmap](https://developer.ticketmaster.com/products-and-docs/apis/international-discovery/v2/)
与 [Availability API](https://developer.ticketmaster.com/products-and-docs/apis/partner/availability/)，并明确
Availability 展示数据不应代替进行中交易的最终裁决；Eventbrite 的官方 API 也把
[Seat Map](https://www.eventbrite.com/platform/new/api) 建成独立资源。本轮没有引入缓存、pagination、
zone filter、delta、WebSocket 或第二个 executor。

本轮固定 `seat_map_compute_workers=4`、queue=16、PostgreSQL pool=4、Seat Hold Redis pool=2、
timeout=0.4s、browser-equivalent gzip。拆分前使用
`post-offload-capacity-measurements.json` 的同机 historical controlled evidence：该证据对应拆分前
callback-offload 源码/镜像；拆分后所有容量轮次使用同一个未重启 backend 容器
`8b1b2611c0fd...`、镜像 `sha256:aa359ea9ae8...`、RestartCount=0。运行期间出现的 Git HEAD
差异只来自并行前端提交，后端源码和运行镜像没有改变。

## API 与实现

新增公开 `GET /sessions/{sessionId}/seat-layout`：

```json
{"sessionId":"ses-concert-1001","seats":[{"id":"...","label":"A01","row":"A","number":1,"zone":"星光区","price":128000}]}
```

它不接受或使用 `checkoutSessionId`，不读 Redis，不返回 `status`，每个 Seat 不重复 `sessionId`。
SQL 只选 `inventory.id / seat_label / row_no / seat_no / zone / inventory.price`，仍按
`row_no, seat_no, inventory.id` 排序。DB callback 将 Drogon Result 复制为 owned `SeatLayoutRow`，
随后把 DTO、JSON 和 Response 构造提交给既有有界 executor；没有让 Result 跨 callback，也没有新线程池。

新增 `GET /sessions/{sessionId}/seat-availability?checkoutSessionId=...`：

```json
{"sessionId":"ses-concert-1001","seats":[{"id":"...","status":"AVAILABLE"}]}
```

SQL 是 `SELECT id, status FROM session_seats WHERE session_id=$1 ORDER BY id ASC`，**不 JOIN seats**。
DB callback 只物化 owned `SeatAvailabilityRow` 与 Seat ID；Redis callback 只保留 ownership-safe owners，
overlay、Availability DTO、JSON 和 Response 构造进入同一个 4/16 executor。Layout 与 Availability 顺序
可以不同，page-entry 测试以 Seat ID merge。

legacy `/seats` 的 path、数组响应和全部字段保持不变。legacy 与 Availability 都调用同一纯函数：正式
`HELD/SOLD` 不变；只有正式 `AVAILABLE` 被叠加，自己 CheckoutSession 的 Hold 显示 AVAILABLE，其他
Hold 显示 HELD。Controller 复用同一认证 Cookie、`findByIdForUser` 所有权和 Session 匹配检查；匿名、
伪造他人 ID、自己的跨 Session ID 都降级为无 own context，不泄露 owner。Redis failure 仍返回 PostgreSQL
正式状态。两个新接口对缺失 Session 返回 `404 SESSION_NOT_FOUND`，存在但无 Seat 返回顶层对象加空数组。
所有三条 route 的 executor 拒绝都返回原有 `503 SEAT_MAP_BUSY`。

新增低基数阶段：`layout_db_fetch_and_materialize`、`layout_json_build`、
`availability_db_fetch_and_materialize`、`availability_redis_lookup`、`availability_overlay`、
`availability_json_build`；三条 route 共用原 queue depth、active worker、accepted/rejected、queue wait、
execution 与 in-flight 指标，没有 ID 类 label。

## 响应体实测

同一 5,000 Seat 数据集，identity 与 gzip 解压正文逐字相同：

| 响应 | raw bytes | gzip bytes |
|---|---:|---:|
| legacy full，0% Hold | 822,421 | 44,086 |
| legacy full，90% Hold | 799,921 | 42,236 |
| Layout | 542,466 | 41,507 |
| Availability，0% Hold | 265,046 | 12,966 |
| Availability，90% Hold | 242,546 | 13,216 |

legacy 90%、Layout、Availability 90% 在实现后又通过真实 HTTP 探针复测，结果分别为
799,921/42,236、542,466/41,507、242,546/13,216 bytes。

## Full refresh Before 与 Availability After

拆分前 full `/seats` 的 controlled baseline：60/s 在 0% 和 90% 都三次稳定；100/s 两次均失稳。
0% 100/s 的代表轮次 HTTP p95 313.08ms、queue wait p95 246.59ms、execution p95 96.07ms、
queue/active=16/4、reject=389。90% 100/s 的两轮 reject=367/394。Redis timeout 始终为 0。

拆分后 Availability（15s；iterations 不含 setup）：

| Hold | rate/s | iterations | HTTP p50/p95/p99 ms | exact | reject | queue 峰值 | 结论 |
|---:|---:|---:|---|---:|---:|---:|---|
| 0% | 60 | 900 | 15.73/19.78/29.70 | 900 | 0 | 0 | stable |
| 0% | 100 | 1501 | 15.94/25.87/31.32 | 1501 | 0 | 0 | stable |
| 0% | 150 | 2251 | 17.28/32.49/42.52 | 2251 | 0 | 0 | stable |
| 0% | 200 | 3001 | 21.76/37.73/45.05 | 3001 | 0 | 0 | stable |
| 0% | 300 | 4500 | 92.76/126.34/139.10 | 3465 | 1035 | 16 | **unstable** |
| 90% | 60 | 901 | 17.15/22.26/29.30 | 901 | 0 | 0 | stable |
| 90% | 100 | 1500 | 17.74/29.14/35.37 | 1500 | 0 | 1 | stable |
| 90% | 150 | 2251 | 19.32/36.13/42.94 | 2251 | 0 | 0 | stable |
| 90% | 200 | 3000 | 36.93/66.33/85.78 | 3000 | 0 | 2 | stable |

每个 stable 轮次 dropped/system_error/unexpected/degraded/invalid/503 均为 0，正式库存前后都是
AVAILABLE=5000，Database verifier 14/14。90% 的每个成功响应严格为 4500 HELD、500 AVAILABLE、
0 SOLD；Redis timeout/error/parse_error 全为 0。新 highest observed stable 是 **200/s**，新 first
observed unstable 是 **300/s**；300/s 时 active=4、queue=16、queue wait p95=97.45ms、
execution p95=38.80ms。到达首个明确失稳后没有继续 400/500/600。

100/s 公平对比中，DB fetch/materialize p95 从 full 24.18ms 降到 Availability 9.85ms，PostgreSQL
语句 mean 从 10.03ms 降到 4.54ms；JSON build p95 从 47.85ms 降到 2.47ms；compute execution p95
从 96.07ms 降到 23.97ms；queue wait p95 从 246.59ms 降到 0.166ms，389 次拒绝降为 0。

## Layout、首次页面与 Mixed Read

Layout 10/s：151/151 exact，HTTP p50/p95/p99=22.63/25.50/27.17ms，queue peak=0；
Layout 30/s：451/451 exact，21.27/27.93/32.26ms，queue peak=0。30/s 的
layout DB fetch/materialize p95=11.96ms、layout JSON build p95=4.89ms、compute execution
p95=46.31ms。30/s 很健康，未继续寻找 Layout 单项极限，也未加入 Cache/ETag。

Page entry 每个 iteration 用 k6 batch 并行请求 Layout + Availability，并检查两个顶层 sessionId、
5,000 个唯一 Layout ID、Availability 状态以及按 ID 完整 merge：10/30/60 entry/s 分别完成
150/451/901，全部 exact、无拒绝；HTTP 全局 p95 分别 23.01/32.74/60.31ms。60 entry/s 约等于
120 HTTP req/s，queue peak=4、active peak=4、queue wait p95=21.02ms，结束后全部归零。

Mixed Read 2× 使用独立 Public 200/s、100 个预热 Session 的 Auth 200/s、Availability 150/s 场景。
Public 3001/3001，p50/p95/p99=0.96/7.24/14.69ms；Auth 3001/3001，
3.16/19.79/30.63ms；Availability 2251/2251 exact，19.36/57.92/70.83ms。dropped、503、
Redis failure、compute rejection 均为 0，queue peak=4。旧 full-seat Mixed2× 的 Seat 仅
875/2251 成功并有 1376 reject，因此拆分恢复了本轮 2× workload。

Mixed 4× 未执行：它会把 Availability 提到 300/s，而单项 300/s 已是明确 first unstable；8× 同样
未执行。没有为了扩大数字机械施压。

## 资源、正确性与边界

所有轮次最后 queue/active/in-flight、Redis omem/oll 都归零。稳定 90% 200/s 采样到短暂
Redis client omem 峰 432,656 bytes，结束为 0 且无 timeout；不能把它描述成持续积压。后端 working
set 在同一未重启进程的连续运行中从首轮峰约 68.95MiB 上升到 Mixed2× 峰 162.56MiB，最终约
159.83MiB；这是连续 warm/high-water 轨迹，没有独立冷启动对照，不能据此证明 leak 或精确归因。
300/s 的失稳直接证据仍是 4 workers + queue16 饱和和 1035 次 capacity rejection。

真实集成测试覆盖 Layout/Availability 精确字段、排序、404/empty、正式状态、own/other Hold、匿名伪造、
跨 Session checkout、Redis outage formal fallback 和 legacy contract。状态接口仍只是展示 Snapshot；
Confirm/Phase 3 PostgreSQL Transaction 才是最终交易裁决。

如果完整 `{id,status}` Snapshot 再成为瓶颈，下一候选是 Delta Availability/Snapshot Version；若用户只看
局部，则评估 zone/areaGroup loading；公共状态高度重复时再评估短时 Snapshot/singleflight；Layout
首次加载成为热点时再评估 Layout Cache/ETag。本轮均未实施，也未增加字段、pool、worker 或 queue。

完整 run、阶段 histogram、compute、时间线、PostgreSQL、Redis、容器资源和原始 run ID 见
`static-dynamic-split-measurements.json`；本报告不把 histogram bucket 插值称为逐请求 tracing。
