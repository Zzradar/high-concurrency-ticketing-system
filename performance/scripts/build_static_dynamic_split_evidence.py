#!/usr/bin/env python3
"""Build the reviewed split evidence bundle from explicit immutable run IDs."""
import argparse
import json
from pathlib import Path

import run_k6
from summarize_seat_map_capacity import summarize


EXPERIMENT_ROOT = (
    run_k6.REPO_ROOT / "performance/experiments/phase10b-seat-map"
)
HISTORICAL_PATH = EXPERIMENT_ROOT / "post-offload-capacity-measurements.json"


def response_bytes(run):
    probe = run["gzip"]
    return {
        "endpoint": probe["endpoint"] if "endpoint" in probe else "seats",
        "raw": probe["rawBodyBytes"],
        "gzip": probe["gzip"]["receivedBodyBytes"],
        "seatCount": probe["seatCount"],
    }


def build(run_ids):
    runs = [summarize(run_id) for run_id in run_ids]
    if any(run.get("incomplete") for run in runs):
        raise RuntimeError("incomplete split run cannot enter evidence")
    historical = json.loads(HISTORICAL_PATH.read_text(encoding="utf-8"))
    before = [
        run for run in historical["runs"]
        if not run["arguments"]["mixed"]
        and run["arguments"]["duration"] == 15
        and run["arguments"]["rate"] in (60, 100)
    ]
    availability_zero = next(
        run for run in runs
        if run["arguments"]["kind"] == "availability"
        and run["arguments"]["density"] == 0
    )
    availability_ninety = next(
        run for run in runs
        if run["arguments"]["kind"] == "availability"
        and run["arguments"]["density"] == 90
    )
    layout = next(
        run for run in runs if run["arguments"]["kind"] == "layout"
    )
    legacy_zero = next(run for run in before if run["arguments"]["density"] == 0)
    legacy_ninety = next(run for run in before if run["arguments"]["density"] == 90)
    return {
        "scope": {
            "comparison": "historical controlled full refresh versus current availability refresh",
            "historicalSource": str(HISTORICAL_PATH.relative_to(run_k6.REPO_ROOT)),
            "workers": 4,
            "queueCapacity": 16,
            "postgresPool": 4,
            "seatHoldRedisPool": 2,
            "redisTimeoutSeconds": 0.4,
            "mixed4Executed": False,
            "mixed4Reason": "single availability 300/s was already first observed unstable",
            "mixed8Executed": False,
            "layoutCacheImplemented": False,
            "deltaOrPushImplemented": False,
        },
        "responseBytes": {
            "legacy0": response_bytes(legacy_zero),
            "legacy90": response_bytes(legacy_ninety),
            "layout": response_bytes(layout),
            "availability0": response_bytes(availability_zero),
            "availability90": response_bytes(availability_ninety),
        },
        "historicalBeforeRuns": before,
        "runs": runs,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_ids", nargs="+")
    parser.add_argument(
        "--output",
        type=Path,
        default=EXPERIMENT_ROOT / "static-dynamic-split-measurements.json",
    )
    args = parser.parse_args()
    payload = build(args.run_ids)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(args.output)


if __name__ == "__main__":
    main()
