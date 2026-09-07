#!/usr/bin/env python3
"""Build checked-in Phase10B-3.5 evidence from bounded raw run directories."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "performance/results"
EXPERIMENT = ROOT / "performance/experiments/phase10b-seat-map"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def transfer_series(response_bytes: dict, density: int) -> list[dict]:
    legacy = response_bytes[f"legacy{density}"]
    layout = response_bytes["layout"]
    availability = response_bytes[f"availability{density}"]
    return [
        {
            "milestone": milestone,
            "snapshots": snapshots,
            "legacyRawBytes": legacy["raw"] * snapshots,
            "legacyGzipBytes": legacy["gzip"] * snapshots,
            "splitRawBytes": layout["raw"] + availability["raw"] * snapshots,
            "splitGzipBytes": layout["gzip"] + availability["gzip"] * snapshots,
        }
        for milestone, snapshots in (
            ("initial-entry", 1), ("after-first-selection", 2), ("after-second-selection", 3)
        )
    ]


def peak(samples: list[dict], *path: str) -> float:
    values = []
    for sample in samples:
        value = sample
        try:
            for key in path:
                value = value[key]
            values.append(float(value))
        except (KeyError, TypeError, ValueError):
            pass
    return max(values, default=0.0)


def collect_run(run_id: str) -> dict:
    directory = RESULTS / run_id
    manifest = read_json(directory / "run-manifest.json")
    summary = read_json(directory / "k6-summary.json")
    samples = [json.loads(line) for line in
               (directory / "samples.jsonl").read_text(encoding="utf-8").splitlines() if line]
    redis_omem = max((float(client.get("omem", 0)) for sample in samples
                      for client in sample.get("clients", [])), default=0.0)
    docker_stats = [json.loads(line) for line in
                    (directory / "docker-stats.jsonl").read_text(encoding="utf-8").splitlines() if line]
    return {
        "runId": run_id,
        "manifest": manifest,
        "k6Summary": summary,
        "stages": read_json(directory / "stages.json"),
        "samples": samples,
        "resourcePeaks": {
            "computeQueueDepth": peak(samples, "seatMapCompute", "ticketing_seat_map_compute_queue_depth"),
            "computeActiveWorkers": peak(samples, "seatMapCompute", "ticketing_seat_map_compute_active_workers"),
            "seatMapInFlight": peak(samples, "seatMapInFlight"),
            "redisClientOmemBytes": redis_omem,
        },
        "postgresTopSql": read_json(directory / "postgres-top-sql.json"),
        "postgresActivity": read_json(directory / "postgres-activity.json"),
        "postgresLocks": read_json(directory / "postgres-locks.json"),
        "redisAfter": read_json(directory / "redis-after.json"),
        "dockerStats": docker_stats,
        "databaseVerifier": (directory / "verifier.txt").read_text(encoding="utf-8"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", required=True)
    parser.add_argument("--browser", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    previous = read_json(EXPERIMENT / "static-dynamic-split-measurements.json")
    payload = {
        "scope": {
            "gitHead": "f18d34cc10bf1b53f0e031e7335afb1e7447a0d9",
            "fixedResources": {"computeWorkers": 4, "computeQueue": 16,
                               "postgresPool": 4, "redisPool": 2, "redisTimeoutSeconds": 0.4},
            "mixed4Executed": False,
            "mixed4Reason": "page 60/s plus refresh 240/s reaches the known 300 availability/s unstable pressure",
            "mixed8Executed": False,
        },
        "browserFlow": read_json(args.browser),
        "responseBytes": previous["responseBytes"],
        "cumulativeTransfer0Percent": transfer_series(previous["responseBytes"], 0),
        "cumulativeTransfer90Percent": transfer_series(previous["responseBytes"], 90),
        "runs": [collect_run(run_id) for run_id in args.run],
    }
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[PASS] wrote {args.output} with {len(payload['runs'])} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
