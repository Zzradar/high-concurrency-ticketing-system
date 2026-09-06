#!/usr/bin/env python3
"""Bounded, isolated Seat Map measurements. No restart, pool tuning or volume deletion."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.request import ProxyHandler, Request, build_opener

import performance_evidence as evidence
import run_k6

ROOT = run_k6.REPO_ROOT
STAGE_METRIC = "ticketing_seat_map_stage_duration_seconds"


def parse_clients(raw):
    """Keep unknown and absent fields honest; Redis CLIENT LIST is versioned."""
    return [dict(part.split("=", 1) for part in line.split() if "=" in part)
            for line in raw.splitlines() if line.strip()]


def metrics():
    with build_opener(ProxyHandler({})).open(run_k6.BACKEND_URL + "/metrics", timeout=5) as response:
        raw = response.read().decode()
    result = {}
    for line in raw.splitlines():
        if line.startswith("ticketing_"):
            key, value = line.rsplit(" ", 1)
            result[key] = float(value)
    return result


def quantile(buckets, fraction):
    """Prometheus classic histogram interpolation; no invented tail above final bucket."""
    buckets = sorted(buckets)
    total = buckets[-1][1] if buckets else 0
    if not total:
        return None
    target = total * fraction
    lower, previous = 0.0, 0.0
    for upper, count in buckets:
        if count >= target:
            if math.isinf(upper):
                return None
            return lower + (upper - lower) * (target - previous) / (count - previous)
        lower, previous = upper, count
    return None


def stage_summary(before, after):
    grouped = {}
    for key, value in after.items():
        if not key.startswith(STAGE_METRIC + "_bucket{"):
            continue
        labels = dict(re.findall(r'(\w+)="([^"]*)"', key))
        delta = value - before.get(key, 0)
        if delta < 0:
            raise RuntimeError("metrics reset during measurement")
        grouped.setdefault(labels["stage"], []).append((float(labels["le"]), delta))
    return {stage: {"samples": max(count for _, count in buckets),
                    **{name: quantile(buckets, fraction) for name, fraction in
                       (("p50Seconds", .5), ("p95Seconds", .95), ("p99Seconds", .99))}}
            for stage, buckets in grouped.items()}


def collect_run_resources(root, run_root, start, end):
    """Do not sum stale cAdvisor series from previous one-off k6 containers."""
    manifest = run_k6.read_json(run_root / "run-manifest.json")
    token = manifest["shortRunToken"]
    if not re.fullmatch(r"[a-f0-9]{8}", token):
        raise ValueError("invalid k6 container token")
    names = {"backend": "ticketing-phase10a-backend-1",
             "redis": "ticketing-phase10a-redis-1",
             "k6": f"ticketing-phase10a-k6-{token}"}
    captured = {}
    for service, name in names.items():
        selector = '{container_label_com_docker_compose_project="ticketing-phase10a",name="' + name + '"}'
        queries = {
            "cpuCores30s": f"rate(container_cpu_usage_seconds_total{selector}[30s])",
            "workingSetBytes": f"container_memory_working_set_bytes{selector}",
            "networkTransmitBytesPerSecond30s": f"rate(container_network_transmit_bytes_total{selector}[30s])",
        }
        captured[service] = {key: evidence.query_range(query, start, end)
                             for key, query in queries.items()}
    evidence.write_json(root / "scoped-resources.json", captured)


def gzip_probe(session_id):
    captured = {}
    bodies = {}
    for encoding in ("identity", "gzip"):
        request = Request(run_k6.BACKEND_URL + f"/sessions/{session_id}/seats",
                          headers={"Accept-Encoding": encoding})
        with build_opener(ProxyHandler({})).open(request, timeout=15) as response:
            body = response.read()  # urllib does not auto-decompress Content-Encoding.
            captured[encoding] = {
                "status": response.status, "contentEncoding": response.headers.get("Content-Encoding"),
                "contentLength": response.headers.get("Content-Length"),
                "transferEncoding": response.headers.get("Transfer-Encoding"),
                "receivedBodyBytes": len(body),
            }
            bodies[encoding] = gzip.decompress(body) if response.headers.get("Content-Encoding") == "gzip" else body
    if captured["gzip"]["contentEncoding"] != "gzip":
        raise RuntimeError("gzip contract did not negotiate gzip")
    if bodies["identity"] != bodies["gzip"]:
        raise RuntimeError("identity/gzip response bodies differ")
    payload = json.loads(bodies["identity"])
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("invalid Seat Map contract")
    captured["rawBodyBytes"] = len(bodies["identity"])
    captured["seatCount"] = len(payload)
    captured["bodyEquality"] = True
    return captured


def sample():
    started = time.time()
    values = metrics()
    raw = evidence.command(run_k6.compose_command(
        "exec", "-T", "redis", "sh", "-c",
        "redis-cli --raw CLIENT LIST; redis-cli --raw INFO memory"))
    clients_raw, memory_raw = raw.split("# Memory", 1)
    backend = evidence.command(run_k6.compose_command(
        "exec", "-T", "backend", "sh", "-c",
        "cat /proc/1/status; cat /sys/fs/cgroup/memory.current; cat /sys/fs/cgroup/memory.stat"))
    return {"epoch": started, "sampleEndEpoch": time.time(),
            "seatMapInFlight": values.get("ticketing_seat_map_requests_in_flight"),
            "httpInFlight": values.get("ticketing_http_requests_in_flight"),
            "seatResponses": sum(value for key, value in values.items()
                                 if key.startswith("ticketing_http_requests_total{")
                                 and 'route="/sessions/{sessionId}/seats"' in key),
            "clients": parse_clients(clients_raw),
            "redisMemory": evidence.parse_redis_info(memory_raw),
            "backendProcessAndCgroup": backend,
            "postgresConnections": int(evidence.psql("SELECT count(*) FROM pg_stat_activity WHERE datname='ticketing';").strip())}


def prepare_profile(seats, root):
    profile = run_k6.read_json(ROOT / "performance/data/profiles/scale-100k.json")
    profile["name"] = f"seat-map-{seats}"
    profile["seatLayout"]["seatsPerRow"] = seats // 10
    path = root / "profile.json"
    evidence.write_json(path, profile)
    for arguments in (
        [sys.executable, str(ROOT / "performance/data/generate_dataset.py"), "--profile", str(path)],
        [sys.executable, str(run_k6.VERIFIER)],
    ):
        result = run_k6.run_command(arguments)
        run_k6.print_console(result.stdout)
    run_k6.clear_auth_cache()
    run_k6.clear_seat_holds()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seats", type=int, choices=(1000, 2500, 5000), required=True)
    parser.add_argument("--rate", type=int, choices=(10, 30, 60, 100), default=10)
    parser.add_argument("--duration", type=int, choices=(15, 30), default=15)
    parser.add_argument("--drain-seconds", type=int, choices=(0, 120, 180, 300), default=0)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-seat-diagnosis-{args.seats}-{args.rate}"
    root = run_k6.RESULTS_ROOT / name
    root.mkdir(parents=True, exist_ok=False)
    try:
        if args.prepare:
            prepare_profile(args.seats, root)
        dataset = run_k6.read_json(run_k6.GENERATED_ROOT / "dataset.json")
        probe = gzip_probe(dataset["seatMapSessionId"])
        evidence.write_json(root / "gzip.json", probe)
        if probe["seatCount"] != args.seats:
            raise RuntimeError("actual Seat Map count does not match experiment")
        baseline = sample()
        if baseline["httpInFlight"] != 0:
            raise RuntimeError("existing in-flight requests; refusing additional load")
        evidence.write_json(root / "baseline.json", baseline)
        before = metrics()
        evidence.write_json(root / "metrics-before.json", before)
        evidence.reset_statement_stats()
        start = time.time()
        existing = set(run_k6.RESULTS_ROOT.iterdir())
        with (root / "runner.log").open("w", encoding="utf-8") as console:
            process = subprocess.Popen([
                sys.executable, str(ROOT / "performance/scripts/run_k6.py"),
                "seat-map-read", "--mode", "steady", "--rate", str(args.rate),
                "--duration", f"{args.duration}s", "--preallocated-vus", "700",
                "--seat-hold-density", "0",
            ], stdout=console, stderr=subprocess.STDOUT, cwd=ROOT)
            finished = None
            with (root / "samples.jsonl").open("w", encoding="utf-8") as output:
                while True:
                    try:
                        current = sample()
                    except Exception as error:
                        current = {"epoch": time.time(), "samplingError": str(error)}
                    output.write(json.dumps(current) + "\n")
                    output.flush()
                    if process.poll() is not None:
                        if finished is None:
                            finished = time.time()
                            print(f"Arrival runner finished; observing {args.drain_seconds}s without restart", flush=True)
                        if time.time() - finished >= args.drain_seconds:
                            break
                    time.sleep(1)
        after = metrics()
        evidence.write_json(root / "metrics-after.json", after)
        evidence.write_json(root / "stages.json", stage_summary(before, after))
        evidence.collect_postgres(root)
        evidence.collect_redis(root, "after")
        evidence.collect_prometheus(root, start, time.time())
        evidence.collect_docker_stats(root)
        created = sorted(str(path) for path in set(run_k6.RESULTS_ROOT.iterdir()) - existing)
        for path in created:
            if (Path(path) / "run-manifest.json").exists():
                collect_run_resources(root, Path(path), start, time.time())
        verifier = run_k6.run_command([sys.executable, str(run_k6.VERIFIER)], check=False)
        (root / "verifier.txt").write_text(verifier.stdout + verifier.stderr, encoding="utf-8")
        evidence.write_json(root / "manifest.json", {
            "arguments": vars(args), "startEpoch": start, "runnerFinishedEpoch": finished,
            "endEpoch": time.time(), "runnerExit": process.returncode,
            "runDirectories": created, "verifierExit": verifier.returncode,
            "finalInFlight": after.get("ticketing_seat_map_requests_in_flight"),
            "gitHead": run_k6.run_command(["git", "rev-parse", "HEAD"]).stdout.strip(),
            "gitDirty": bool(run_k6.run_command(["git", "status", "--porcelain"]).stdout.strip()),
        })
        print(f"Evidence: {root}", flush=True)
        return 0 if process.returncode == 0 and verifier.returncode == 0 else 1
    except Exception as error:
        (root / "error.txt").write_text(str(error), encoding="utf-8")
        print(f"[FAIL] {error}; evidence={root}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
