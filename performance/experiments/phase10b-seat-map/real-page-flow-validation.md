# Phase10B-3.5：真实选座页面请求模型验证

## 结论

本轮确认前端已经真实接入 Static Layout 与 Dynamic Availability，且完整 Page Entry 单项在
10、30、60 次页面进入/秒下均通过。但新版 Mixed Read 2× 在固定 4-worker / queue16 下出现
69 次 compute rejection 和 HTTP 503；最终真实后端 Playwright 复验还暴露出 5,000 座页面中前排
座位可能落在可视区域之外、无法由普通点击选择的问题。因此 **Phase10B-3 本轮不封板**。前者不是
PostgreSQL 权威数据损坏，而是完整页面进入中的 Layout 与持续 Availability refresh 共享 executor 后，
组合压力比上一轮仅测 Availability 的 Mixed Read 更早触及计算容量边界；后者属于前端修复任务，
本轮按范围约束只保留证据，不修改前端。

本轮没有修改 `frontend/` 或 `backend/`，没有通过扩 worker、扩 queue、扩连接池、缓存或 Delta
隐藏结果。完整机器可读证据见 `real-page-flow-browser.json` 与
`real-page-flow-measurements.json`。

## Git 与前端接入核对

开始时分支为 `main`，HEAD 为 `f18d34cc10bf1b53f0e031e7335afb1e7447a0d9`，
`origin/main` 为 `ca772d08eb0a4cb377a7898acf97b104a5dace20`，工作区 clean，fetch 后远端未前进。
前端提交只修改 frontend、真实 E2E 和前端契约文件，没有修改 backend 或 performance。

源码与测试确认：选座页先取 Session，再用 `Promise.all` 并行取 Event、Layout 和无上下文
Availability；Layout 顶层 `sessionId` 在 API 边界补入内部 SeatStatic；两个数组按 Seat ID 合并；
`refreshSeats()` 只取 Availability；CheckoutSession ID 只传给 Availability；刷新或合并失败时不覆盖
最后成功快照。OrderPage 仍使用 legacy `getSeats()`。

## 浏览器真实请求图

独立 Playwright 记录器驱动真实前端、Performance Backend、PostgreSQL 和 Redis。匿名首次进入的
Seat Map 读取为 Session 1 次、Event 1 次、Layout 1 次、Availability 1 次、legacy 0 次。

登录用户首次进入同样只读取一次 Layout。选择第一座后发生一次 `POST /checkout-sessions`，随后只新增
一次带服务端返回 CheckoutSession ID 的 Availability；累计 Layout=1、Availability=2。再选择第二座时
发生一次 `PUT /checkout-sessions/{id}/seats`，随后只新增 Availability；累计 Layout=1、
Availability=3，legacy 始终为 0。记录器以 method 与完整 path 区分 Checkout 的 `/seats` 写入和 legacy
Seat Map 读取。浏览器证据只证明真实请求顺序，不用于制造容量压力。

恢复已有 CheckoutSession 时，源码顺序是初始无上下文快照完成后读取 CheckoutSession，验证当前用户和
场次，再以该 ID 刷新 Availability。当前页面没有固定时间轮询；本轮没有编造轮询频率。

## 完整 Page Entry workload

每次迭代严格执行：

```text
GET /sessions/{sessionId}
        ↓ 解析 eventId
并行 GET /events/{eventId}
     GET /sessions/{sessionId}/seat-layout
     GET /sessions/{sessionId}/seat-availability
        ↓
以 Seat ID 验证 5,000 个 Layout/Availability identity 完整一致
```

只有四个请求全部成功、Event/Session identity 一致、Layout 精确字段正确且 Availability 状态精确时，
才计一次页面成功。页面到达率不是 HTTP 请求率；下表 `HTTP requests` 包含压力请求及每轮 4 个 preflight。

| Hold | Page entry/s | 页面完成/成功 | HTTP requests | 组级 p50/p95/p99 ms | Session p95 | Event p95 | Layout p95 | Availability p95 | 结果 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 0% | 10 | 151/151 | 608 | 56/79/84 | 7.06 | 1.27 | 26.48 | 17.32 | stable |
| 90% | 30 | 450/450 | 1,804 | 51.5/90/103 | 8.57 | 1.39 | 32.49 | 27.94 | stable |
| 90% | 60 | 900/900 | 3,604 | 74/133/157.01 | 15.05 | 6.84 | 55.34 | 50.98 | stable |

