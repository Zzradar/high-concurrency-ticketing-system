# Phase17 管理员活动发布与场馆座位配置

本阶段使用 `phase17/admin-event-publishing`，工作树 `D:\Documents\vscode\high-concurrency-ticketing-system-phase17`。固定基线 `1d7194d0aac708592e52a1d59fb642c21ce7554e` 包含 Phase15 最终提交 `8e86a40ba3a5177e1738be81f5608e26c085851e`。第一批 `ce7e952a12771f9f8551ae9a964fe81c4a72fe2b` 已验收，本轮从该 clean HEAD 继续；未改写提交、修改旧 migration 或操作 main/旧 Phase16 工作树。

## Schema 与认证

新增 migration **012_add_admin_event_publishing.sql**，旧 001–011 不变。Seed、所有 Compose initdb、Phase11/12/14/15/16 夹具和性能生成器同步更新。

- `app_users.role` 仅 CUSTOMER/ADMIN，默认 CUSTOMER。UserRecord、AuthSessionRecord、AuthContext、登录和 `/auth/me` 传播 role。
- Redis role 严格解析，缺 role 的旧缓存当作 miss；cache hit 在既有一次 PG active 校验中取得当前 role，数据库降权后的下一请求即失去 ADMIN 权限，不增加第二次查询。
- Venue → venue_zones → Seat 是唯一权威，已删除 seats.zone。旧区域按首个真实 row_no/seat_no/名称确定性排序回填，名称保留。
- Seat 的 zone_id 必填，复合外键保证同 Venue；位置和 label 唯一性包含 Zone，两个 Zone 均可有 A001。
- Event/Session 增加 DRAFT；Event 有 published_at/published_by；session_zone_prices 保存草稿区价，正整数分与复合外键保证金额和场馆一致。
- Demo 的 ADMIN 与 CUSTOMER 登录配置以 `backend/db/seeds/001_demo_seed.sql` 为准，**仅供本地演示**。不提供注册、角色管理、多租户或复杂 RBAC。

## Admin API

服务端 AdminFilter 强制认证和 ADMIN；所有写请求复用 Cookie Session、CSRF Cookie/Header 和 Origin 校验。匿名 401、CUSTOMER 403 ADMIN_REQUIRED、CSRF 失败 403 CSRF_INVALID。管理 DTO 与消费者 DTO 分离。金额为整数分，时间为带 Z/明确偏移的 ISO8601。

| 方法与路径 | 行为 |
|---|---|
| GET /admin/venues | 摘要数组，含 totalSeats、zoneCount、frozen |
| POST /admin/venues | 创建完整 Seat Plan，201 详情 |
| GET /admin/venues/{id} | Zone/Row 详情、实时 frozen |
| PUT /admin/venues/{id} | 未冻结方案全量替换，返回 pricingReset |
| GET /admin/events | 管理摘要数组，包含 DRAFT |
| POST /admin/events | 创建草稿，201 管理详情 |
| GET /admin/events/{id} | 管理详情、场次价格、venue 和 readiness |
| PUT /admin/events/{id} | DRAFT 全量编辑，有场次后不能换 Venue |
| PATCH /admin/events/{id}/display | 仅 name、description、category、coverUrl 部分修改 |
| POST /admin/events/{id}/sessions | 新增 DRAFT 场次，返回 Event 详情及 savedSessionId |
| PUT/DELETE /admin/events/{id}/sessions/{sid} | 修改/删除 DRAFT 场次 |
| PUT /admin/events/{id}/sessions/{sid}/prices | Zone Price 全量替换 |
| GET /admin/events/{id}/publish-preview | 一致只读快照下的 readiness |
| POST /admin/events/{id}/publish | 原子发布或幂等已发布结果 |

Seat Plan 输入示例：

```json
{"name":"演示馆","city":"成都","zones":[{"code":"FLOOR","name":"内场","rows":[{"label":"A","seatCount":50}]},{"code":"STAND","name":"看台","rows":[{"label":"A","seatCount":50}]}]}
```

Zone 数组顺序成为 sort_order；code 使用大写字母/数字/下划线。拒绝重复 code/name、区内重复行、空值、错误类型、未知字段和越界总数。`custom_config.admin_catalog` 默认：32 区、每区 200 行、每行 500 席、每馆 20000 席、每活动 20 场；启动校验正整数及乘积溢出。集合式 jsonb_array_elements/generate_series 创建全部 Seat，ID 与显示 label 分离。

Event 输入为 name、description、category、coverUrl、venueId、salesStartsAt、salesEndsAt；Session 为 hallName、startTime、gateTime；Price 为 `{"prices":[{"zoneId":"...","price":10000}]}`。草稿允许缺价；价格拒绝重复/外馆 Zone、非正整数和 int64 溢出。入场早于开始，开始晚于活动开售。

