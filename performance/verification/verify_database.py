#!/usr/bin/env python3
"""Run the read-only Phase 10A PostgreSQL invariant verifier."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COMPOSE_FILE = REPO_ROOT / "performance" / "docker-compose.performance.yml"
DEFAULT_SQL_FILE = Path(__file__).resolve().with_name("verify.sql")
PROJECT_NAME = "ticketing-phase10a"
EXPECTED_CHECKS = {
    "effective_seat_overlap",
    "active_reservation_seat_mismatch",
    "held_seat_owner_mismatch",
    "confirmed_state_mismatch",
    "sold_state_mismatch",
    "order_reservation_status_mismatch",
    "order_paid_at_mismatch",
    "order_amount_mismatch",
    "terminal_reservation_still_holds",
    "accepted_payment_mismatch",
    "unaccepted_success_refund_mismatch",
    "multiple_processing_attempts",
    "multiple_refunds",
    "refund_order_or_amount_mismatch",
}


def parse_verifier_output(output: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for line_number, line in enumerate(output.splitlines(), start=1):
        if not line.strip():
            continue
        pieces = line.split("\t")
        if len(pieces) != 2:
            raise ValueError(f"invalid verifier row {line_number}: {line!r}")
        name, raw_count = pieces
        if name in result:
            raise ValueError(f"duplicate verifier check: {name}")
        try:
            count = int(raw_count)
        except ValueError as error:
            raise ValueError(f"invalid violation count for {name}: {raw_count}") from error
        if count < 0:
            raise ValueError(f"negative violation count for {name}")
        result[name] = count
    missing = EXPECTED_CHECKS - result.keys()
    extra = result.keys() - EXPECTED_CHECKS
    if missing or extra:
        raise ValueError(
            f"verifier check set mismatch: missing={sorted(missing)}, extra={sorted(extra)}"
        )
    return result


def execute_verifier(compose_file: Path, sql_file: Path) -> str:
    sql = sql_file.read_text(encoding="utf-8")
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "-p",
            PROJECT_NAME,
            "-f",
            str(compose_file),
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "ticketing",
            "-d",
            "ticketing",
            "-v",
            "ON_ERROR_STOP=1",
            "-At",
            "-F",
            "\t",
        ],
        cwd=REPO_ROOT,
        input=sql,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE_FILE)
    parser.add_argument("--sql-file", type=Path, default=DEFAULT_SQL_FILE)
    args = parser.parse_args()
    try:
        checks = parse_verifier_output(
            execute_verifier(args.compose_file.resolve(), args.sql_file.resolve())
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"[FAIL] verifier execution: {error}", file=sys.stderr)
        return 1
    failed = False
    for name in sorted(checks):
        count = checks[name]
        state = "PASS" if count == 0 else "FAIL"
        print(f"[{state}] {name}: violation_count={count}")
        failed = failed or count != 0
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
