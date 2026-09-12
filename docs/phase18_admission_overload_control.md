# Phase18 准入与过载控制

本阶段默认 OFF。PostgreSQL 仍是销售窗口、DRAFT 可见性、库存状态、所有权、Reservation／Checkout／支付退款与幂等结果的最终权威。Redis 只保存临时资格、限流和派生读模型。没有新增活动级库存大锁、SSE、WebSocket、共享动态库存缓存或生产容量承诺。

## 策略与资格隔离

migration013 新增策略和审计；migration014 新增运行 generation 初始化标记及 SYSTEM 审计主体，旧 migration 不修改。缺失策略行返回合成 OFF、version=0、容量和 generation=null。首次保存才创建策略，不为历史活动批量填充容量。

| 模式 | 命名空间 | 消费者行为 |
|---|---|---|
| OFF | NONE | 保持已有业务流程，不要求排队，准入不强依赖 Redis |
| OBSERVE | SHADOW | 执行同样准入／限流计算和指标记录，消费者不被拦截 |
| PAUSED | FORMAL | 保留位置和已有活跃租约，暂停新增放行 |
| ENFORCED | FORMAL | 正式执行排队、资格和限流 |

目标不是 NONE 且命名空间不同就轮换 generation；首次创建也使用新随机 generation。PAUSED ↔ ENFORCED、同模式普通配置更新保留 generation；进 OFF 再启用不能复用旧资格。Shadow 和 Formal 双向切换均隔离。版本、generation、规范化审计在同一 PostgreSQL 事务中提交，HTTP 等待提交成功。OCC 失败和审计失败不产生部分更新。

ADMIN GET/PUT `/admin/events/{eventId}/admission-policy` 继续严格 AuthFilter、AdminFilter、Origin/CSRF；PUT 必填 expectedPolicyVersion。prequeueSeconds 0..86400、maxActiveUsers 1..1000000、admissionRatePerSecond 1..100000、leaseSeconds 10..3600；这些上限只是输入边界。HMAC 只从 `TICKETING_ADMISSION_HMAC_SECRET` 环境读取，至少 32 字节；非 OFF 缺密钥明确失败。前端严格验证返回的身份、枚举、整数和 nullable，不转换数组／字符串。OCC 冲突禁用旧表单，必须显式重载，不自动重试 PUT。

公共 Event/Session 仅附 required/state/prequeueStartsAt 三字段，不公开容量、内部速率、generation 或队列深度。启动或元数据未收敛时显示可恢复 UNAVAILABLE。

## Redis 模型与边界

每活动使用 SHA-256 event hash tag。runtime 和八个 generation 键由短 Lua 处理：prequeue、waiting、presence、active、heartbeat、sequence、release、pause。预排队 HMAC 稳定随机排序，开售后单调 FIFO；同用户同活动仅一个位置／一份有效资格。客户端不能提交身份、score 或时间，GET 只接受可选 queueGeneration，不创建位置、不续租。

租约／presence 和放行使用 Redis TIME、严格有界参数和 TTL。过早 heartbeat 不续写，过期不复活；expired cleanup 和放行每批有界。容量下降不驱逐当前活跃用户。Scheduler 用有界到期索引、每批最多 64 个活动；每活动 Lua 同槽，跨槽到期索引是独立幂等修复步骤。Redis 数据丢失通过持久初始化标记检测，OCC 轮换 generation 和 SYSTEM 审计后重建，旧客户端收到 RESET_REQUIRED。

Registry 上限 10000 活动、200000 场次，刷新默认 2 秒，快照超过 15 秒不再视为就绪；调度间隔 250ms。单实例管理提交后立即使本实例快照失效。多实例后台传播存在约 2 秒刷新窗口，进程暂停／后端延迟会扩大到失效界限；这不是线性一致的全局开关。Lua 版本栅栏阻止已投影的新版本被旧实例覆盖。两个真实 API／Scheduler 的同代并发测试通过，但本轮没有 Redis Cluster／Sentinel 或多机网络分区验证。

只读身份缓存仅用于准入状态、heartbeat 和正式 Availability 身份读取。稳定 GET 不产生认证 SQL；miss 合并上限 64 组、每组 8 个等待者，PG fallback 额度 2。禁用账号的轻读撤销可能延迟至缓存 TTL（240..300 秒），logout 显式失效；库存和金融仍执行严格认证。带已有 Checkout 的 Availability 保留额外严格认证 SQL，不宣称该成本消失。

## 请求分类、限流与恢复

Token Bucket 使用整数 milli-token、Redis TIME 和两个同槽 bucket（账号+活动+操作、活动+操作），全部允许才一起扣减，拒绝不部分扣费。容量／补充速率输入上限 1000000，elapsed 截断至一小时，TTL 最大一天。本版八类操作权重均为 1：ADMISSION_JOIN、ADMISSION_STATUS、ADMISSION_HEARTBEAT、AVAILABILITY_SYNC、CHECKOUT_CREATE、SEAT_REPLACE、CONFIRM、RESERVATION_CREATE。默认账号容量／速率 20/10，活动 200/100；都是演示配置，不是生产安全值。

| 结果 | HTTP | 附加字段 |
|---|---:|---|
| 无新购票资格 | 409 ADMISSION_REQUIRED | state、pollAfterMs、queueGeneration 等状态 DTO |
| 业务速率超额 | 429 RATE_LIMITED | 有限 scope、retryAfterMs、向上取整且至少 1 秒 Retry-After |
| 本地资源满 | 503 SYSTEM_OVERLOADED | 有限 resource、retryAfterMs、Retry-After |
| 正式准入无法安全判断 | 503 ADMISSION_UNAVAILABLE | 明确失败，不回退成 PG 库存计数器 |