未冻结替换持有 Venue 行锁，清空相关 DRAFT 场次价格，实际清过价格返回 pricingReset=true。任意正式 SessionSeat 存在即 frozen，拒绝继续替换。主要错误：404 VENUE_NOT_FOUND/EVENT_NOT_FOUND/SESSION_NOT_FOUND；409 VENUE_SEAT_PLAN_FROZEN/EVENT_NOT_EDITABLE/SESSION_NOT_EDITABLE/EVENT_VENUE_LOCKED/EVENT_NOT_PUBLISHABLE；400 INVALID_ARGUMENT；有界管理队列满 503 ADMIN_BUSY。

## Preview 与原子发布

Preview 返回 publishable、sessionCount、expectedSessionSeatCount、venue、各场 configuredZones/requiredZones 和 issues[{code,message,sessionId?,zoneId?}]。问题代码包括 NO_SESSIONS、VENUE_EMPTY、EVENT_WINDOW_ENDED、SESSION_START_NOT_FUTURE、SESSION_GATE_INVALID、SESSION_WINDOW_EMPTY、ZONE_PRICE_MISSING、ZONE_PRICE_INVALID、SESSION_VENUE_MISMATCH。

Publish 在独立有界管理执行器中执行 PG transaction：Event FOR UPDATE → Venue FOR UPDATE → 锁内重新读取/校验 → 一条 INSERT SELECT 生成所有 SessionSeat → 验证 affectedRows → Session/Event 变为 ON_SALE、写审计、按真实 Session 时间推导北京时间 date_range → COMMIT。只有提交回调成功才回复。

Session/Price 变更也先锁 Event 再锁 Venue；Seat Plan 只锁 Venue，不反向锁 Event。并发发布返回一个 PUBLISHED_NOW、一个 ALREADY_PUBLISHED，库存不重复。发布和替换并发只能一方成功：替换成功清价后发布失败，或发布成功后替换被 frozen 拒绝。Event 更新故障会回滚库存、状态与审计。返回包含 event 和 inventory{sessionCount,seatCountPerSession,sessionSeatCount}。

发布事务不写 Redis，不依赖预热，Redis 停机时发布测试通过；消费者首次读取再由 Phase16 派生缓存。发布后只允许纯展示字段修改，场馆方案、活动 Venue/售票窗口、Session 和 Price 冻结。不建设动态图形编辑器、动态票价或多租户。

## 公共隔离与管理前端

公共 Event/Session 列表隐藏 DRAFT，猜测 Event/Session/Seat/Availability ID 返回 404；所有预订/Checkout 入口保留公开状态和 Phase15 半开售票窗口校验。Zone 公开字段仍是 name，排序使用 sort_order。即使 Redis 已 ready，Phase16 仍先检查 Session/Event 可见性，因此 no-change Delta 有一次小型 PG 可见性查询，但没有全场 Seat/库存查询。

ADMIN 账户菜单入口及路由守卫只作导航辅助；四个管理页复用 Axios Cookie、CSRF、401 和错误归一化。支持结构化行编辑、连续字母行生成、场次/区价、Preview/Publish；frozen、pricingReset、结构化 issues 可见。时间工具将 datetime-local 按北京时间解释并转 UTC，有无效日期/跨日测试。真实演示连接后端，没有完整 Mock Admin 数据库。

## 实际验证（2026-09-12）

| 门禁 | 结果 |
|---|---|
| Release C++20、BUILD_TESTING=ON、完整普通 CTest | 34/34 |
| 完整 Vitest、frontend production build | 203/203（25 文件）、通过 |
| performance Python unit | 233/233 |
| Phase17 migration011 升级/fresh Compose/约束/回填 | 6/6 |
| role/cache/RBAC/CSRF/Zone HTTP | 5/5 |
| Admin Venue 真实 HTTP/PG | 4/4 |
| Publish/并发/回滚/隔离/Redis 停机/动态过期 | 9/9 |
| Verifier PG 回滚反例 | 3/3 |
| 独立 Phase17 Playwright | 5/5 |
| Phase11 Stripe/crash + Phase12 buyer refund | 11/11 + 11/11 + 38/38 |
| Phase15 migration/read/reservation/checkout/observation | 4/4 + 2/2 + 4/4 + 7/7 + 2/2 |
| Phase15 formal commit 后真实退出恢复 | 1/1，退出码 88，复用原订单 |
| Phase16 PG/Redis Lua/HTTP | 5/5 + 11/11 + 7/7 |
| Phase16 真实故障 | 48 请求/24 并发冷初始化仅 1 次完整 PG；退出 86/87、重放、停机、清空、回滚通过 |
| Phase14 G0/U1/U2 | functional smoke/correctness 通过，delivery errors 为空 |
| Phase17/Phase15/Phase16/原 verify.sql | 全部 0 违规 |

Playwright 使用本轮 UI 动态库存，消费者无需重启看到发布并完成 hold、confirm、模拟支付、全额退款、取消。过期由另一动态订单的真实 HTTP/PG 测试覆盖；动态活动也验证 NOT_STARTED 自然跨入 OPEN 后可以购买。退款后取消场景使用新浏览器会话，保留既有 sessionStorage 恢复已确认订单语义。