60 page entry/s 对应压力区间约 240 HTTP requests/s。该轮 dropped、system error、unexpected、503、
degraded、invalid、compute reject 均为 0；逐页面均精确得到 4 个响应和可按 ID 合并的 5,000 个座位。
采样峰值为 active=4、queue=1、Seat Map in-flight=4，结束后归零。compute queue wait p95=17.54ms，
execution p95=49.12ms。

60/s 的阶段 p95：Layout DB/materialize 22.49ms、Layout JSON 9.52ms、Availability DB/materialize
15.21ms、Redis lookup 19.78ms、overlay 0.96ms、Availability JSON 4.49ms。PostgreSQL 中每个正式
Page Entry 对应一次 Session、Event、Layout 和 Availability 查询；Layout/Availability 各 901 次（含
preflight），没有写入正式库存。

## Layout 复用与累计传输

以下使用同一后端、5,000 Seat 的真实 response size。首次拆分的 raw JSON 略小，但 gzip 合计更大；
因此不能称为“首次加载流量下降”。后续每次交互只增加 Availability，累计收益从刷新后出现。

0% Hold：

| 时点 | Legacy raw/gzip | Split raw/gzip |
|---|---:|---:|
| 首次进入 | 822,421 / 44,086 | 807,512 / 54,473 |
| 选择一座后 | 1,644,842 / 88,172 | 1,072,558 / 67,439 |
| 再选择第二座后 | 2,467,263 / 132,258 | 1,337,604 / 80,405 |

90% Hold：

| 时点 | Legacy raw/gzip | Split raw/gzip |
|---|---:|---:|
| 首次进入 | 799,921 / 42,236 | 785,012 / 54,723 |
| 选择一座后 | 1,599,842 / 84,472 | 1,027,558 / 67,939 |
| 再选择第二座后 | 2,399,763 / 126,708 | 1,270,104 / 81,155 |

三个时点来自受控两座交互，用于解释复用收益开始出现的位置，不代表线上用户一定选择两座或固定刷新三次。

## Hold 与身份正确性

0% Page Entry 151 个页面组全部精确；90% Page Entry 和 Mixed 中，每个成功 Availability 响应均严格为
4,500 HELD、500 AVAILABLE、0 SOLD。所有运行 degraded=0、invalid=0，Redis timeout/error/
parse_error 均为 0。浏览器创建的合法 CheckoutSession 后，带正确 ID 的 Availability 保持 own Hold
显示语义；既有 Seat Hold 集成回归继续覆盖匿名、他人、伪造和跨场次 ID 不能获得 own 视图。

数组顺序从未作为正确性条件；k6 和前端均以 Seat ID 合并。

## 新版 Mixed Read

模型保留独立 Public 与 warm Auth 场景，并把旧 Seat Map 场景拆成完整 Page Entry 与页面进入后的
Availability refresh。基准档为 Public 100/s、Auth 100/s、Page Entry 15/s、refresh 60/s；2× 等比例
变为 200/200/30/120。Page Entry 自身也包含一次 Availability，因此总 Availability 压力分别为
75/s 和 150/s。这个比例是受控回归模型，不是线上用户行为统计。

| 档位 | 业务 | 目标 | 完成/成功 | p50/p95/p99 ms |
|---|---|---:|---:|---:|
| 1× | Public | 1,500 | 1,502/1,502 | 0.96/7.12/14.27 |
| 1× | Auth | 1,500 | 1,502/1,502 | 1.45/13.92/31.43 |
| 1× | Page Entry | 225 | 226/226 | 56/175.75/217 |
| 1× | Availability refresh | 900 | 900/900 | 17.32/48.60/83.78 |
| 2× | Public | 3,000 | 3,002/3,002 | 2.65/28.71/50.96 |
| 2× | Auth | 3,000 | 3,002/3,002 | 10.68/43.61/63.70 |
| 2× | Page Entry | 450 | 451/437 | 172/491/602 |
| 2× | Availability refresh | 1,800 | 1,801/1,746 | 75.50/177.73/224.59 |

