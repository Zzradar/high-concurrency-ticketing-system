# Phase 10A 性能验证环境

这套 Performance Stack（性能测试专用服务组）与日常 `backend/docker-compose.yml` 完全隔离：Compose project 固定为 `ticketing-phase10a`，PostgreSQL、Prometheus 和 Grafana 使用独立命名卷，主机端口也不与开发栈重叠。它只用于 Phase 1～9 Demo 数据上的观测冒烟，不应连接或复用开发数据库。

## 组件与端口

- Backend `http://127.0.0.1:18080`：运行 Phase 9 原业务参数，并在 `/metrics` 暴露 Drogon 原生 HTTP 指标。
- PostgreSQL `127.0.0.1:15432`：启用 `pg_stat_statements`（SQL 聚合执行统计）、I/O timing 和锁等待日志。
- Redis `127.0.0.1:16379`：独立的认证会话和座位临时占用缓存。
- postgres_exporter `127.0.0.1:19187`：用只读监控账号把 PostgreSQL 状态转换成 Prometheus 指标。
- redis_exporter `127.0.0.1:19121`：把 Redis `INFO` 状态转换成 Prometheus 指标。
- Prometheus `http://127.0.0.1:19090`：每 5 秒抓取并保存各组件时序指标。
- Grafana `http://127.0.0.1:13000`：展示已预置的 `Ticketing Phase 10A Observability` Dashboard；本地管理员为 `admin/admin`。
- cAdvisor `http://127.0.0.1:18081`：从 Docker/cgroup 读取容器 CPU、内存和网络指标。

Backend 的 PostgreSQL pool 仍为 4 条连接；`seat_holds` 与 `auth_sessions` 两个 Redis client pool 仍各为 2 条连接。Worker、TTL、支付模拟、认证和限流参数均保持 Phase 9 基线，本阶段没有做连接池或业务参数调优。

## 启动和验证

在仓库根目录执行：

```powershell
docker compose -p ticketing-phase10a -f performance/docker-compose.performance.yml up -d --build --wait
python performance/scripts/verify_observability.py
```

Prometheus Targets 页面应显示 backend、postgres、redis、cadvisor 和 prometheus 为 UP。Grafana 的 Prometheus datasource 与 Phase10A Overview dashboard 会在启动时自动 provision（由文件声明并创建），无需手工操作。

关闭服务但保留数据：

```powershell
docker compose -p ticketing-phase10a -f performance/docker-compose.performance.yml down
```

只有明确要丢弃全部 Performance 数据时，才执行以下命令；它会删除 `ticketing_phase10a_postgres_data`、`ticketing_phase10a_prometheus_data` 和 `ticketing_phase10a_grafana_data`，但不会触碰开发卷：

```powershell
docker compose -p ticketing-phase10a -f performance/docker-compose.performance.yml down -v
```

## cAdvisor fallback

Windows + WSL2 + Docker Desktop 某些版本可能让 cAdvisor 容器保持 Running，却无法识别其他业务容器。`verify_observability.py` 会把这种情况报告为 FAIL，不会伪装成完整成功。此时用 Docker 自身的实时统计作为 fallback（后备采集方式）：

```powershell
python performance/scripts/docker_stats_sampler.py --interval 5 --format csv --output performance/artifacts/docker-stats.csv
```

脚本只选择 `ticketing-phase10a` 项目容器，记录 UTC 时间、CPU、内存、网络、块 I/O 和 PID 数；按 `Ctrl+C` 可安全结束。若没有找到对应容器，脚本会返回非零状态并明确报错。

## Metrics ON/OFF 小型对照

默认 Metrics ON 使用 `config/config.performance.json`。只关闭逐请求自定义指标、保留 PromExporter `/metrics` 时，使用同一栈和 `config/config.performance.no_metrics.json`：

