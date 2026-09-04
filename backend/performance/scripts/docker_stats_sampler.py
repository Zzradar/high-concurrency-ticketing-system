#!/usr/bin/env python3
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time


PROJECT = "ticketing-phase10a"
FIELDS = (
    "timestamp",
    "container",
    "cpu_percent",
    "memory_usage",
    "memory_percent",
    "network_io",
    "block_io",
    "pids",
)


def phase_containers() -> list[str]:
    completed = subprocess.run(
        [
            "docker",
            "ps",
            "--filter",
            f"label=com.docker.compose.project={PROJECT}",
            "--format",
            "{{.Names}}",
        ],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "docker ps failed")
    names = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not names:
        raise RuntimeError(f"no running containers found for Compose project {PROJECT}")
    return names


def sample(names: list[str]) -> list[dict[str, str]]:
    completed = subprocess.run(
        ["docker", "stats", "--no-stream", "--format", "{{json .}}", *names],
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "docker stats failed")
    timestamp = datetime.now(timezone.utc).isoformat()
    records = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        records.append(
            {
                "timestamp": timestamp,
                "container": value.get("Name", value.get("Container", "")),
                "cpu_percent": value.get("CPUPerc", ""),
                "memory_usage": value.get("MemUsage", ""),
                "memory_percent": value.get("MemPerc", ""),
                "network_io": value.get("NetIO", ""),
                "block_io": value.get("BlockIO", ""),
                "pids": value.get("PIDs", ""),
            }
        )
    if len(records) != len(names):
        raise RuntimeError(
            f"docker stats returned {len(records)} rows for {len(names)} containers"
        )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Sample Phase 10A containers with docker stats")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--samples", type=int, default=0, help="0 means run until Ctrl+C")
    parser.add_argument("--format", choices=("csv", "jsonl"), default="csv")
    parser.add_argument("--output", type=Path, default=Path("docker-stats.csv"))
    args = parser.parse_args()
    if args.interval <= 0 or args.samples < 0:
        parser.error("interval must be positive and samples must be non-negative")

    try:
        names = phase_containers()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if args.output.exists() else "w"
        with args.output.open(mode, newline="", encoding="utf-8") as output:
            writer = csv.DictWriter(output, fieldnames=FIELDS) if args.format == "csv" else None
            if writer and mode == "w":
                writer.writeheader()
            count = 0
            while args.samples == 0 or count < args.samples:
                for record in sample(names):
                    if writer:
                        writer.writerow(record)
                    else:
                        output.write(json.dumps(record, ensure_ascii=False) + "\n")
                output.flush()
                count += 1
                if args.samples == 0 or count < args.samples:
                    time.sleep(args.interval)
        print(f"wrote {count} sample set(s) for {len(names)} containers to {args.output}")
        return 0
    except KeyboardInterrupt:
        print("sampling stopped by user")
        return 0
    except (OSError, RuntimeError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
