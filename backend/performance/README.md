# Phase 10A-1 性能观测环境

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

在 `backend/` 目录执行：

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
