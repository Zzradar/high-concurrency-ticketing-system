#!/usr/bin/env python3
"""Generate repeatable Phase 10A PostgreSQL data and offline auth sessions."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener


REPO_ROOT = Path(__file__).resolve().parents[2]
PERFORMANCE_ROOT = REPO_ROOT / "performance"
PROFILE_ROOT = PERFORMANCE_ROOT / "data" / "profiles"
GENERATED_ROOT = PERFORMANCE_ROOT / "generated"
COMPOSE_FILE = PERFORMANCE_ROOT / "docker-compose.performance.yml"
AUTH_CONFIG = REPO_ROOT / "backend" / "config" / "config.performance.json"
PROJECT_NAME = "ticketing-phase10a"
PERF_PREFIX = "perf-"
PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=2,p=1$tUON0+a+tW+XPmzdPL+RoA$"
    "OCRPrfDL//acztJL8FF4AhlFnL7GN03xL4mAsYextRo"
)
IDENTIFIER_RE = re.compile(r"^[a-z0-9-]+$")


class DatasetError(RuntimeError):
    pass


@dataclass(frozen=True)
class DatasetShape:
    users: int
    events: int
    sessions: int
    seats: int
    session_seats: int


def canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def profile_sha256(profile: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(profile)).hexdigest()


def performance_id(kind: str, *parts: int) -> str:
    if kind == "user":
        return f"perf-user-{parts[0]:06d}"
    if kind == "auth":
        return f"perf-auth-{parts[0]:06d}"
    if kind in {"venue", "event"}:
        return f"perf-{kind}-{parts[0]:03d}"
    if kind == "session":
        return f"perf-session-{parts[0]:03d}-{parts[1]:03d}"
    if kind == "seat":
        return f"perf-seat-{parts[0]:06d}"
    if kind == "session-seat":
        return (
            f"perf-ss-{parts[0]:03d}-{parts[1]:03d}-{parts[2]:06d}"
        )
    raise ValueError(f"unknown performance id kind: {kind}")


def validate_profile(profile: dict[str, Any]) -> DatasetShape:
    required = {
        "version",
        "name",
        "seed",
        "users",
        "events",
        "sessionsPerEvent",
        "seatLayout",
        "futureStartOffsetDays",
        "sessionSpacingHours",
        "gateLeadMinutes",
        "priceZones",
    }
    missing = sorted(required - profile.keys())
    if missing:
        raise ValueError(f"profile is missing fields: {', '.join(missing)}")
    if profile["version"] != 1:
        raise ValueError("only profile version 1 is supported")
    if not isinstance(profile["name"], str) or not IDENTIFIER_RE.fullmatch(
        profile["name"]
    ):
        raise ValueError("profile name must contain lowercase letters, digits or hyphens")

    positive_fields = (
        "seed",
        "users",
        "events",
        "sessionsPerEvent",
        "futureStartOffsetDays",
        "sessionSpacingHours",
        "gateLeadMinutes",
    )
    for field in positive_fields:
        value = profile[field]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field} must be a positive integer")

    layout = profile["seatLayout"]
    if not isinstance(layout, dict):
        raise ValueError("seatLayout must be an object")
    for field in ("rows", "seatsPerRow"):
        value = layout.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"seatLayout.{field} must be a positive integer")
    if layout["seatsPerRow"] > 999999:
        raise ValueError("seat numbers must fit the deterministic six-digit ID format")

    zones = profile["priceZones"]
    if not isinstance(zones, list) or not zones:
        raise ValueError("priceZones must be a non-empty array")
    zone_rows = 0
    zone_names: set[str] = set()
    for zone in zones:
        if not isinstance(zone, dict):
            raise ValueError("each price zone must be an object")
        name = zone.get("name")
        rows = zone.get("rows")
        price = zone.get("price")
        if not isinstance(name, str) or not IDENTIFIER_RE.fullmatch(name.lower()):
            raise ValueError("zone name must be a non-empty identifier")
        if name in zone_names:
            raise ValueError(f"duplicate zone name: {name}")
        zone_names.add(name)
        if isinstance(rows, bool) or not isinstance(rows, int) or rows <= 0:
            raise ValueError("zone rows must be a positive integer")
        if isinstance(price, bool) or not isinstance(price, int) or price < 0:
            raise ValueError("zone price must be a non-negative integer")
        zone_rows += rows
    if zone_rows != layout["rows"]:
        raise ValueError("price zone rows must exactly cover the seat layout")

    # The SQL always subtracts this positive lead from each generated start time.
    if profile["gateLeadMinutes"] <= 0:
        raise ValueError("gate_time must be earlier than start_time")

    sessions = profile["events"] * profile["sessionsPerEvent"]
    seats = layout["rows"] * layout["seatsPerRow"]
    return DatasetShape(
        users=profile["users"],
        events=profile["events"],
        sessions=sessions,
        seats=seats,
        session_seats=sessions * seats,
    )


def load_profile(name_or_path: str) -> tuple[dict[str, Any], Path]:
    candidate = Path(name_or_path)
    path = candidate if candidate.suffix == ".json" else PROFILE_ROOT / f"{name_or_path}.json"
    path = path.resolve()
    try:
        profile = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read profile {path}: {error}") from error
    validate_profile(profile)
    return profile, path


def load_auth_timeouts(path: Path = AUTH_CONFIG) -> tuple[int, int]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
        auth = config["custom_config"]["authentication"]
        idle = auth["idle_timeout_seconds"]
        absolute = auth["absolute_timeout_seconds"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise ValueError(f"cannot read authentication timeouts from {path}: {error}") from error
    for name, value in (("idle", idle), ("absolute", absolute)):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"authentication {name} timeout must be a positive integer")
    if idle > absolute:
        raise ValueError("authentication idle timeout cannot exceed absolute timeout")
    return idle, absolute


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


def run_psql(sql: str) -> str:
    completed = subprocess.run(
        compose_command(
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
        ),
        cwd=REPO_ROOT,
        input=sql,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise DatasetError(completed.stderr.strip() or completed.stdout.strip())
    return completed.stdout.strip()


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def zone_case(profile: dict[str, Any], result: str) -> str:
    clauses = []
    first_row = 1
    for zone in profile["priceZones"]:
        last_row = first_row + zone["rows"] - 1
        value = zone[result]
        literal = str(value) if isinstance(value, int) else sql_literal(value)
        clauses.append(f"WHEN row_index BETWEEN {first_row} AND {last_row} THEN {literal}")
        first_row = last_row + 1
    return "CASE " + " ".join(clauses) + " ELSE NULL END"


def generate_session_credentials(user_count: int) -> list[dict[str, str]]:
    sessions = []
    for index in range(1, user_count + 1):
        raw = secrets.token_hex(32)
        csrf = secrets.token_hex(32)
        sessions.append(
            {
                "userId": performance_id("user", index),
                "username": performance_id("user", index),
                "authSessionId": performance_id("auth", index),
                "sessionToken": raw,
                "csrfToken": csrf,
                "tokenHash": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            }
        )
    return sessions


def build_generation_sql(
    profile: dict[str, Any],
    shape: DatasetShape,
    credentials: list[dict[str, str]],
    idle_timeout: int,
    absolute_timeout: int,
) -> str:
    layout = profile["seatLayout"]
    zone_sql = zone_case(profile, "name")
    price_sql = zone_case(profile, "price")
    session_rows = profile["sessionsPerEvent"]
    copy_rows = "\n".join(
        f"{item['authSessionId']}\t{item['userId']}\t{item['tokenHash']}"
        for item in credentials
    )
    return f"""
