"""One bounded generator-only qualification point. Never starts a higher tier automatically."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

from resource_gate import stop_reason

HERE = Path(__file__).resolve().parent


def run(*args, timeout=30):
    p = subprocess.run(list(map(str, args)), capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    if p.returncode:
        raise RuntimeError(str(args[:3]) + ": " + p.stderr[-1500:])
    return p.stdout.strip()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def sample(name, previous=None):
    raw = run("docker", "exec", "--user", "0", name, "sh", "-c",
        "cat /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.max /sys/fs/cgroup/cpu.stat /proc/meminfo /proc/vmstat /proc/1/status /proc/1/limits; ls /proc/1/fd | wc -l; cat /proc/1/net/tcp /proc/1/net/tcp6 | wc -l")
    def value(pattern):
        found = re.search(pattern, raw, re.M)
        if not found:
            raise RuntimeError("Missing process observation: " + pattern)
        return int(found.group(1))
    now = time.monotonic()
    usage = value(r"^usage_usec (\d+)")
    swap = value(r"^pswpout (\d+)")
    row = {"utc": datetime.now(timezone.utc).isoformat(), "monotonic": now,
        "memory": int(raw.splitlines()[0]), "memoryLimit": int(raw.splitlines()[1]),
        "rss": value(r"^VmRSS:\s+(\d+)")*1024, "rssPeak": value(r"^VmHWM:\s+(\d+)")*1024,
        "linuxAvailable": value(r"^MemAvailable:\s+(\d+)")*1024,
        "linuxTotal": value(r"^MemTotal:\s+(\d+)")*1024,
        "fdLimit": value(r"^Max open files\s+(\d+)"), "fd": int(raw.splitlines()[-2]),
        "tcpTableEntries": max(0, int(raw.splitlines()[-1])-2),
        "usageUsec": usage, "swapOutTotal": swap,
        "swapOutPages": 0 if previous is None else max(0, swap-previous["swapOutTotal"]),
        "cpuFraction": 0 if previous is None else (usage-previous["usageUsec"])/1e6/(now-previous["monotonic"])/2}
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--vus", type=int, choices=[100, 250, 500, 1000, 2000, 3000], required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=60)
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists():
        raise RuntimeError("Refusing to overwrite an earlier qualification point")
    out.mkdir(parents=True)
    fixture = out / "fixture"
    fixture.mkdir()
    # Synthetic credentials are inert stub data, never valid SUT sessions.
    save(fixture / "users.json", [{"userId": f"phase19-stub-{i}", "sessionToken": "stub", "csrfToken": "stub"} for i in range(5000)])
    save(fixture / "config.json", {"zones": [f"Zone {i}" for i in range(5)], "readerSession": "phase19-reader", "writerSession": "phase19-writer", "writerSeats": [], "holdTtlSeconds": 5})
    prefix = "phase19-calibration-" + str(args.vus)
    network, stub, generator = prefix + "-network", prefix + "-stub", prefix + "-k6"
    images = {role: json.loads(run("docker", "image", "inspect", image))[0]
              for role, image in [("k6", "grafana/k6:2.2.0"), ("stub", "python:3.12-alpine")]}
    identity = {"startedUtc": datetime.now(timezone.utc).isoformat(), "actualVUsRequested": args.vus,
        "observationSeconds": args.seconds, "initialIdleSeconds": 15,
        "protocolSha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in HERE.iterdir() if p.is_file()},
        "images": {role: {"id": obj["Id"], "digests": obj["RepoDigests"]} for role, obj in images.items()},
        "limits": {"generator": {"cpus": 2, "memoryBytes": 2147483648, "pids": 256, "nofile": 16384}, "stub": {"cpus": 1, "memoryBytes": 268435456}}}
    save(out / "identity.json", identity)
    created = []
    rows, stop, exit_code = [], None, None
    started = time.monotonic()
    try:
        run("docker", "network", "create", "--internal", network)
        created.append(network)
        run("docker", "run", "-d", "--name", stub, "--network", network, "--network-alias", "stub",
            "--cpus", "1", "--memory", "256m", "--pids-limit", "256", "--ulimit", "nofile=16384:16384",
            "--mount", f"type=bind,source={HERE},target=/protocol,readonly", images["stub"]["Id"], "python", "/protocol/stub.py")
        created.append(stub)
        run("docker", "run", "-d", "--name", generator, "--network", network,
            "--cpus", "2", "--memory", "2g", "--pids-limit", "256", "--ulimit", "nofile=16384:16384",
            "--mount", f"type=bind,source={HERE},target=/protocol,readonly",
            "--mount", f"type=bind,source={fixture},target=/fixture,readonly", "--mount", f"type=bind,source={out},target=/output",
            "-e", "MODE=closed", "-e", f"VUS={args.vus}", "-e", f"SECONDS={args.seconds+15}",
            "-e", "INIT_IDLE_SECONDS=15", "-e", "WARMUP_SECONDS=15", "-e", "BASE_URL=http://stub:8080",
            images["k6"]["Id"], "run", "--quiet", "/protocol/workload.js")
        created.append(generator)
        while True:
            info = json.loads(run("docker", "inspect", generator))[0]
            state = info["State"]
            if not state["Running"]:
                exit_code = state["ExitCode"]
                if state["OOMKilled"]:
                    stop = "OOM"
                break
            try:
                row = sample(generator, rows[-1] if rows else None)
            except RuntimeError:
                if not json.loads(run("docker", "inspect", generator))[0]["State"]["Running"]:
                    continue
                raise
            row["elapsedSeconds"] = time.monotonic()-started
            rows.append(row)
            save(out / "resource-samples.json", rows)
            stop = stop_reason(rows)
            if time.monotonic()-started > args.seconds+150:
                stop = "Qualification wall-clock deadline exceeded"
            if stop:
                run("docker", "stop", "--timeout", "5", generator)
                break
            time.sleep(1)
    except Exception as error:
        stop = str(error)
    finally:
        for name in [generator, stub]:
            if name in created:
                logs = subprocess.run(["docker", "logs", name], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", check=True).stdout
                (out / ("k6.log" if name == generator else "stub.log")).write_text(logs, encoding="utf-8")
        for name in reversed(created):
            if name == network:
                run("docker", "network", "rm", name)
            else:
                run("docker", "rm", "-f", name)
    summary = json.loads((out / "k6-summary.json").read_text()) if (out / "k6-summary.json").exists() else None
    metrics = summary["data"]["metrics"] if summary else {}
    count = lambda name: metrics.get(name, {}).get("values", {}).get("count", 0)
    dropped = count("dropped_iterations")
    interrupted = count("phase19_started") - count("phase19_completed")
    idle = [r for r in rows if 10 <= r["elapsedSeconds"] < 15]
    result = {"valid": bool(summary and rows and not stop and exit_code == 0 and not dropped and not interrupted and count("phase19_initialized_vus") == args.vus),
        "reason": stop, "exitCode": exit_code, "vus": args.vus, "initializedVUs": count("phase19_initialized_vus"),
        "droppedIterations": dropped, "startedIterations": count("phase19_started"), "completedIterations": count("phase19_completed"),
        "interruptedOrUncompletedIterations": interrupted,
        "peakBytes": max((r["rssPeak"] for r in rows), default=0), "peakCgroupBytes": max((r["memory"] for r in rows), default=0),
        "cpuPeakQuotaFraction": max((r["cpuFraction"] for r in rows), default=0), "fdPeak": max((r["fd"] for r in rows), default=0),
        "tcpTableEntriesPeak": max((r["tcpTableEntries"] for r in rows), default=0),
        "idleRssBytes": idle[-1]["rss"] if idle else None,
        "elapsedSeconds": time.monotonic()-started, "sampling": "approximately 1-2s; startup before first sample can be missed",
        "cleanup": "only point-owned containers and network removed"}
    save(out / "result.json", result)
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
