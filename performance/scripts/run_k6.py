#!/usr/bin/env python3
"""Run one Phase 10A-4 k6 workload against the isolated Performance stack."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import ProxyHandler, Request, build_opener


REPO_ROOT = Path(__file__).resolve().parents[2]
PERFORMANCE_ROOT = REPO_ROOT / "performance"
COMPOSE_FILE = PERFORMANCE_ROOT / "docker-compose.performance.yml"
GENERATED_ROOT = PERFORMANCE_ROOT / "generated"
RESULTS_ROOT = PERFORMANCE_ROOT / "results"
VERIFIER = PERFORMANCE_ROOT / "verification" / "verify_database.py"
OBSERVABILITY_VERIFIER = PERFORMANCE_ROOT / "scripts" / "verify_observability.py"
PROJECT = "ticketing-phase10a"
K6_IMAGE = "grafana/k6:2.2.0"
BACKEND_URL = "http://127.0.0.1:18080"
PROMETHEUS_URL = "http://127.0.0.1:19090"
AUTH_CACHE_PATTERN = "ticketing:auth-session:*"
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class RunError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_duration(value: str) -> float:
    match = re.fullmatch(r"([1-9][0-9]*)(ms|s|m|h)", value)
    if not match:
        raise ValueError(f"invalid duration: {value}")
    number = int(match.group(1))
    return number * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[match.group(2)]


def compose_command(*arguments: str) -> list[str]:
    return [
        "docker",
        "compose",
        "-p",
        PROJECT,
        "-f",
        str(COMPOSE_FILE),
        *arguments,
    ]


def run_command(arguments: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        arguments,
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if check and completed.returncode != 0:
        raise RunError(
            f"command failed ({completed.returncode}): {' '.join(arguments)}\n"
            f"{completed.stdout}{completed.stderr}"
        )
    return completed


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RunError(f"cannot read {path}: {error}") from error


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def print_console(value: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    print(value.encode(encoding, errors="replace").decode(encoding), end="")


def http_json(url: str, *, headers: dict[str, str] | None = None, timeout: float = 10) -> Any:
    opener = build_opener(ProxyHandler({}))
    request = Request(url, headers=headers or {})
    try:
        with opener.open(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, OSError, json.JSONDecodeError) as error:
        raise RunError(f"HTTP request failed for {url}: {error}") from error


def prometheus_query(expression: str) -> list[dict[str, Any]]:
    payload = http_json(f"{PROMETHEUS_URL}/api/v1/query?{urlencode({'query': expression})}")
    if payload.get("status") != "success":
        raise RunError(f"Prometheus query failed: {payload}")
    return payload["data"]["result"]


def planned_iterations(args: argparse.Namespace) -> int:
    if args.mode == "smoke":
        return 3
    if args.mode == "steady":
        rate = args.group_rate if args.workload == "formal-seat-contention" else args.rate
        return math.ceil(rate * parse_duration(args.duration))
    target = args.target_rate
    total = parse_duration(args.ramp_duration)
    if args.hold_duration:
        total += parse_duration(args.hold_duration)
    return math.ceil(target * total)


def validate_args(args: argparse.Namespace, session_count: int, seat_count: int) -> int:
    if args.mode in {"steady", "discovery"} and not args.preallocated_vus:
        raise RunError("--preallocated-vus is required for steady/discovery")
    if args.mode == "steady":
        selected = args.group_rate if args.workload == "formal-seat-contention" else args.rate
        if not selected or selected <= 0:
            raise RunError("steady mode requires a positive --rate/--group-rate")
        parse_duration(args.duration)
    if args.mode == "discovery":
        if not args.start_rate or not args.target_rate:
            raise RunError("discovery requires --start-rate and --target-rate")
        parse_duration(args.ramp_duration)
        if args.hold_duration:
            parse_duration(args.hold_duration)
    planned = planned_iterations(args)
    if args.workload == "auth-read":
        if args.auth_pool_size <= 0 or args.auth_pool_size > session_count:
            raise RunError("auth pool size exceeds available sessions")
        if args.auth_mode == "cold" and planned > session_count:
            raise RunError("cold run would reuse an offline Session")
    if args.workload == "formal-seat-contention":
        if not 2 <= args.contenders <= 20:
            raise RunError("--contenders must be between 2 and 20")
        if args.contenders > session_count:
            raise RunError("not enough distinct users for one contention group")
        if planned > seat_count:
            raise RunError("planned contention groups would exhaust the Seat pool")
    return planned


def clear_auth_cache() -> int:
    completed = run_command(
        compose_command(
            "exec", "-T", "redis", "redis-cli", "--raw", "EVAL",
            "local c='0'; local n=0; repeat local r=redis.call('SCAN',c,'MATCH',ARGV[1],'COUNT',1000); c=r[1]; for _,k in ipairs(r[2]) do n=n+redis.call('DEL',k) end until c=='0'; return n",
            "0", AUTH_CACHE_PATTERN,
        )
    )
    return int(completed.stdout.strip() or "0")


def auth_cache_count() -> int:
    completed = run_command(
        compose_command(
            "exec", "-T", "redis", "redis-cli", "--raw", "--scan",
            "--pattern", AUTH_CACHE_PATTERN,
        )
    )
    return len([line for line in completed.stdout.splitlines() if line.strip()])


def authenticate_session(session: dict[str, str]) -> None:
    payload = http_json(
        f"{BACKEND_URL}/auth/me",
        headers={"Cookie": f"ticketing_session={session['sessionToken']}"},
    )
    if payload.get("id") != session["userId"]:
        raise RunError("warm-up /auth/me returned the wrong user")


def prepare_auth(args: argparse.Namespace, sessions: list[dict[str, str]]) -> dict[str, Any]:
    deleted = clear_auth_cache()
    details: dict[str, Any] = {"cacheKeysDeleted": deleted}
    if args.auth_mode == "warm":
        for session in sessions[: args.auth_pool_size]:
            authenticate_session(session)
        deadline = time.monotonic() + 10
        count = 0
        while time.monotonic() < deadline:
            count = auth_cache_count()
            if count >= args.auth_pool_size:
                break
            time.sleep(0.2)
        if count < args.auth_pool_size:
            raise RunError(
                f"warm auth cache has {count} keys, expected at least {args.auth_pool_size}"
            )
        details["warmedCacheKeys"] = count
    return details


def k6_version() -> str:
    completed = run_command(["docker", "run", "--rm", K6_IMAGE, "version"])
    return completed.stdout.strip()


def verify_remote_write(run_id: str, start_epoch: float) -> list[dict[str, str]]:
    query = urlencode(
        [
            ("match[]", f'{{testid="{run_id}"}}'),
            ("start", str(start_epoch)),
            ("end", str(time.time() + 5)),
        ]
    )
    deadline = time.monotonic() + 20
    series: list[dict[str, str]] = []
    while time.monotonic() < deadline:
        payload = http_json(f"{PROMETHEUS_URL}/api/v1/series?{query}")
        series = payload.get("data", []) if payload.get("status") == "success" else []
        names = {item.get("__name__", "") for item in series}
        if any(name.startswith("k6_") for name in names) and any(
            "iterations" in name or "http_reqs" in name or "ticketing_" in name
            for name in names
        ):
            break
        time.sleep(1)
    if not series:
        raise RunError("Prometheus has no Remote Write series for this testid")
    forbidden_labels = {
        "url", "userId", "username", "sessionToken", "csrfToken",
        "authSessionId", "seatId", "sessionId", "reservationId", "orderId",
        "idempotencyKey", "vu", "iter", "ip", "error",
    }
    for labels in series:
        if forbidden_labels.intersection(labels):
            raise RunError(f"high-cardinality label found: {labels}")
        serialized = json.dumps(labels, ensure_ascii=False)
        if any(value in serialized for value in ("perf-user-", "perf-ss-", "ticketing_session")):
            raise RunError(f"dynamic identifier leaked into Remote Write labels: {labels}")
    return series


def verify_k6_resources() -> dict[str, bool]:
    selector = (
        '{container_label_com_docker_compose_project="ticketing-phase10a",'
        'container_label_com_docker_compose_service="k6"}'
    )
    return {
        "cpu": bool(prometheus_query("container_cpu_usage_seconds_total" + selector)),
        "memory": bool(prometheus_query("container_memory_working_set_bytes" + selector)),
    }


def run_observability_with_retries() -> int:
    for attempt in range(1, 7):
        completed = run_command([sys.executable, str(OBSERVABILITY_VERIFIER)], check=False)
        if completed.returncode == 0:
            print_console(completed.stdout)
            return 0
        if attempt < 6:
            time.sleep(5)
    print_console(completed.stdout + completed.stderr)
    return completed.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "workload", choices=("public-read", "auth-read", "formal-seat-contention")
    )
    parser.add_argument("--mode", choices=("smoke", "steady", "discovery"), default="smoke")
    parser.add_argument("--rate", type=int)
    parser.add_argument("--group-rate", type=int)
    parser.add_argument("--duration", default="10s")
    parser.add_argument("--preallocated-vus", type=int)
    parser.add_argument("--start-rate", type=int)
    parser.add_argument("--target-rate", type=int)
    parser.add_argument("--ramp-duration", default="10s")
    parser.add_argument("--hold-duration")
    parser.add_argument("--auth-mode", choices=("warm", "cold", "redis-down"), default="warm")
    parser.add_argument("--auth-pool-size", type=int, default=100)
    parser.add_argument("--contenders", type=int, default=4)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    run_id = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + f"-{args.workload}-{args.mode}-{secrets.token_hex(2)}"
    )
    short_token = secrets.token_hex(4)
    if not RUN_ID_RE.fullmatch(run_id):
        print("invalid generated run id", file=sys.stderr)
        return 1
    result_dir = RESULTS_ROOT / run_id
    redis_stopped = False
    start_epoch = time.time()
    start_utc = utc_now()
    manifest: dict[str, Any] = {}
    result_code = 1
    try:
        dataset = read_json(GENERATED_ROOT / "dataset.json")
        sessions = read_json(GENERATED_ROOT / "sessions.json")
        seats = read_json(GENERATED_ROOT / "workload-seats.json")
        if not isinstance(sessions, list) or not isinstance(seats, list):
            raise RunError("generated Session/Seat manifests must be arrays")
        planned = validate_args(args, len(sessions), len(seats))
        http_json(f"{BACKEND_URL}/health")
        result_dir.mkdir(parents=True, exist_ok=False)
        version = k6_version()
        git_head = run_command(["git", "rev-parse", "HEAD"]).stdout.strip()
        git_dirty = bool(run_command(["git", "status", "--porcelain"]).stdout.strip())
        manifest = {
            "runId": run_id,
            "shortRunToken": short_token,
            "startUtc": start_utc,
            "endUtc": None,
            "gitHead": git_head,
            "gitDirty": git_dirty,
            "datasetProfile": dataset["profile"],
            "datasetProfileSha256": dataset["profileSha256"],
            "datasetGitHead": dataset["gitHead"],
            "workload": args.workload,
            "mode": args.mode,
            "rate": args.rate,
            "groupRate": args.group_rate,
            "duration": args.duration,
            "preAllocatedVUs": args.preallocated_vus,
            "authMode": args.auth_mode if args.workload == "auth-read" else None,
            "authPoolSize": args.auth_pool_size if args.workload == "auth-read" else None,
            "contendersPerSeat": args.contenders if args.workload == "formal-seat-contention" else None,
            "plannedIterations": planned,
            "plannedAttemptRate": (
                args.group_rate * args.contenders
                if args.workload == "formal-seat-contention" and args.group_rate
                else None
            ),
            "k6Image": K6_IMAGE,
            "k6Version": version,
            "k6ExitCode": None,
            "k6ExitKind": None,
            "remoteWriteVerified": False,
            "resourceMetrics": {"cpu": False, "memory": False},
            "verifierExitCode": None,
            "verdict": "running",
        }
        if args.workload == "auth-read":
            manifest["authPreparation"] = prepare_auth(args, sessions)
            if args.auth_mode == "redis-down":
                run_command(compose_command("stop", "redis"))
                redis_stopped = True

        environment = {
            "RUN_ID": run_id,
            "SHORT_RUN_TOKEN": short_token,
            "BASE_URL": "http://backend:8080",
            "MODE": args.mode,
            "DURATION": args.duration,
            "AUTH_MODE": args.auth_mode,
            "AUTH_POOL_SIZE": str(args.auth_pool_size),
            "CONTENDERS_PER_SEAT": str(args.contenders),
        }
        optional = {
            "RATE": args.rate,
            "GROUP_RATE": args.group_rate,
            "PREALLOCATED_VUS": args.preallocated_vus,
            "START_RATE": args.start_rate,
            "TARGET_RATE": args.target_rate,
            "RAMP_DURATION": args.ramp_duration,
            "HOLD_DURATION": args.hold_duration,
        }
        environment.update({name: str(value) for name, value in optional.items() if value is not None})
        command = compose_command(
            "--profile", "load", "run", "--rm", "--no-deps",
            "--name", f"ticketing-phase10a-k6-{short_token}",
        )
        for name, value in environment.items():
            command.extend(["-e", f"{name}={value}"])
        command.extend(
            [
                "k6", "run", "-o", "experimental-prometheus-rw",
                "--tag", f"testid={run_id}", f"/scripts/workloads/{args.workload}.js",
            ]
        )
        console_path = result_dir / "console.log"
        with console_path.open("w", encoding="utf-8", newline="\n") as console:
            process = subprocess.Popen(
                command, cwd=REPO_ROOT, text=True, encoding="utf-8",
                stdout=console, stderr=subprocess.STDOUT,
            )
            observed = {"cpu": False, "memory": False}
            observe_resources = args.mode == "steady" and parse_duration(args.duration) >= 10
            next_observation = time.monotonic() + 5
            while process.poll() is None:
                if observe_resources and time.monotonic() >= next_observation:
                    try:
                        sample = verify_k6_resources()
                    except RunError:
                        sample = {"cpu": False, "memory": False}
                    observed = {key: observed[key] or sample[key] for key in observed}
                    next_observation = time.monotonic() + 1
                time.sleep(0.2)
            code = process.returncode
        manifest["resourceMetrics"] = observed
        manifest["k6ExitCode"] = code
        manifest["k6ExitKind"] = (
            "success" if code == 0 else "threshold_failure" if code == 99 else "execution_failure"
        )
        if code not in (0, 99):
            raise RunError(f"k6 exited with {code} ({manifest['k6ExitKind']})")
        if observe_resources and not all(observed.values()):
            raise RunError(f"k6 cAdvisor metrics missing: {observed}")
        if not (result_dir / "business-summary.json").exists():
            raise RunError("k6 did not write business-summary.json")
        series = verify_remote_write(run_id, start_epoch)
        manifest["remoteWriteVerified"] = True
        manifest["remoteWriteSeriesCount"] = len(series)
        manifest["remoteWriteMetricNames"] = sorted(
            {labels.get("__name__", "") for labels in series}
        )
        if args.workload == "auth-read" and args.auth_mode == "cold":
            measured = read_json(result_dir / "business-summary.json")["iterations"]
            cache_count = auth_cache_count()
            manifest["coldUniqueSessions"] = measured
            manifest["coldCacheKeysAfter"] = cache_count
            if cache_count < measured:
                raise RunError("cold run did not create one cache entry per completed iteration")
        if args.workload == "formal-seat-contention":
            verifier = run_command([sys.executable, str(VERIFIER)], check=False)
            (result_dir / "verifier.txt").write_text(
                verifier.stdout + verifier.stderr, encoding="utf-8"
            )
            manifest["verifierExitCode"] = verifier.returncode
            if verifier.returncode != 0:
                raise RunError("PostgreSQL invariant verifier failed")
        if code == 99:
            raise RunError("k6 exited with 99 (threshold_failure)")
        manifest["verdict"] = "passed"
        print_console((result_dir / "console.log").read_text(encoding="utf-8"))
        print(f"[PASS] run artifacts: {result_dir}")
        result_code = 0
    except (RunError, ValueError, KeyError, OSError) as error:
        manifest["verdict"] = "failed"
        manifest["error"] = str(error)
        print(f"[FAIL] {error}", file=sys.stderr)
    finally:
        if redis_stopped:
            restored = run_command(
                compose_command("up", "-d", "--wait", "redis"), check=False
            )
            manifest["redisRestoreExitCode"] = restored.returncode
            observability_code = run_observability_with_retries()
            manifest["postRedisObservabilityExitCode"] = observability_code
            if restored.returncode != 0 or observability_code != 0:
                manifest["verdict"] = "failed"
                manifest["error"] = "Redis restore or post-recovery observability failed"
                result_code = 1
        if manifest and result_dir.exists():
            manifest["endUtc"] = utc_now()
            write_json(result_dir / "run-manifest.json", manifest)
    return result_code


if __name__ == "__main__":
    raise SystemExit(main())