\\set ON_ERROR_STOP on
BEGIN;
SET LOCAL TIME ZONE 'UTC';

DELETE FROM user_notifications WHERE user_id LIKE 'perf-user-%';
DELETE FROM refunds WHERE order_id LIKE 'perf-order-%';
DELETE FROM payment_attempts WHERE order_id LIKE 'perf-order-%';
DELETE FROM checkout_session_seats WHERE checkout_session_id LIKE 'perf-checkout-%';
DELETE FROM checkout_sessions WHERE id LIKE 'perf-checkout-%' OR user_id LIKE 'perf-user-%';
DELETE FROM orders WHERE id LIKE 'perf-order-%' OR user_id LIKE 'perf-user-%';
DELETE FROM reservation_session_seats WHERE reservation_id LIKE 'perf-reservation-%';
DELETE FROM session_seats WHERE id LIKE 'perf-ss-%';
DELETE FROM reservations WHERE id LIKE 'perf-reservation-%' OR user_id LIKE 'perf-user-%';
DELETE FROM user_sessions WHERE id LIKE 'perf-auth-%' OR user_id LIKE 'perf-user-%';
DELETE FROM seats WHERE id LIKE 'perf-seat-%';
DELETE FROM sessions WHERE id LIKE 'perf-session-%';
DELETE FROM events WHERE id LIKE 'perf-event-%';
DELETE FROM venues WHERE id LIKE 'perf-venue-%';
DELETE FROM app_users WHERE id LIKE 'perf-user-%';

