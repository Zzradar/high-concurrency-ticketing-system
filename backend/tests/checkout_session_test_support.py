import json
import os
from pathlib import Path
import subprocess
from urllib.error import HTTPError
from urllib.request import Request, urlopen


BASE_URL = os.environ.get("TICKETING_BASE_URL", "http://127.0.0.1:8080")
BACKEND_ROOT = Path(__file__).resolve().parents[1]
SESSION_ID = "ses-concert-1001"
TEST_USERS = ("U-PHASE5-A", "U-PHASE5-B", "U-PHASE5-C")
TEST_SEATS = [
    f"{SESSION_ID}-{label}"
    for label in ("A01", "A02", "A04", "A05", "A06", "A07")
]


def psql(sql: str) -> str:
    completed = subprocess.run(
        [
            "docker", "compose", "exec", "-T", "postgres", "psql",
            "-U", "ticketing", "-d", "ticketing", "-v", "ON_ERROR_STOP=1",
            "-At", "-F", "\t", "-c", sql,
        ],
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"psql failed ({completed.returncode}): {completed.stderr}\nSQL: {sql}"
        )
    return completed.stdout.strip()


def redis_cli(*arguments: str) -> str:
    completed = subprocess.run(
        ["docker", "compose", "exec", "-T", "redis", "redis-cli", "--raw", *arguments],
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"redis-cli failed ({completed.returncode}): {completed.stderr}"
        )
    return completed.stdout.strip()


def cleanup_seat_holds() -> None:
    keys = redis_cli("--scan", "--pattern", "ticketing:seat-hold:*").splitlines()
    if keys:
        redis_cli("DEL", *keys)


def cleanup_phase5_data(*, recreate_users: bool = False) -> None:
    cleanup_seat_holds()
    users = ", ".join(repr(user) for user in TEST_USERS)
    psql(
        f"""
        BEGIN;
        DROP TRIGGER IF EXISTS phase5_force_reservation_failure ON reservations;
        DROP FUNCTION IF EXISTS phase5_force_reservation_failure();
        DROP TRIGGER IF EXISTS phase7_force_checkout_failure ON checkout_sessions;
        DROP FUNCTION IF EXISTS phase7_force_checkout_failure();
        DELETE FROM checkout_sessions WHERE user_id IN ({users});
        UPDATE session_seats
        SET status = 'AVAILABLE', current_reservation_id = NULL
        WHERE current_reservation_id IN (
            SELECT id FROM reservations WHERE user_id IN ({users})
        );
        DELETE FROM orders WHERE user_id IN ({users});
        DELETE FROM reservation_session_seats
        WHERE reservation_id IN (
            SELECT id FROM reservations WHERE user_id IN ({users})
        );
        DELETE FROM reservations WHERE user_id IN ({users});
        DELETE FROM app_users WHERE id IN ({users});
        UPDATE sessions SET status = 'ON_SALE' WHERE id = '{SESSION_ID}';
        COMMIT;
        """
    )
    if recreate_users:
        values = ", ".join(
            f"('{user}', 'Phase 5 integration user')" for user in TEST_USERS
        )
        psql(
            "INSERT INTO app_users (id, display_name) VALUES "
            f"{values} ON CONFLICT (id) DO NOTHING;"
        )


def request_json(
    path: str,
    *,
    method: str = "GET",
    user_id: str | None = TEST_USERS[0],
    body=None,
    timeout: float = 30,
):
    headers = {"Content-Type": "application/json"}
    if user_id is not None:
        headers["X-User-Id"] = user_id
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = Request(BASE_URL + path, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)
    except Exception as error:
        raise AssertionError(
            f"Backend is required at {BASE_URL}; {method} {path} failed: {error}"
        ) from error


def create_checkout(user_id: str, seat_ids: list[str]):
    return request_json(
        "/checkout-sessions",
        method="POST",
        user_id=user_id,
        body={"sessionId": SESSION_ID, "seatIds": seat_ids},
    )


def confirm_checkout(checkout_id: str, user_id: str):
    return request_json(
        f"/checkout-sessions/{checkout_id}/confirm",
        method="POST",
        user_id=user_id,
    )


def create_formal_reservation(user_id: str, idempotency_key: str, seat_ids: list[str]):
    headers = {
        "Content-Type": "application/json",
        "X-User-Id": user_id,
        "Idempotency-Key": idempotency_key,
    }
    request = Request(
        BASE_URL + "/reservations",
        data=json.dumps({"sessionId": SESSION_ID, "seatIds": seat_ids}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)