本地 PUBLIC_STATIC_READ、ADMISSION、AVAILABILITY、INVENTORY_WRITE、RECOVERY、FINANCIAL、ADMIN 额度默认各 16，POSTGRES_FALLBACK 为 2；合法配置范围 1..256。所有模式都执行本地额度，不设长等待队列；shared RAII Permit 覆盖业务工作及异常／超时收口，恰好一次完成释放。内部准入执行器 4 个 worker／4 个在途上限。

Reservation 先恢复并校验已有幂等结果；新请求才走资格、限流和库存额度。Checkout 已有 RESERVED/SUBMITTING 确认、查询／恢复、abandon、空座位释放不要求新资格。订单、取消、支付、退款、Webhook 和对账不使用消费者排队或 bucket，只使用独立金融额度和原有权限／签名／幂等。PG 事务仍复查库存、时间、状态和固定锁序；Redis 在资格检查后失效或租约到期不会改变 PostgreSQL 的最终裁决。

库存额度拒绝、Reservation／Checkout 内部数据库失败触发按活动 5 秒冷却，Redis 标记 NX+TTL，重复拒绝不无限延长；Scheduler 冷却期间停止新增放行。当前保守地将这些路径的全部 InternalError 计入冷却，不仅识别超时；与管理员 PAUSED 分别记录。

Drogon 非 fast PG client 的 number_of_connections 是每实例总数，未按 HTTP loop 倍增：每实例 4，双实例 8，另留迁移、worker 和运维连接；没有提高 max_connections。Redis traffic_control 独立 2 条连接，原 seat_holds/auth_sessions 各 2 不变。认证阶段及后台任务仍共享 PG 资源，业务舱壁不等于数据库连接物理预留，更不保证任意洪峰下金融延迟。受控测试证明指定读／库存饱和场景下金融恢复成功、业务在途有界及回落；并未证明全站所有认证入口在无限并发下都可用。

## Layout 缓存和前端轮询

公开 Layout 首先通过 PostgreSQL 可见性校验，再以不可变发布／场次身份生成弱 ETag。精确、列表、弱、星号条件匹配时 304 空 body，不调用全量座位 SQL。普通 200 的座位顺序、价格和 JSON 形状不变。默认 public max-age=60、stale-while-revalidate=15，Vary: Accept-Encoding；无一年 immutable，无复制巨大 Redis JSON 或无界 LRU。DRAFT／不存在永不因 tag 命中返回 304。其他动态、私有及错误 API 默认 private/no-store。

Snapshot／变化 Delta 默认 pollAfterMs=2000，空 Delta=5000，degraded=10000，hasMore=0；六项 seat_read 配置严格校验。前端纯 policy 根据连续空／错误退避，上限 30 秒，扰动不早于服务端建议；Retry-After 秒数／HTTP 日期都验证并有界。上一请求完成才安排下一次，hasMore 串行让出任务后继续；无重叠 setInterval。真实 hidden 停止新请求，在途排空；恢复前台／focus 合并为一次权威快照。卸载、换场次、换身份和 logout 使旧响应失效。

Waiting Room 只有明确 POST 加入；显示“前方约 N 人”，不承诺 ETA。状态查询与 heartbeat 分别按服务端 pollAfterMs／heartbeatAfterMs 到期，不以 GET 推迟心跳。隐藏两者都停，恢复先 GET。ADMITTED 后结束等待页轮询，选座页只保留独立资格 heartbeat 和 Availability；RESET_REQUIRED 必须显式再加入。已有 Checkout 恢复面板不因资格丢失消失。站内目的地验证避免开放跳转；409／429／503 使用不同中文业务文案，购买 POST 无通用自动重试。

## 验证和证据

证据位于 `performance/experiments/phase18-admission-overload/capabilities/`，各能力批次与 OFF A/B 分开。Stage0 SUT 固定为 `ed51447154418e05ed9e4c49728f3eb114713db9`；交付原 Manifest SHA-256 `19f394034d74e027a19e62f3e61f2ab82c9806b542604d666dc24d948640f338`；baseline/manifest.json SHA-256 `c0891851436eb997e3414c4d2b6b5525a72c38b7fe635a9cb582e46d77b2e402`。不得把证据提交误写成 baseline SUT。

已验证全部模式转换、OCC／审计回滚、Lua 排序／FIFO／过期／并发、429 原子 bucket、读饱和和库存 DB timeout 冷却、两个真实 API 与调度器、真实 Edge 排队／Admin 流程，以及 Phase15/16/17 和原 Stripe／退款／崩溃套件。`phase18_verify.py` 只读检查审计链、命名空间与资格互斥／TTL；过期或 DRAFT 策略不要求有效 Redis 投影，当前容量下降也不被误当成驱逐要求。历史原始日志与源 hash 绑定；失败诊断均应标注 CLOSED，checkpoint 不是可部署版本。

Metrics 只用固定 mode/outcome/request_class/scope/resource/result_class。16 用户×8 活动 128 次加入后，Phase18 序列数八次均为 31。poll interval 是服务端最近建议值 Gauge，不是客户端实际间隔分布；实际间隔以浏览器请求时间线为准。到期计数当前合并 waiting presence 和 active lease。原生 91 秒 hidden 能力探针验证至少三个最长 30 秒周期无新 Availability；正式 A/B 仍保持冻结的 60/10/10 秒协议。

正式 after 必须从 clean 候选 SHA、全新 Release 构建运行冻结八份协议，固定 Edge 二进制／Playwright、镜像、数据、配额、顺序和重复数。生成脚本保留历史 `STAGE0_VALID` 标签；after 的实际性质由独立交付 Manifest 标注，不能修改冻结脚本来改标签。正式结果和比较在实验 README／交付 Manifest 中追加，单次本机数据不代表生产 SLA。
