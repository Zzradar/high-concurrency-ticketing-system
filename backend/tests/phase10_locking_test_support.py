"""Support for deterministic PostgreSQL lock-wait integration tests."""

from __future__ import annotations

from concurrent.futures import Future
import json
from pathlib import Path
import queue
import subprocess
import threading
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "performance" / "docker-compose.performance.yml"
PROJECT_NAME = "ticketing-phase10a"
BASE_URL = "http://127.0.0.1:18080"
ORIGIN = "http://localhost:5173"
GENERATED_SESSIONS = REPO_ROOT / "performance" / "generated" / "sessions.json"
BACKEND_APPLICATION_NAME = "ticketing_backend_phase10a"


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


def psql(sql: str) -> str:
    completed = subprocess.run(
        compose_command(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-X",
            "-U",
            "ticketing",
            "-d",
            "ticketing",
            "-v",
            "ON_ERROR_STOP=1",
            "-At",
            "-F",
            "\t",
            "-c",
            sql,
        ),
        cwd=REPO_ROOT,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"psql failed ({completed.returncode}): {completed.stderr}\nSQL: {sql}"
        )
    return completed.stdout.strip()


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class PersistentTransaction:
    """Own a psql process so a row lock remains held across HTTP calls."""

    _ALLOWED_TABLES = {"session_seats", "checkout_sessions", "reservations"}

    def __init__(self) -> None:
        self._stdout: queue.Queue[str | None] = queue.Queue()
        self._stderr: list[str] = []
        self._process = subprocess.Popen(
            compose_command(
                "exec",
                "-T",
                "postgres",
                "psql",
                "-X",
                "-qAt",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "ticketing",
                "-d",
                "ticketing",
            ),
            cwd=REPO_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        assert self._process.stdout is not None
        assert self._process.stderr is not None
        self._stdout_thread = threading.Thread(
            target=self._read_stdout, name="phase10-psql-stdout", daemon=True
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stderr, name="phase10-psql-stderr", daemon=True
        )
        self._stdout_thread.start()
        self._stderr_thread.start()
        self._send("BEGIN;\nSELECT '__PHASE10_PID__' || pg_backend_pid();\n")
        marker = self._wait_for_prefix("__PHASE10_PID__", timeout=10)
        self.pid = int(marker.removeprefix("__PHASE10_PID__"))
        self._released = False

    def _read_stdout(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            self._stdout.put(line.rstrip("\r\n"))
        self._stdout.put(None)

    def _read_stderr(self) -> None:
        assert self._process.stderr is not None
        for line in self._process.stderr:
            self._stderr.append(line.rstrip("\r\n"))

    def _send(self, commands: str) -> None:
        if self._process.poll() is not None:
            raise AssertionError(
                f"persistent psql exited {self._process.returncode}: "
                + "\n".join(self._stderr)
            )
        assert self._process.stdin is not None
        self._process.stdin.write(commands)
        self._process.stdin.flush()

    def _wait_for_prefix(self, prefix: str, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        seen: list[str] = []
        while time.monotonic() < deadline:
            try:
                line = self._stdout.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty:
                break
            if line is None:
                break
            seen.append(line)
            if line.startswith(prefix):
                return line
        raise AssertionError(
            f"persistent psql marker {prefix!r} not observed; "
            f"stdout={seen!r}, stderr={self._stderr!r}, "
            f"returncode={self._process.poll()}"
        )

    def lock_row(self, table: str, row_id: str) -> None:
        if table not in self._ALLOWED_TABLES:
            raise ValueError(f"table is not allowed for lock fixture: {table}")
        self._send(
            f"SELECT id FROM {table} WHERE id={sql_literal(row_id)} FOR UPDATE;\n"
            "SELECT '__PHASE10_LOCKED__';\n"
        )
        self._wait_for_prefix("__PHASE10_LOCKED__", timeout=10)

    def rollback(self) -> None:
        if self._released:
            return
        self._send("ROLLBACK;\nSELECT '__PHASE10_RELEASED__';\n")
        self._wait_for_prefix("__PHASE10_RELEASED__", timeout=10)
        self._send("\\q\n")
        self._process.wait(timeout=10)
        self._released = True
        assert self._process.stdin is not None
        assert self._process.stdout is not None
        assert self._process.stderr is not None
        self._process.stdin.close()
        self._process.stdout.close()
        self._process.stderr.close()
        self._stdout_thread.join(timeout=2)
        self._stderr_thread.join(timeout=2)

    def __enter__(self) -> "PersistentTransaction":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        try:
            self.rollback()
        finally:
            if self._process.poll() is None:
                self._process.kill()
                self._process.wait(timeout=5)


def load_credentials(count: int = 3) -> list[dict[str, str]]:
    payload = json.loads(GENERATED_SESSIONS.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or len(payload) < count:
        raise AssertionError(
            "fresh smoke sessions.json is required; run reset_environment.py first"
        )
    return payload[:count]


class PerformanceClient:
    def __init__(self, credential: dict[str, str]):
        self.user_id = credential["userId"]
        self._cookie = (
            f"ticketing_session={credential['sessionToken']}; "
            f"ticketing_csrf={credential['csrfToken']}"
        )
        self._csrf = credential["csrfToken"]
        self._opener = build_opener(ProxyHandler({}))

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30,
    ) -> tuple[int, Any]:
        request_headers = {"Cookie": self._cookie, **(headers or {})}
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")
        if method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            request_headers.setdefault("Origin", ORIGIN)
            request_headers.setdefault("X-CSRF-Token", self._csrf)
        request = Request(
            BASE_URL + path, data=data, headers=request_headers, method=method
        )
        try:
            with self._opener.open(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return response.status, json.loads(raw) if raw else None
        except HTTPError as error:
            raw = error.read().decode("utf-8")
            return error.code, json.loads(raw) if raw else None


def activity_snapshot() -> str:
    return psql(
        """
        SELECT pid,
               coalesce(state, ''),
               coalesce(wait_event_type, ''),
               coalesce(wait_event, ''),
               array_to_string(pg_blocking_pids(pid), ','),
               regexp_replace(coalesce(query, ''), E'[\\n\\r\\t]+', ' ', 'g')
        FROM pg_stat_activity
        WHERE application_name = 'ticketing_backend_phase10a'
        ORDER BY pid;
        """
    )


def wait_for_blocked_by(
    blocker_pid: int,
    *,
    timeout: float = 12,
    future: Future | None = None,
    exclude_pids: set[int] | None = None,
) -> dict[str, Any]:
    excluded = exclude_pids or set()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        rows = psql(
            f"""
            SELECT pid, wait_event_type, wait_event,
                   array_to_string(pg_blocking_pids(pid), ','),
                   regexp_replace(query, E'[\\n\\r\\t]+', ' ', 'g')
            FROM pg_stat_activity
            WHERE application_name = {sql_literal(BACKEND_APPLICATION_NAME)}
              AND wait_event_type = 'Lock'
              AND {blocker_pid} = ANY(pg_blocking_pids(pid))
            ORDER BY pid;
            """
        )
        for row in rows.splitlines():
            if not row:
                continue
            pid, wait_type, wait_event, blockers, query_text = row.split("\t", 4)
            if int(pid) in excluded:
                continue
            evidence = {
                "blockedPid": int(pid),
                "waitEventType": wait_type,
                "waitEvent": wait_event,
                "blockingPids": [int(value) for value in blockers.split(",") if value],
                "query": query_text,
            }
            print("LOCK_EVIDENCE " + json.dumps(evidence, sort_keys=True))
            return evidence
        time.sleep(0.1)
    future_state = "not supplied" if future is None else f"done={future.done()}"
    raise AssertionError(
        f"no backend lock wait blocked by pid={blocker_pid}; "
        f"HTTP future {future_state}; activity:\n{activity_snapshot()}"
    )


def cleanup_users(user_ids: list[str], session_ids: list[str], seat_ids: list[str]) -> None:
    users = ", ".join(sql_literal(value) for value in user_ids)
    sessions = ", ".join(sql_literal(value) for value in session_ids)
    seats = ", ".join(sql_literal(value) for value in seat_ids)
    psql(
        f"""
        BEGIN;
        DELETE FROM checkout_session_seats AS item
        USING checkout_sessions AS checkout
        WHERE item.checkout_session_id = checkout.id
          AND checkout.user_id IN ({users})
          AND checkout.session_id IN ({sessions});
        DELETE FROM checkout_sessions
        WHERE user_id IN ({users}) AND session_id IN ({sessions});
        UPDATE session_seats
        SET status = 'AVAILABLE', current_reservation_id = NULL
        WHERE id IN ({seats}) OR current_reservation_id IN (
            SELECT id FROM reservations
            WHERE user_id IN ({users}) AND session_id IN ({sessions})
        );
        DELETE FROM user_notifications AS notification
        USING orders AS ticket_order, reservations AS reservation
        WHERE notification.order_id = ticket_order.id
          AND ticket_order.reservation_id = reservation.id
          AND reservation.user_id IN ({users})
          AND reservation.session_id IN ({sessions});
        DELETE FROM refunds AS refund
        USING orders AS ticket_order, reservations AS reservation
        WHERE refund.order_id = ticket_order.id
          AND ticket_order.reservation_id = reservation.id
          AND reservation.user_id IN ({users})
          AND reservation.session_id IN ({sessions});
        DELETE FROM payment_attempts AS attempt
        USING orders AS ticket_order, reservations AS reservation
        WHERE attempt.order_id = ticket_order.id
          AND ticket_order.reservation_id = reservation.id
          AND reservation.user_id IN ({users})
          AND reservation.session_id IN ({sessions});
        DELETE FROM orders AS ticket_order
        USING reservations AS reservation
        WHERE ticket_order.reservation_id = reservation.id
          AND reservation.user_id IN ({users})
          AND reservation.session_id IN ({sessions});
        DELETE FROM reservation_session_seats AS item USING reservations AS reservation
        WHERE item.reservation_id = reservation.id
          AND reservation.user_id IN ({users})
          AND reservation.session_id IN ({sessions});
        DELETE FROM reservations
        WHERE user_id IN ({users}) AND session_id IN ({sessions});
        COMMIT;
        """
    )


def force_success_backend() -> None:
    environment = dict(__import__("os").environ)
    environment["TICKETING_PAYMENT_FORCE_OUTCOME"] = "SUCCESS"
    completed = subprocess.run(
        compose_command("up", "-d", "--force-recreate", "--wait", "backend"),
        cwd=REPO_ROOT,
        env=environment,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr or completed.stdout)