1× 共 4,813 个 HTTP 请求，所有硬门槛通过，compute accepted=1,355、reject=0，queue 采样峰值=0、
active=3，queue wait p95=1.85ms。2× 共 9,614 个 HTTP 请求，没有 dropped iteration，但出现 69 个
HTTP 503/system error，与 compute rejected=69 一致；Page Entry 失败 14 组，独立 refresh 失败 55 次。
Public/Auth 没有失败，分类指标没有被全局 p95 掩盖。

2× 的 compute active 达到 4；1 秒级采样看到 queue 峰值 7，但发生 rejection 证明更细粒度瞬间已经触及
queue16。queue wait p95=90.29ms、execution p95=48.04ms。Availability Redis lookup p95 上升至
134.21ms，但 timeout/error/parse error 仍为 0。Layout DB/materialize p95=24.61ms，Availability
DB/materialize p95=22.56ms；PostgreSQL verifier 仍通过。

4× 会形成 Page Entry 60/s 加 refresh 240/s，即总 Availability 300/s，已达到上一轮明确 first observed
unstable；由于 2× 已经失稳，本轮未执行 4× 或 8×。

## 系统资源与权威数据

Page Entry 10/30/60、Mixed 1×/2× 运行在同一未重启 Backend 容器，RestartCount=0。Backend cAdvisor
30 秒 CPU rate 峰值依次约 0.31、1.00、2.34、1.40、2.89 cores；working set 峰值依次约
89.5、100.0、122.4、126.7、159.1MiB。因为这是连续 warm 进程且没有冷启动对照，本轮不能证明或排除
内存泄漏。

稳定轮次 Redis client omem/oll 采样峰值均为 0。Mixed 2× 出现短时 omem 峰 1,408,704 bytes，结束后
connected client 的 recent max output buffer 为 0，所有 Seat Map/HTTP in-flight 和 compute active/queue
均归零，没有 Redis timeout。该现象记录为过载轮次资源证据，不描述为持续 Redis 积压。

每个正式运行都执行现有 14 项 PostgreSQL 权威不变量验证，全部 violation_count=0；目标 Performance
Session 的正式库存运行前后均为 AVAILABLE=5,000。读取压力没有改变 Reservation、Order、
PaymentAttempt、Refund、Notification 或正式 Seat 所有权。

## 回归与封板判断

前端 Vitest 9 files/50 tests、`vue-tsc -b` 和生产构建通过；Frontend Mock Playwright 4/4 通过。
根目录真实 E2E 在旧卷上首次因历史幂等数据命中 PAID/EXPIRED 而 1/4，通过安全 guard 仅重建三个
`ticketing_phase10a_*` 卷后曾 4/4 通过。最终以同一 5,000 座 Performance 数据集复验时为 2/4：
checkout-smoke 在点击 `R001-004` 时超时，失败截图显示一行 500 个座位被居中后，当前可视区域从约
243 号座位开始，目标前排座位处于视口外；multi-client 随后也超时。该不一致不满足“所有真实 E2E
回归通过”的封板门槛，且本轮没有修改前端。上述 reset 没有清理用户标准开发卷。

Performance Python 101/101、Backend CTest 23/23、Read API 4/4、Seat Hold 11/11、Checkout 6/6、
Auth 7/7 均通过。数据库 verifier 的 14 项不变量全部 violation_count=0，observability verifier 为
PASS；真实后端 Playwright 的最终结果则如上为 2/4，并非全部通过。

Phase10B-3 的前端接入、真实请求图、Page Entry 60/s 单项和数据正确性已经被证明，但新版 Mixed 2×
存在未解释为可接受行为的 69 个系统拒绝，且 5,000 座真实 UI 回归未全部通过，不满足封板条件。
因此当前结论是：

```text
Phase10B-3：尚未封板
阻塞证据 1：固定 4/16 下真实组合 Mixed Read 2× 出现 69 次 compute rejection / HTTP 503
阻塞证据 2：5,000 座真实后端 Playwright 最终复验 2/4，前排座位可能处于不可点击的视口外区域
```

这不推翻 Availability 单项最高已验证稳定 200/s，也不能把 200/s 扩大成整个系统容量。下一任务应先审查
真实 Page Entry 与 refresh 组合的容量预算和资源隔离取舍；本轮不实施 Delta、缓存、WebSocket、扩池、
Waiting Room、zone 分区或其他优化。
