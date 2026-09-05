#!/usr/bin/env python3
"""Run a JSON Phase 10A plan and attach system evidence to every measured run."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import shutil

import performance_evidence as evidence
from run_k6 import GENERATED_ROOT, REPO_ROOT, RESULTS_ROOT, clear_auth_cache, clear_seat_holds


def execute(arguments: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        arguments, cwd=REPO_ROOT, env=env, text=True, encoding="utf-8",
        errors="replace", capture_output=True, check=False,
    )
    stdout_encoding = sys.stdout.encoding or "utf-8"
    print(completed.stdout.encode(stdout_encoding, errors="replace").decode(stdout_encoding), end="")
    if completed.returncode != 0:
        stderr_encoding = sys.stderr.encoding or "utf-8"
        print(
            completed.stderr.encode(stderr_encoding, errors="replace").decode(stderr_encoding),
            file=sys.stderr, end="",
        )
        raise RuntimeError(f"command failed ({completed.returncode}): {subprocess.list2cmdline(arguments)}")
    return completed


def logical_reset(profile: str) -> None:
    execute([sys.executable, str(REPO_ROOT / "performance/data/generate_dataset.py"), "--profile", profile])
    clear_auth_cache(); clear_seat_holds()


def warmup_system() -> None:
    evidence.command(["curl.exe", "-fsS", "http://127.0.0.1:18080/health"])
    evidence.command(["curl.exe", "-fsS", "http://127.0.0.1:18080/events"])


def reset_environment(kind: str, profile: str, allow_destructive: bool) -> None:
    if kind == "none": return
    if kind == "logical": logical_reset(profile); return
    if not allow_destructive:
        raise RuntimeError("full reset requires --allow-destructive-reset")
    execute([sys.executable, str(REPO_ROOT / "performance/scripts/reset_environment.py"), "--profile", profile, "--yes"])


def newest_result(before: set[Path]) -> Path:
    created = set(path for path in RESULTS_ROOT.iterdir() if path.is_dir()) - before
    if len(created) != 1:
        raise RuntimeError(f"expected exactly one measured result directory, got {sorted(created)}")
    return created.pop()


def run_entry(entry: dict, password: str | None, allow_destructive: bool) -> Path:
    reset_environment(
        entry.get("reset", "logical"), entry.get("profile", "baseline"),
        allow_destructive,
    )
    warmup_system()
    for warmup in entry.get("warmup", []):
        execute([sys.executable, str(REPO_ROOT / "performance/scripts/run_k6.py"), *warmup])
    stats_reset = evidence.reset_statement_stats()
    before = set(path for path in RESULTS_ROOT.iterdir() if path.is_dir())
    with tempfile.TemporaryDirectory(prefix="phase10a-evidence-") as directory:
        temporary = Path(directory)
        evidence.collect_redis(temporary, "before")
        start_epoch = time.time(); since = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        env = os.environ.copy()
        if password: env["TICKETING_PERF_LOGIN_PASSWORD"] = password
        command = [sys.executable, str(REPO_ROOT / "performance/scripts/run_k6.py"), *entry["args"]]
        execute(command, env=env)
        end_epoch = time.time()
        root = newest_result(before)
        for artifact in temporary.iterdir():
            shutil.copy2(artifact, root / artifact.name)
    evidence.collect_redis(root, "after")
    evidence.collect_postgres(root)
    evidence.collect_prometheus(root, start_epoch, end_epoch)
    evidence.collect_docker_stats(root)
    evidence.collect_logs(root, since)
    evidence.write_json(root / "environment.json", evidence.environment_fingerprint())
    evidence.write_json(root / "evidence-manifest.json", {
        "name": entry["name"], "statsReset": stats_reset,
        "startEpoch": start_epoch, "endEpoch": end_epoch,
        "reset": entry.get("reset", "logical"), "profile": entry.get("profile", "baseline"),
    })
    return root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--login-password", default=os.environ.get("TICKETING_PERF_LOGIN_PASSWORD"))
    parser.add_argument("--allow-destructive-reset", action="store_true")
    parser.add_argument("--only", action="append", default=[], help="run only matching plan entry names")
    args = parser.parse_args()
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8"))
        entries = plan["runs"]
        if args.only:
            requested = set(args.only)
            entries = [entry for entry in entries if entry["name"] in requested]
            missing = requested - {entry["name"] for entry in entries}
            if missing:
                raise RuntimeError(f"plan entries not found: {sorted(missing)}")
        for entry in entries:
            print(f"=== {entry['name']} ===")
            root = run_entry(entry, args.login_password, args.allow_destructive_reset)
            print(f"[PASS] evidence: {root}")
        return 0
    except (OSError, KeyError, ValueError, RuntimeError, json.JSONDecodeError) as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__": raise SystemExit(main())
