#!/usr/bin/env python3
"""Run evidence-backed Phase 10B login worker/queue experiments."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

import run_baseline
from run_k6 import COMPOSE_FILE, PROJECT, REPO_ROOT, RunError, write_json


PERFORMANCE_ROOT = REPO_ROOT / "performance"
SOURCE_CONFIG = REPO_ROOT / "backend" / "config" / "config.performance.json"
GENERATED_CONFIG = PERFORMANCE_ROOT / "generated" / "auth-experiment-config.json"
COMPOSE_OVERRIDE = PERFORMANCE_ROOT / "auth-experiment-compose.yml"
ALLOWED_CHANGES = {
    ("custom_config", "authentication", "password_hash_workers"),
    ("custom_config", "authentication", "password_hash_queue_capacity"),
}


def changed_paths(left: Any, right: Any, prefix: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    if type(left) is not type(right):
        return {prefix}
    if isinstance(left, dict):
        paths: set[tuple[str, ...]] = set()
        for key in left.keys() | right.keys():
            if key not in left or key not in right:
                paths.add(prefix + (str(key),))
            else:
                paths.update(changed_paths(left[key], right[key], prefix + (str(key),)))
        return paths
    if isinstance(left, list):
        if len(left) != len(right):
            return {prefix}
        paths: set[tuple[str, ...]] = set()
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            paths.update(changed_paths(left_item, right_item, prefix + (str(index),)))
        return paths
    return set() if left == right else {prefix}


def build_experiment_config(workers: int, queue_capacity: int) -> dict[str, Any]:
    if workers <= 0 or queue_capacity <= 0:
        raise ValueError("workers and queue capacity must be positive")
    source = json.loads(SOURCE_CONFIG.read_text(encoding="utf-8"))
    candidate = copy.deepcopy(source)
    authentication = candidate["custom_config"]["authentication"]
    authentication["password_hash_workers"] = workers
    authentication["password_hash_queue_capacity"] = queue_capacity
    changes = changed_paths(source, candidate)
    unexpected = changes - ALLOWED_CHANGES
    if unexpected:
        raise RuntimeError(f"auth experiment changed forbidden config paths: {sorted(unexpected)}")
    return candidate


def config_sha256(config: dict[str, Any]) -> str:
    payload = json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compose_arguments(*arguments: str, experiment: bool) -> list[str]:
    command = ["docker", "compose", "-p", PROJECT, "-f", str(COMPOSE_FILE)]
    if experiment:
        command.extend(["-f", str(COMPOSE_OVERRIDE)])
    return [*command, *arguments]


def execute(arguments: list[str]) -> None:
    completed = subprocess.run(
        arguments,
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RunError(
            f"command failed ({completed.returncode}): {' '.join(arguments)}\n"
            f"{completed.stdout}{completed.stderr}"
        )


def recreate_backend(*, experiment: bool) -> None:
    execute(
        compose_arguments(
            "up", "-d", "--no-deps", "--force-recreate", "--wait", "backend",
            experiment=experiment,
        )
    )


def attach_experiment_metadata(
    result_root: Path,
    *,
    workers: int,
    queue_capacity: int,
    config_hash: str,
) -> None:
    path = result_root / "evidence-manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["authExperiment"] = {
        "passwordHashWorkers": workers,
        "passwordHashQueueCapacity": queue_capacity,
        "configSha256": config_hash,
    }
    write_json(path, manifest)


def run(args: argparse.Namespace) -> list[Path]:
    config = build_experiment_config(args.workers, args.queue_capacity)
    config_hash = config_sha256(config)
    write_json(GENERATED_CONFIG, config)
    recreate_backend(experiment=True)
    roots: list[Path] = []
    try:
        for rate in args.rate:
            for repetition in range(1, args.repetitions + 1):
                entry = {
                    "name": (
                        f"login-w{args.workers}-q{args.queue_capacity}-"
                        f"r{rate}-rep{repetition}"
                    ),
                    "profile": args.profile,
                    "reset": "logical",
                    "args": [
                        "login", "--mode", "steady", "--rate", str(rate),
                        "--duration", args.duration, "--preallocated-vus",
                        str(args.preallocated_vus),
                    ],
                }
                root = run_baseline.run_entry(entry, args.login_password, False)
                attach_experiment_metadata(
                    root,
                    workers=args.workers,
                    queue_capacity=args.queue_capacity,
                    config_hash=config_hash,
                )
                roots.append(root)
                print(f"[PASS] {entry['name']}: {root}")
    finally:
        recreate_backend(experiment=False)
    return roots


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--workers", type=int, required=True)
    result.add_argument("--queue-capacity", type=int, required=True)
    result.add_argument("--rate", type=int, action="append", required=True)
    result.add_argument("--duration", default="30s")
    result.add_argument("--repetitions", type=int, default=1)
    result.add_argument("--preallocated-vus", type=int, default=160)
    result.add_argument("--profile", default="baseline")
    result.add_argument(
        "--login-password",
        default=os.environ.get("TICKETING_PERF_LOGIN_PASSWORD"),
    )
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if not args.login_password:
            raise ValueError(
                "--login-password or TICKETING_PERF_LOGIN_PASSWORD is required"
            )
        if args.repetitions <= 0 or args.preallocated_vus <= 0:
            raise ValueError("repetitions and preallocated VUs must be positive")
        if any(rate <= 0 for rate in args.rate):
            raise ValueError("rates must be positive")
        run(args)
        return 0
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