INSERT INTO venues (id, name, city)
VALUES ('perf-venue-001', 'Phase 10A Performance Venue', 'Shanghai');

INSERT INTO events (id, primary_venue_id, name, description, status, category, cover_url, date_range)
SELECT 'perf-event-' || lpad(event_index::text, 3, '0'),
       'perf-venue-001',
       'Performance Event ' || event_index,
       'Generated Phase 10A dataset event',
       'ON_SALE',
       'PERFORMANCE_TEST',
       'https://example.invalid/performance/event-' || event_index || '.jpg',
       'Generated future schedule'
FROM generate_series(1, {profile['events']}) AS event_index;

INSERT INTO sessions (id, event_id, venue_id, hall_name, start_time, gate_time, status)
SELECT 'perf-session-' || lpad(event_index::text, 3, '0') || '-' || lpad(session_index::text, 3, '0'),
       'perf-event-' || lpad(event_index::text, 3, '0'),
       'perf-venue-001',
       'Performance Hall',
       clock_timestamp() + make_interval(days => {profile['futureStartOffsetDays']}, hours => ((event_index - 1) * {session_rows} + session_index - 1) * {profile['sessionSpacingHours']}),
       clock_timestamp() + make_interval(days => {profile['futureStartOffsetDays']}, hours => ((event_index - 1) * {session_rows} + session_index - 1) * {profile['sessionSpacingHours']}, mins => -{profile['gateLeadMinutes']}),
       'ON_SALE'
FROM generate_series(1, {profile['events']}) AS event_index
CROSS JOIN generate_series(1, {session_rows}) AS session_index;

INSERT INTO seats (id, venue_id, row_no, seat_no, seat_label, zone)
SELECT 'perf-seat-' || lpad(seat_index::text, 6, '0'),
       'perf-venue-001',
       'R' || lpad(row_index::text, 3, '0'),
       seat_number,
       'R' || lpad(row_index::text, 3, '0') || '-' || lpad(seat_number::text, 3, '0'),
       {zone_sql}
FROM generate_series(1, {shape.seats}) AS seat_index
CROSS JOIN LATERAL (
    SELECT ((seat_index - 1) / {layout['seatsPerRow']}) + 1 AS row_index,
           ((seat_index - 1) % {layout['seatsPerRow']}) + 1 AS seat_number
) AS position;

INSERT INTO session_seats (id, session_id, seat_id, venue_id, status, price, current_reservation_id)
SELECT 'perf-ss-' || lpad(event_index::text, 3, '0') || '-' || lpad(session_index::text, 3, '0') || '-' || lpad(seat_index::text, 6, '0'),
       'perf-session-' || lpad(event_index::text, 3, '0') || '-' || lpad(session_index::text, 3, '0'),
       'perf-seat-' || lpad(seat_index::text, 6, '0'),
       'perf-venue-001',
       'AVAILABLE',
       {price_sql},
       NULL
FROM generate_series(1, {profile['events']}) AS event_index
CROSS JOIN generate_series(1, {session_rows}) AS session_index
CROSS JOIN generate_series(1, {shape.seats}) AS seat_index
CROSS JOIN LATERAL (
    SELECT ((seat_index - 1) / {layout['seatsPerRow']}) + 1 AS row_index
) AS position;

INSERT INTO app_users (id, display_name, username, password_hash, status)
SELECT 'perf-user-' || lpad(user_index::text, 6, '0'),
       'Performance User ' || user_index,
       'perf-user-' || lpad(user_index::text, 6, '0'),
       {sql_literal(PASSWORD_HASH)},
       'ACTIVE'
FROM generate_series(1, {shape.users}) AS user_index;

CREATE TEMP TABLE perf_auth_input (
    id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL
) ON COMMIT DROP;
COPY perf_auth_input (id, user_id, token_hash) FROM STDIN;
{copy_rows}
\\.

INSERT INTO user_sessions (
    id, user_id, token_hash, created_at, last_seen_at,
    idle_expires_at, absolute_expires_at, revoked_at
)
SELECT id,
       user_id,
       token_hash,
       clock_timestamp(),
       clock_timestamp(),
       clock_timestamp() + make_interval(secs => {idle_timeout}),
       clock_timestamp() + make_interval(secs => {absolute_timeout}),
       NULL
FROM perf_auth_input
ORDER BY id;

DO $validation$
DECLARE
    actual BIGINT;