```powershell
$env:TICKETING_CONFIG_PATH = "config/config.performance.no_metrics.json"
docker compose -p ticketing-phase10a -f performance/docker-compose.performance.yml up -d --force-recreate backend --wait
```

恢复 Metrics ON：

```powershell
Remove-Item Env:TICKETING_CONFIG_PATH -ErrorAction SilentlyContinue
docker compose -p ticketing-phase10a -f performance/docker-compose.performance.yml up -d --force-recreate backend --wait
```

对照必须对同一个公开 `GET /events` 做相同 warm-up，并以同一工具、固定 duration 和 concurrency 分别运行 OFF/ON 各三次。结果只用于判断互斥锁指标埋点是否明显超过自然波动，不是容量结论。

## 当前范围

Phase 10A-1 只建立可信的测量环境，尚未实现正式业务压测 workload、大数据生成、Run Harness、压测专用 `verify.sql`、Playwright、限流、Waiting Room、消息队列或 SQL/连接池优化。因此 Dashboard 有数据不代表系统容量已经测出；SQL Top N 也继续通过 PostgreSQL `pg_stat_statements` 查询，而不会把 SQL 文本放入 Prometheus label。后续压测前再重置统计并导出完整 Top SQL 报告。

## 可重复数据 Profile

`performance/data/profiles/` 中的 Profile（数据规模配置）用版本控制中的 JSON 描述用户、活动、场次、座位布局、价格分区与未来开场偏移。`smoke` 是脚本和浏览器 E2E 的小数据集；`baseline` 生成 10,000 个用户、2 个活动、20 个场次、1,000 个物理座位和 20,000 个场次座位。这些数量只是第一版可重复测试条件，不是容量目标或容量结论。

Performance 数据统一使用 `perf-*` ID。生成器通过 PostgreSQL 集合操作写入业务实体，并批量导入真实格式的离线认证 Session（会话）：

```powershell
python performance/data/generate_dataset.py --profile smoke
python performance/data/generate_dataset.py --profile baseline
```

生成器会先完整校验 Profile，再在单个数据库事务中替换 Performance 作用域的数据。它复用 Demo 用户的合法 Argon2id 测试密码哈希来满足 Schema；本阶段业务压测直接使用离线 Session，不做 10,000 次密码哈希，也不代表 Login Stress（登录压力测试）。真实登录压力留到 Phase 10A-5。

`performance/generated/dataset.json` 记录 Profile 哈希、Git HEAD、数量和 hot/low-conflict 目标；`sessions.json` 按用户顺序记录 raw Session Token（原始会话令牌）与独立 CSRF Token。原始令牌属于敏感测试凭据，整个生成目录默认被 Git 忽略，禁止复制到日志或提交仓库。生成器不会批量预热 Redis 认证缓存；仅用第一条凭据调用一次 `/auth/me` 做真实验证。

## 安全 Reset 与权威校验

以下命令会显示计划但不修改任何状态：

```powershell
python performance/scripts/reset_environment.py --profile baseline
```

显式确认后，Reset（重置）脚本只允许删除名称以 `ticketing_phase10a_` 开头的三个 Performance 卷，然后重建栈、验证观测链、生成数据、检查初始状态并调用 PostgreSQL 权威不变量校验：

```powershell
python performance/scripts/reset_environment.py --profile baseline --yes
```

脚本会拒绝 `backend_ticketing_postgres_data` 或任何非 Performance 卷，不会调用 Docker prune，也不会连接开发 Compose。支付夹具和大量 `PENDING_PAYMENT` 订单暂不预生成。

业务测试写入数据后，可以随时运行只读 verifier（不变量检查器）：

```powershell
python performance/verification/verify_database.py
```

`verify.sql` 只读取 `perf-*` 用户或库存关联的事实，逐项输出 `check_name<TAB>violation_count`。全部为零才返回成功；任一跨表状态、金额、所有权、支付或退款不变量被破坏时返回非零。该结果用于否决不可信的测试运行，不等于容量测试。
