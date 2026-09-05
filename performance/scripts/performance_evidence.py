#!/usr/bin/env python3
"""Evidence collectors for repeatable local Phase 10A baseline runs."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import re
import subprocess
from typing import Any
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener

from run_k6 import BACKEND_URL, COMPOSE_FILE, PROJECT, compose_command


def command(arguments: list[str], *, input_text: str | None = None) -> str:
    completed = subprocess.run(
        arguments, text=True, encoding="utf-8", errors="replace",
        input=input_text, capture_output=True, check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout


def psql(sql: str) -> str:
    return command(compose_command(
        "exec", "-T", "postgres", "psql", "-U", "ticketing", "-d", "ticketing",
        "-v", "ON_ERROR_STOP=1", "-At", "-F", "\t", "-c", sql,
    ))


def redis_info(section: str) -> str:
    return command(compose_command(
        "exec", "-T", "redis", "redis-cli", "--raw", "INFO", section,
    ))


def parse_redis_info(raw: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for line in raw.splitlines():
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        if "," in value and "=" in value:
            fields = {}
            for item in value.split(","):
                if "=" in item:
                    child, child_value = item.split("=", 1)
                    fields[child] = number(child_value)
            parsed[key] = fields
        else:
            parsed[key] = number(value)
    return parsed


def number(value: str) -> Any:
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def collect_redis(root: Path, phase: str) -> None:
    all_parsed = {}
    for section in ("clients", "memory", "stats", "commandstats", "latencystats"):
        raw = redis_info(section)
        (root / f"redis-{phase}-{section}.txt").write_text(raw, encoding="utf-8")
        all_parsed[section] = parse_redis_info(raw)
    write_json(root / f"redis-{phase}.json", all_parsed)


def reset_statement_stats() -> str:
    return psql("SELECT pg_stat_statements_reset(); SELECT stats_reset FROM pg_stat_statements_info;").strip()


def collect_postgres(root: Path) -> None:
    sql = """
SELECT calls, total_exec_time, mean_exec_time, rows,
       shared_blks_hit, shared_blks_read, temp_blks_written,
       regexp_replace(query, E'[\\n\\r\\t]+', ' ', 'g') AS query
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname='ticketing')
  AND userid = (SELECT oid FROM pg_roles WHERE rolname='ticketing')
ORDER BY total_exec_time DESC
LIMIT 20;
"""
    raw = psql(sql)
    (root / "postgres-top-sql.tsv").write_text(raw, encoding="utf-8")
    rows = []
    for line in raw.splitlines():
        parts = line.split("\t", 7)
        if len(parts) == 8:
            rows.append(dict(zip(
                ("calls", "totalExecMs", "meanExecMs", "rows", "sharedHits",
                 "sharedReads", "tempWrites", "query"), parts,
            )))
    write_json(root / "postgres-top-sql.json", rows)


PROMETHEUS_QUERIES = {
    "backend-rate": "sum(rate(ticketing_http_requests_total[1m])) by (route,method,status_class)",
    "backend-p95": "histogram_quantile(0.95,sum(rate(ticketing_http_request_duration_seconds_bucket[1m])) by (le,route))",
    "postgres-connections": 'pg_stat_database_numbackends{datname="ticketing"}',
    "postgres-waits": "sum(pg_backend_activity_waiting)",
    "redis-clients": "redis_connected_clients",
    "container-cpu": 'sum(rate(container_cpu_usage_seconds_total{container_label_com_docker_compose_project="ticketing-phase10a"}[1m])) by (container_label_com_docker_compose_service)',
    "container-memory": 'sum(container_memory_working_set_bytes{container_label_com_docker_compose_project="ticketing-phase10a"}) by (container_label_com_docker_compose_service)',
}


def query_range(expression: str, start: float, end: float, step: str = "5s") -> Any:
    query = urlencode({"query": expression, "start": start, "end": end, "step": step})
    request = Request(f"http://127.0.0.1:19090/api/v1/query_range?{query}")
    with build_opener(ProxyHandler({})).open(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("status") != "success": raise RuntimeError(str(payload))
    return payload


def collect_prometheus(root: Path, start: float, end: float) -> None:
    for name, expression in PROMETHEUS_QUERIES.items():
        write_json(root / f"prometheus-{name}.json", query_range(expression, start, end))


def collect_logs(root: Path, since: str) -> None:
    raw = command(compose_command("logs", "--no-color", "--since", since, "backend", "postgres", "redis"))
    (root / "service-logs.txt").write_text(raw, encoding="utf-8")
    abnormal = [line for line in raw.splitlines() if re.search(r"\b(error|fatal|panic|deadlock)\b", line, re.I)]
    (root / "abnormal-logs.txt").write_text("\n".join(abnormal) + ("\n" if abnormal else ""), encoding="utf-8")


def collect_docker_stats(root: Path) -> None:
    raw = command([
        "docker", "stats", "--no-stream", "--format", "{{json .}}",
        *command([
            "docker", "ps", "--filter", f"label=com.docker.compose.project={PROJECT}",
            "--format", "{{.Names}}",
        ]).split(),
    ])
    (root / "docker-stats.jsonl").write_text(raw, encoding="utf-8")


def environment_fingerprint() -> dict[str, Any]:
    inspect = json.loads(command(["docker", "compose", "-p", PROJECT, "-f", str(COMPOSE_FILE), "images", "--format", "json"]))
    return {
        "collectedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "platform": platform.platform(), "processor": platform.processor(),
        "python": platform.python_version(),
        "dockerVersion": command(["docker", "version", "--format", "{{json .}}"]),
        "composeVersion": command(["docker", "compose", "version", "--short"]).strip(),
        "images": inspect,
        "backendHealth": json.loads(command(["curl.exe", "-sS", f"{BACKEND_URL}/health"])),
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
