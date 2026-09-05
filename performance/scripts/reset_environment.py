#!/usr/bin/env python3
"""Safely rebuild the isolated Phase 10A stack and generate a fresh dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time


REPO_ROOT = Path(__file__).resolve().parents[2]
PERFORMANCE_ROOT = REPO_ROOT / "performance"
COMPOSE_FILE = PERFORMANCE_ROOT / "docker-compose.performance.yml"
GENERATED_ROOT = PERFORMANCE_ROOT / "generated"
PROJECT_NAME = "ticketing-phase10a"
PERFORMANCE_VOLUME_PREFIX = "ticketing_phase10a_"
DEVELOPMENT_VOLUME = "backend_ticketing_postgres_data"


class ResetGuardError(RuntimeError):
    pass


def compose_command(*arguments: str) -> list[str]:
    return [
        "docker",
        "compose",
        "-p",
        PROJECT_NAME,
        "-f",
        str(COMPOSE_FILE),
        *arguments,
    ]


def run_command(arguments: list[str]) -> None:
    print("+ " + subprocess.list2cmdline(arguments))
    completed = subprocess.run(arguments, cwd=REPO_ROOT, check=False)
    if completed.returncode != 0:
        raise ResetGuardError(
            f"command failed with exit code {completed.returncode}: "
            f"{subprocess.list2cmdline(arguments)}"
        )


def run_command_with_retries(
    arguments: list[str], *, attempts: int, delay_seconds: float
) -> None:
    for attempt in range(1, attempts + 1):
        print(f"+ {subprocess.list2cmdline(arguments)} (attempt {attempt}/{attempts})")
        completed = subprocess.run(arguments, cwd=REPO_ROOT, check=False)
        if completed.returncode == 0:
            return
        if attempt < attempts:
            print(
                "Observability stack has not converged yet; "
                f"retrying in {delay_seconds:g} seconds."
            )
            time.sleep(delay_seconds)
    raise ResetGuardError(
        f"command failed after {attempts} attempts: "
        f"{subprocess.list2cmdline(arguments)}"
    )


def read_compose_model() -> dict:
    completed = subprocess.run(
        compose_command("config", "--format", "json"),
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ResetGuardError(completed.stderr.strip() or "cannot parse Compose config")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ResetGuardError(f"Compose config did not return JSON: {error}") from error


def validate_volume_names(project_name: str, volume_names: list[str]) -> None:
    if project_name != PROJECT_NAME:
        raise ResetGuardError(
            f"refusing reset for Compose project {project_name!r}; expected {PROJECT_NAME!r}"
        )
    if not volume_names:
        raise ResetGuardError("Compose model declares no named volumes")
    unsafe = sorted(
        name
        for name in volume_names
        if name == DEVELOPMENT_VOLUME or not name.startswith(PERFORMANCE_VOLUME_PREFIX)
    )
    if unsafe:
        raise ResetGuardError(f"refusing to delete non-Performance volumes: {unsafe}")


def guarded_volume_names(model: dict) -> list[str]:
    project_name = model.get("name")
    volumes = model.get("volumes")
    if not isinstance(volumes, dict):
        raise ResetGuardError("Compose model has no volumes object")
    names = []
    for key, value in volumes.items():
        if not isinstance(value, dict) or not isinstance(value.get("name"), str):
            raise ResetGuardError(f"Compose volume {key!r} has no explicit name")
        names.append(value["name"])
    validate_volume_names(project_name, names)
    return sorted(names)


def clear_generated() -> None:
    generated = GENERATED_ROOT.resolve()
    expected_parent = PERFORMANCE_ROOT.resolve()
    if generated.parent != expected_parent:
        raise ResetGuardError(f"unsafe generated directory: {generated}")
    for path in generated.iterdir():
        if path.name == ".gitignore":
            continue
        if path.is_dir():
            raise ResetGuardError(f"refusing unexpected generated subdirectory: {path}")
        path.unlink()


def reset(profile: str, *, confirmed: bool) -> None:
    if Path.cwd().resolve() != REPO_ROOT.resolve():
        raise ResetGuardError(f"run from repository root: {REPO_ROOT}")
    if not COMPOSE_FILE.is_file():
        raise ResetGuardError(f"Compose file is missing: {COMPOSE_FILE}")
    model = read_compose_model()
    volumes = guarded_volume_names(model)
    print(f"Compose project: {PROJECT_NAME}")
    print("Performance volumes selected for deletion:")
    for name in volumes:
        print(f"  - {name}")
    print(f"Dataset profile after rebuild: {profile}")
    if not confirmed:
        print("DRY RUN: no files, containers, or volumes were changed; pass --yes to execute.")
        return

    clear_generated()
    run_command(compose_command("down", "-v"))
    run_command(compose_command("up", "-d", "--build", "--wait"))
    run_command_with_retries(
        [sys.executable, str(PERFORMANCE_ROOT / "scripts" / "verify_observability.py")],
        attempts=6,
        delay_seconds=5,
    )
    run_command(
        [
            sys.executable,
            str(PERFORMANCE_ROOT / "data" / "generate_dataset.py"),
            "--profile",
            profile,
        ]
    )
    run_command(
        [
            sys.executable,
            str(PERFORMANCE_ROOT / "verification" / "verify_database.py"),
        ]
    )
    print(f"[PASS] fresh Phase 10A environment is ready with profile={profile}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="baseline")
    parser.add_argument("--yes", action="store_true", help="confirm Performance volume deletion")
    args = parser.parse_args()
    try:
        reset(args.profile, confirmed=args.yes)
        return 0
    except (OSError, ResetGuardError) as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