BEGIN
    SELECT count(*) INTO actual FROM app_users WHERE id LIKE 'perf-user-%';
    IF actual <> {shape.users} THEN RAISE EXCEPTION 'perf user count %, expected {shape.users}', actual; END IF;
    SELECT count(*) INTO actual FROM user_sessions WHERE id LIKE 'perf-auth-%';
    IF actual <> {shape.users} THEN RAISE EXCEPTION 'perf auth count %, expected {shape.users}', actual; END IF;
    SELECT count(*) INTO actual FROM events WHERE id LIKE 'perf-event-%';
    IF actual <> {shape.events} THEN RAISE EXCEPTION 'perf event count %, expected {shape.events}', actual; END IF;
    SELECT count(*) INTO actual FROM sessions WHERE id LIKE 'perf-session-%';
    IF actual <> {shape.sessions} THEN RAISE EXCEPTION 'perf session count %, expected {shape.sessions}', actual; END IF;
    SELECT count(*) INTO actual FROM seats WHERE id LIKE 'perf-seat-%';
    IF actual <> {shape.seats} THEN RAISE EXCEPTION 'perf seat count %, expected {shape.seats}', actual; END IF;
    SELECT count(*) INTO actual FROM session_seats WHERE id LIKE 'perf-ss-%';
    IF actual <> {shape.session_seats} THEN RAISE EXCEPTION 'perf session seat count %, expected {shape.session_seats}', actual; END IF;
END
$validation$;
COMMIT;
"""


def git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise DatasetError(completed.stderr.strip() or "cannot read Git HEAD")
    return completed.stdout.strip()


def build_dataset_manifest(
    profile: dict[str, Any], shape: DatasetShape, profile_hash: str
) -> dict[str, Any]:
    low_conflict_count = min(4, shape.sessions)
    low_conflict = []
    for ordinal in range(low_conflict_count):
        event_index = ordinal // profile["sessionsPerEvent"] + 1
        session_index = ordinal % profile["sessionsPerEvent"] + 1
        low_conflict.append(performance_id("session", event_index, session_index))
    return {
        "version": 1,
        "profile": profile["name"],
        "profileSha256": profile_hash,
        "gitHead": git_head(),
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "scope": {"prefix": PERF_PREFIX},
        "counts": {
            "users": shape.users,
            "events": shape.events,
            "sessions": shape.sessions,
            "physicalSeats": shape.seats,
            "sessionSeats": shape.session_seats,
        },
        "publicReadEventId": performance_id("event", 1),
        "seatMapSessionId": performance_id("session", 1, 1),
        "hotSessionId": performance_id("session", 1, 1),
        "hotSessionSeatId": performance_id("session-seat", 1, 1, 1),
        "lowConflictSessionIds": low_conflict,
    }


def validate_database(
    shape: DatasetShape,
    manifest: dict[str, Any],
    credentials: list[dict[str, str]],
) -> None:
    first = credentials[0]
    targets = manifest["lowConflictSessionIds"]
    target_sql = ", ".join(sql_literal(value) for value in targets)
    checks_sql = f"""
