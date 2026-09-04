#!/usr/bin/env python3
import argparse
import base64
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import (
    HTTPCookieProcessor,
    ProxyHandler,
    Request,
    build_opener,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COMPOSE_FILE = REPO_ROOT / "performance" / "docker-compose.performance.yml"


class Checks:
    def __init__(self) -> None:
        self.failed = 0

    def record(self, name: str, passed: bool, detail: str) -> None:
        state = "PASS" if passed else "FAIL"
        print(f"[{state}] {name}: {detail}")
        if not passed:
            self.failed += 1


def request(url: str, *, headers=None, data=None, opener=None, timeout=10):
    req = Request(url, headers=headers or {}, data=data)
    client = opener or build_opener(ProxyHandler({}))
    try:
        with client.open(req, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8")
    except HTTPError as error:
        return error.code, error.read().decode("utf-8")


def wait_for_url(url: str, *, expected=200, timeout=60, headers=None):
    deadline = time.monotonic() + timeout
    last = "no response"
    while time.monotonic() < deadline:
        try:
            status, body = request(url, headers=headers)
            last = f"HTTP {status}"
            if status == expected:
                return status, body
        except (OSError, URLError) as error:
            last = str(error)
        time.sleep(1)
    raise RuntimeError(f"{url} did not become ready: {last}")


def compose_psql(compose_file: Path, sql: str, *, monitoring_user=False) -> str:
    if monitoring_user:
        connection = (
            "postgresql://ticketing_metrics:ticketing_metrics_dev@"
            "127.0.0.1:5432/ticketing?sslmode=disable"
        )
        psql_args = ["psql", connection]
    else:
        psql_args = ["psql", "-U", "ticketing", "-d", "ticketing"]
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "exec",
            "-T",
            "postgres",
            *psql_args,
            "-v",
            "ON_ERROR_STOP=1",
            "-At",
            "-F",
            "\t",
            "-c",
            sql,
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout.strip()


def compose_redis(compose_file: Path, *arguments: str) -> str:
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(compose_file),
            "exec",
            "-T",
            "redis",
            "redis-cli",
            "--raw",
            *arguments,
        ],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout.strip()


def prometheus_query(base_url: str, expression: str):
    url = f"{base_url}/api/v1/query?{urlencode({'query': expression})}"
    status, body = request(url)
    if status != 200:
        raise RuntimeError(f"HTTP {status}: {body[:200]}")
    payload = json.loads(body)
    return payload["data"]["result"]


def wait_for_prometheus_query(base_url: str, expression: str, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = prometheus_query(base_url, expression)
        if result:
            return result
        time.sleep(1)
    return []


def exercise_redis_backed_paths(backend_url: str) -> str:
    jar = CookieJar()
    opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(jar))
    origin = "http://performance.local"
    payload = json.dumps(
        {"username": "demo", "password": "Ticketing123!"}
    ).encode("utf-8")
    status, _ = request(
        f"{backend_url}/auth/login",
        headers={"Content-Type": "application/json", "Origin": origin},
        data=payload,
        opener=opener,
    )
    if status != 200:
        return f"login returned HTTP {status}"
    me_status, _ = request(f"{backend_url}/auth/me", opener=opener)
    seats_status, _ = request(
        f"{backend_url}/sessions/ses-concert-1001/seats", opener=opener
    )
    csrf = next((cookie.value for cookie in jar if cookie.name == "ticketing_csrf"), "")
    logout_status, _ = request(
        f"{backend_url}/auth/logout",
        headers={"Origin": origin, "X-CSRF-Token": csrf},
        data=b"",
        opener=opener,
    )
    return (
        f"login=200, me={me_status}, seats={seats_status}, "
        f"logout={logout_status}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the Phase 10A observability stack")
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE_FILE)
    parser.add_argument("--backend-url", default="http://127.0.0.1:18080")
    parser.add_argument("--prometheus-url", default="http://127.0.0.1:19090")
    parser.add_argument("--grafana-url", default="http://127.0.0.1:13000")
    parser.add_argument("--cadvisor-url", default="http://127.0.0.1:18081")
    args = parser.parse_args()
    compose_file = args.compose_file.resolve()
    checks = Checks()
    dashboard_expressions = []

    performance_root = REPO_ROOT / "performance"
    checks.record(
        "performance directory layout",
        Path(__file__).resolve().parent.parent == performance_root
        and not (REPO_ROOT / "backend" / "performance").exists(),
        f"root={performance_root}",
    )

    try:
        status, health = wait_for_url(f"{args.backend_url}/health")
        checks.record("backend health", status == 200, f"HTTP {status} {health}")
    except Exception as error:
        checks.record("backend health", False, str(error))

    try:
        event_status, _ = request(f"{args.backend_url}/events")
        order_status, _ = request(f"{args.backend_url}/orders")
        order_id_status, _ = request(
            f"{args.backend_url}/orders/TKT-SEED-SOLD-ses-concert-1001"
        )
        unmatched_status, _ = request(
            f"{args.backend_url}/phase10a-unmatched-smoke"
        )
        request(f"{args.backend_url}/health")
        request(f"{args.backend_url}/metrics")
        _, metrics = request(f"{args.backend_url}/metrics")
        required = (
            "ticketing_http_requests_total",
            "ticketing_http_request_duration_seconds",
            "ticketing_http_requests_in_flight",
        )
        checks.record(
            "backend metric families",
            all(name in metrics for name in required),
            ", ".join(required),
        )
        event_metric = re.search(
            r'ticketing_http_requests_total\{[^}]*route="/events"[^}]*status_class="2xx"[^}]*\}\s+([0-9.]+)',
            metrics,
        )
        order_metric = re.search(
            r'ticketing_http_requests_total\{[^}]*route="/orders"[^}]*status_class="4xx"[^}]*\}\s+([0-9.]+)',
            metrics,
        )
        order_id_metric = re.search(
            r'ticketing_http_requests_total\{[^}]*route="/orders/\{orderId\}"[^}]*status_class="4xx"[^}]*\}\s+([0-9.]+)',
            metrics,
        )
        unmatched_metric = re.search(
            r'ticketing_http_requests_total\{[^}]*route="__unmatched__"[^}]*status_class="4xx"[^}]*\}\s+([0-9.]+)',
            metrics,
        )
        checks.record(
            "2xx normalized route",
            event_status == 200 and event_metric is not None,
            f"GET /events HTTP {event_status}",
        )
        checks.record(
            "401 counted as 4xx",
            order_status == 401 and order_metric is not None,
            f"GET /orders HTTP {order_status}",
        )
        checks.record(
            "parameterized route normalized",
            order_id_status == 401 and order_id_metric is not None,
            f"GET /orders/<id> HTTP {order_id_status}",
        )
        checks.record(
            "unmatched route bounded",
            unmatched_status == 404 and unmatched_metric is not None,
            f"unmatched HTTP {unmatched_status}",
        )
        excluded = 'route="/health"' not in metrics and 'route="/metrics"' not in metrics
        checks.record("health and metrics excluded", excluded, "no excluded route labels")
        unmatched_safe = (
            "TKT-SEED-SOLD-ses-concert-1001" not in metrics
            and "U-1001" not in metrics
            and "phase10a-unmatched-smoke" not in metrics
        )
        checks.record("bounded metric labels", unmatched_safe, "no sample IDs in labels")
        gauge = re.search(r"^ticketing_http_requests_in_flight\s+(-?[0-9.]+)$", metrics, re.MULTILINE)
        checks.record(
            "in-flight returned to zero",
            gauge is not None and float(gauge.group(1)) == 0.0,
            gauge.group(1) if gauge else "gauge sample missing",
        )
    except Exception as error:
        checks.record("backend HTTP metrics", False, str(error))

    try:
        exercise = exercise_redis_backed_paths(args.backend_url)
        checks.record(
            "Redis-backed API exercise",
            "me=200" in exercise and "seats=200" in exercise and "logout=200" in exercise,
            exercise,
        )
    except Exception as error:
        checks.record("Redis-backed API exercise", False, str(error))

    try:
        status, body = wait_for_url(f"{args.prometheus_url}/-/ready")
        checks.record("Prometheus readiness", status == 200, body.strip())
        _, targets_body = request(f"{args.prometheus_url}/api/v1/targets")
        active = json.loads(targets_body)["data"]["activeTargets"]
        target_states = {
            target["labels"]["job"]: target["health"] for target in active
        }
        expected_jobs = {
            "ticketing-backend",
            "postgres",
            "redis",
            "cadvisor",
            "prometheus",
        }
        checks.record(
            "Prometheus targets",
            expected_jobs.issubset(target_states)
            and all(target_states[job] == "up" for job in expected_jobs),
            json.dumps(target_states, sort_keys=True),
        )
    except Exception as error:
        checks.record("Prometheus", False, str(error))

    try:
        auth = base64.b64encode(b"admin:admin").decode("ascii")
        headers = {"Authorization": f"Basic {auth}"}
        status, health = wait_for_url(f"{args.grafana_url}/api/health")
        checks.record("Grafana health", status == 200, health)
        datasource_status, datasource = request(
            f"{args.grafana_url}/api/datasources/uid/ticketing-prometheus",
            headers=headers,
        )
        dashboard_status, dashboard = request(
            f"{args.grafana_url}/api/dashboards/uid/ticketing-phase10a",
            headers=headers,
        )
        checks.record(
            "Grafana datasource provisioning",
            datasource_status == 200 and "Prometheus" in datasource,
            f"HTTP {datasource_status}",
        )
        checks.record(
            "Grafana dashboard provisioning",
            dashboard_status == 200 and "Ticketing Phase 10A Observability" in dashboard,
            f"HTTP {dashboard_status}",
        )
        dashboard_value = json.loads(dashboard)
        dashboard_expressions = [
            target["expr"]
            for panel in dashboard_value["dashboard"]["panels"]
            for target in panel.get("targets", [])
            if target.get("expr")
        ]
    except Exception as error:
        checks.record("Grafana provisioning", False, str(error))

    try:
        settings = compose_psql(
            compose_file,
            "SELECT current_setting('shared_preload_libraries'), "
            "current_setting('track_io_timing'), current_setting('log_lock_waits');",
        )
        checks.record(
            "PostgreSQL observability settings",
            settings == "pg_stat_statements\ton\ton",
            settings,
        )
        extension = compose_psql(
            compose_file,
            "SELECT extname FROM pg_extension WHERE extname='pg_stat_statements';",
        )
        checks.record("pg_stat_statements extension", extension == "pg_stat_statements", extension)
        role = compose_psql(
            compose_file,
            "SELECT pg_has_role('ticketing_metrics', 'pg_monitor', 'member');",
        )
        no_writes = compose_psql(
            compose_file,
            "SELECT NOT COALESCE(bool_or("
            "has_table_privilege('ticketing_metrics', format('%I.%I', table_schema, table_name), 'INSERT') OR "
            "has_table_privilege('ticketing_metrics', format('%I.%I', table_schema, table_name), 'UPDATE') OR "
            "has_table_privilege('ticketing_metrics', format('%I.%I', table_schema, table_name), 'DELETE')"
            "), false) FROM information_schema.tables WHERE table_schema='public';",
        )
        monitor_read = compose_psql(
            compose_file,
            "SELECT count(*) >= 1 FROM pg_stat_activity;",
            monitoring_user=True,
        )
        checks.record(
            "ticketing_metrics permissions",
            role == "t" and no_writes == "t" and monitor_read == "t",
            f"pg_monitor={role}, no_business_writes={no_writes}, read_stats={monitor_read}",
        )
        backend_connections = compose_psql(
            compose_file,
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE application_name='ticketing_backend_phase10a';",
        )
        exporter_connections = compose_psql(
            compose_file,
            "SELECT count(*) FROM pg_stat_activity "
            "WHERE application_name='ticketing_postgres_exporter';",
        )
        checks.record(
            "PostgreSQL application names",
            backend_connections == "4" and int(exporter_connections or "0") >= 1,
            f"backend={backend_connections}, exporter={exporter_connections}",
        )
        statements = compose_psql(
            compose_file,
            "SELECT count(*) > 0 FROM pg_stat_statements;",
        )
        checks.record("pg_stat_statements data", statements == "t", statements)
    except Exception as error:
        checks.record("PostgreSQL checks", False, str(error))

    try:
        commandstats = compose_redis(compose_file, "INFO", "commandstats")
        latencystats = compose_redis(compose_file, "INFO", "latencystats")
        checks.record(
            "Redis commandstats",
            "cmdstat_" in commandstats,
            f"{commandstats.count('cmdstat_')} command rows",
        )
        checks.record(
            "Redis latencystats",
            "latency_percentiles_usec_" in latencystats,
            f"{latencystats.count('latency_percentiles_usec_')} latency rows",
        )
        _, redis_metrics = request("http://127.0.0.1:19121/metrics")
        checks.record(
            "Redis exporter metrics",
            "redis_up 1" in redis_metrics and "redis_connected_clients" in redis_metrics,
            "redis_up and connected_clients present",
        )
    except Exception as error:
        checks.record("Redis checks", False, str(error))

    try:
        _, cadvisor_metrics = request(f"{args.cadvisor_url}/metrics", timeout=20)
        cpu_present = "container_cpu_usage_seconds_total" in cadvisor_metrics
        memory_present = "container_memory_working_set_bytes" in cadvisor_metrics
        services = {
            service: (
                f'container_label_com_docker_compose_project="ticketing-phase10a"' in cadvisor_metrics
                and f'container_label_com_docker_compose_service="{service}"' in cadvisor_metrics
            )
            for service in ("backend", "postgres", "redis")
        }
        cadvisor_ok = cpu_present and memory_present and all(services.values())
        checks.record(
            "cAdvisor container recognition",
            cadvisor_ok,
            f"cpu={cpu_present}, memory={memory_present}, services={services}",
        )
        if not cadvisor_ok:
            print(
                "[FALLBACK] Run performance/scripts/docker_stats_sampler.py; "
                "cAdvisor recognition is a partial verification failure."
            )
    except Exception as error:
        checks.record("cAdvisor", False, f"{error}; use docker_stats_sampler.py")

    try:
        for expression in dashboard_expressions:
            prometheus_query(args.prometheus_url, expression)
        checks.record(
            "Grafana dashboard query syntax",
            bool(dashboard_expressions),
            f"Prometheus accepted {len(dashboard_expressions)} panel queries",
        )
    except Exception as error:
        checks.record("Grafana dashboard query syntax", False, str(error))

    for name, expression in {
        "backend": "ticketing_http_requests_total",
        "postgres": 'pg_stat_database_numbackends{datname="ticketing"}',
        "redis": "redis_connected_clients",
        "containers": 'container_memory_working_set_bytes{container_label_com_docker_compose_project="ticketing-phase10a"}',
    }.items():
        try:
            result = wait_for_prometheus_query(args.prometheus_url, expression)
            checks.record(f"Prometheus {name} panel data", bool(result), f"{len(result)} series")
        except Exception as error:
            checks.record(f"Prometheus {name} panel data", False, str(error))

    print(f"\nVerification result: {'PASS' if checks.failed == 0 else 'FAIL'} ({checks.failed} failed check(s))")
    return 0 if checks.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