Phase14 原 verdict 保留：smoke measurement_validity 为 fail（local_characterization_only），capacity/overload 不适用；只声称 functional smoke 和数据库 correctness 通过，不把 formalRecovery 诊断当正式性能结论。Phase11/12 使用本地 Fake Stripe，没有生产支付。

## 5000/10000 席规模特征

本机 Docker Desktop、PG16、Redis7.4，5 Zone、1 Session，顺序 HTTP；未调大 pool 或 SeatMap worker/queue。Venue/Publish 各 1 样本；Layout/Snapshot/Delta 各 20，冷初始化 1，浏览器 5。原始样本和 SQL 增量在 performance/experiments/phase17-admin-publishing。

| 指标 | 5000 | 10000 |
|---|---:|---:|
| Venue HTTP ms | 281.323 | 523.813 |
| Venue 业务 SQL / Seat INSERT 次数 | 4 / 1 | 4 / 1 |
| Publish HTTP ms | 230.561 | 486.563 |
| Publish 业务 SQL / 库存 INSERT 次数 | 15 / 1 | 15 / 1 |
| 实际 SessionSeat 数 | 5000 | 10000 |
| Layout p50/p95 ms | 59.011 / 64.846 | 105.022 / 117.024 |
| Layout JSON/gzip bytes | 824766 / 31732 | 1653966 / 63183 |
| 冷 Snapshot HTTP ms | 128.123 | 235.197 |
| 完整冷 PG 查询 ms / 次数 | 12.747 / 1 | 29.954 / 1 |
| 冷请求 Redis EVAL ms | 12.280 | 19.446 |
| 热 Snapshot p50/p95 ms | 29.839 / 32.518 | 42.702 / 47.160 |
| no-change Delta p50/p95 ms | 4.735 / 21.249 | 15.622 / 17.263 |
| 20 Delta 的全场库存/可见性查询数 | 0 / 20 | 0 / 20 |
| 浏览器 navigation 至两次 RAF p50/p95 ms | 400 / 470 | 598 / 653 |
| 当前 Zone DOM Seat 数 | 1000 | 2000 |

业务 SQL 由 pg_stat_statements 指纹归类，不含认证、事务控制和后台扫描；原始增量保留这些干扰，不能直接求和冒称单请求 roundtrip。Redis 时间来自 SLOWLOG；gzip 是本地压缩大小，未声称实际传输编码。浏览器时间包含网络和 Vue 更新，不是纯 CPU 时间。短样本、共享主机有波动，这些是数据规模特征，**不是生产 SLA 或并发容量**。

同一旧 5000 席夹具对照：现存 phase15-current:local（包含 Phase16，镜像 SHA 见 layout-comparison.json）Layout p50/p95=42.162/60.735 ms，当前=46.466/60.805 ms，两者 JSON=509646、gzip=28706 bytes。该镜像不是本轮固定 baseline SHA 重新编译，只作迁移前同规模参考。动态数据 ID/label 更长，不用不同 payload 的时间差推导 JOIN 成本。

## 复核与隔离

主环境 phase17-postgres/phase17-redis/phase17-build（HTTP18117）；支付隔离项目 phase17-phase12（18127/18128）；G0/U1/U2 为 phase14-phase17-current（18137）。故障适配只映射进程、端口和目录；原 Phase16 断言保留，SQL 计数指纹改为 Zone 排序后的真实语句。旧阶段 evidence 未覆盖。

仓库根目录运行 Python，frontend 目录运行 Playwright。各 PHASE15/16/17 BASE_URL、POSTGRES_CONTAINER、REDIS_CONTAINER 指向专用环境；迁移测试还读取 PG_CONTAINER。执行记录在同名 txt/JSON 文件。

```text
python -m unittest discover -s backend/tests -p phase17_schema_test.py -v
python -m unittest discover -s backend/tests -p phase17_http_test.py -v
python -m unittest discover -s backend/tests -p phase17_venue_test.py -v
python -m unittest discover -s backend/tests -p phase17_publishing_test.py -v
python -m unittest discover -s backend/tests -p phase17_verifier_test.py -v
python -m unittest discover -s backend/tests -p phase17_crash_test.py -v
python performance/scripts/run_phase17_phase16_faults.py
python performance/scripts/run_phase17_regression.py current
python performance/scripts/phase17_scale.py
python performance/scripts/phase17_layout_comparison.py
python performance/verification/phase17_verify.py
python -m unittest discover -s performance/tests -v
npm --prefix frontend run test -- --run
npm --prefix frontend run build
npx playwright test -c playwright.phase17.config.ts
ctest --test-dir /phase17-build --output-on-failure
git diff --check
```

Role HTTP probe 只在 TICKETING_PHASE17_EXTERNAL_TESTS=ON 测试构建存在；最终普通构建不含 probe。故障 runner 拒绝未知同名容器，重复运行应选择/准备新的专用环境。Scale 脚本顺序创建新数据；基线对照脚本拒绝覆盖同名数据库。

最终普通 push、完整提交 SHA 和 clean/ahead/behind 以会话报告为准。分支不会自动 merge main，不创建 PR。