SELECT 'users', count(*) FROM app_users WHERE id LIKE 'perf-user-%'
UNION ALL SELECT 'user_sessions', count(*) FROM user_sessions WHERE id LIKE 'perf-auth-%'
UNION ALL SELECT 'events', count(*) FROM events WHERE id LIKE 'perf-event-%'
UNION ALL SELECT 'sessions', count(*) FROM sessions WHERE id LIKE 'perf-session-%'
UNION ALL SELECT 'seats', count(*) FROM seats WHERE id LIKE 'perf-seat-%'
UNION ALL SELECT 'session_seats', count(*) FROM session_seats WHERE id LIKE 'perf-ss-%'
UNION ALL SELECT 'available_session_seats', count(*) FROM session_seats WHERE id LIKE 'perf-ss-%' AND status = 'AVAILABLE'
UNION ALL SELECT 'seat_pointers', count(*) FROM session_seats WHERE id LIKE 'perf-ss-%' AND current_reservation_id IS NOT NULL
UNION ALL SELECT 'reservations', count(*) FROM reservations WHERE id LIKE 'perf-reservation-%' OR user_id LIKE 'perf-user-%'
UNION ALL SELECT 'checkouts', count(*) FROM checkout_sessions WHERE id LIKE 'perf-checkout-%' OR user_id LIKE 'perf-user-%'
UNION ALL SELECT 'orders', count(*) FROM orders WHERE id LIKE 'perf-order-%' OR user_id LIKE 'perf-user-%'
UNION ALL SELECT 'attempts', count(*) FROM payment_attempts WHERE order_id LIKE 'perf-order-%'
UNION ALL SELECT 'refunds', count(*) FROM refunds WHERE order_id LIKE 'perf-order-%'
UNION ALL SELECT 'notifications', count(*) FROM user_notifications WHERE user_id LIKE 'perf-user-%'
UNION ALL SELECT 'hot_target', count(*) FROM session_seats WHERE id = {sql_literal(manifest['hotSessionSeatId'])}
UNION ALL SELECT 'low_conflict_targets', count(*) FROM sessions WHERE id IN ({target_sql})
UNION ALL SELECT 'token_hash', count(*) FROM user_sessions WHERE id = {sql_literal(first['authSessionId'])} AND token_hash = {sql_literal(first['tokenHash'])};
"""
    parsed: dict[str, int] = {}
    for line in run_psql(checks_sql).splitlines():
        name, count = line.split("\t", 1)
        parsed[name] = int(count)
    expected = {
        "users": shape.users,
        "user_sessions": shape.users,
        "events": shape.events,
        "sessions": shape.sessions,
        "seats": shape.seats,
        "session_seats": shape.session_seats,
        "available_session_seats": shape.session_seats,
        "seat_pointers": 0,
        "reservations": 0,
        "checkouts": 0,
        "orders": 0,
        "attempts": 0,
        "refunds": 0,
        "notifications": 0,
        "hot_target": 1,
        "low_conflict_targets": len(targets),
        "token_hash": 1,
    }
    differences = {
        name: (parsed.get(name), value)
        for name, value in expected.items()
        if parsed.get(name) != value
    }
    if differences:
        raise DatasetError(f"dataset validation failed: {differences}")


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, newline="\n"
    ) as temporary:
        json.dump(payload, temporary, ensure_ascii=False, indent=2)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    temporary_path.replace(path)


def auth_me_smoke(
    backend_url: str, credential: dict[str, str], timeout: float = 10.0
) -> None:
    request = Request(
        f"{backend_url.rstrip('/')}/auth/me",
        headers={"Cookie": f"ticketing_session={credential['sessionToken']}"},
    )
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            status = response.status
            body = response.read().decode("utf-8")
    except HTTPError as error:
        raise DatasetError(
            f"offline session /auth/me returned HTTP {error.code}: "
            f"{error.read().decode('utf-8')[:300]}"
        ) from error
    except (OSError, URLError) as error:
        raise DatasetError(f"offline session /auth/me failed: {error}") from error
    payload = json.loads(body)
    actual_user_id = payload.get("id")
    if status != 200 or actual_user_id != credential["userId"]:
        raise DatasetError(
            f"offline session /auth/me mismatch: HTTP {status}, body={body[:300]}"
        )
    print(f"[PASS] offline session /auth/me: HTTP {status}, userId={actual_user_id}")


def public_sessions(credentials: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {
            "userId": item["userId"],
            "username": item["username"],
            "authSessionId": item["authSessionId"],
            "sessionToken": item["sessionToken"],
            "csrfToken": item["csrfToken"],
        }
        for item in credentials
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="smoke", help="profile name or JSON path")
    parser.add_argument("--backend-url", default="http://127.0.0.1:18080")
    parser.add_argument("--skip-auth-check", action="store_true")
    args = parser.parse_args()
    try:
        profile, path = load_profile(args.profile)
        shape = validate_profile(profile)
        idle_timeout, absolute_timeout = load_auth_timeouts()
        credentials = generate_session_credentials(shape.users)
        sql = build_generation_sql(
            profile, shape, credentials, idle_timeout, absolute_timeout
        )
        print(
            f"Generating profile={profile['name']} users={shape.users} "
            f"events={shape.events} sessions={shape.sessions} seats={shape.seats} "
            f"session_seats={shape.session_seats}"
        )
        run_psql(sql)
        manifest = build_dataset_manifest(profile, shape, profile_sha256(profile))
        validate_database(shape, manifest, credentials)
        sessions_payload = public_sessions(credentials)
        if len(sessions_payload) != shape.users:
            raise DatasetError("session manifest count mismatch")
        write_json_atomic(GENERATED_ROOT / "sessions.json", sessions_payload)
        write_json_atomic(GENERATED_ROOT / "dataset.json", manifest)
        if not args.skip_auth_check:
            auth_me_smoke(args.backend_url, credentials[0])
        print(
            f"[PASS] dataset {profile['name']} generated from {path}; "
            f"manifests={GENERATED_ROOT}"
        )
        return 0
    except (DatasetError, ValueError, json.JSONDecodeError) as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
