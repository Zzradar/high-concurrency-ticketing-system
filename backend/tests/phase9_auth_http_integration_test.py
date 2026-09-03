import subprocess
import time
import unittest
from pathlib import Path

from auth_test_support import (
    ALLOWED_ORIGIN,
    AuthenticatedClient,
    TEST_PASSWORD,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]


def compose(*arguments: str) -> str:
    completed = subprocess.run(
        ["docker", "compose", *arguments], cwd=BACKEND_ROOT,
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    if completed.returncode:
        raise AssertionError(completed.stderr)
    return completed.stdout.strip()


def psql(sql: str) -> str:
    return compose(
        "exec", "-T", "postgres", "psql", "-U", "ticketing", "-d", "ticketing",
        "-v", "ON_ERROR_STOP=1", "-At", "-F", "\t", "-c", sql,
    )


def redis(*arguments: str) -> str:
    return compose("exec", "-T", "redis", "redis-cli", "--raw", *arguments)


def start_redis() -> None:
    compose("start", "redis")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            if redis("PING") == "PONG":
                time.sleep(0.5)
                return
        except AssertionError:
            pass
        time.sleep(0.2)
    raise AssertionError("Redis did not become healthy")


def clear_auth_state() -> None:
    start_redis()
    rate_keys = redis("--scan", "--pattern", "ticketing:login-fail:*").splitlines()
    if rate_keys:
        redis("DEL", *rate_keys)
    keys = redis("--scan", "--pattern", "ticketing:auth-session:*").splitlines()
    if keys:
        redis("DEL", *keys)
    psql("DELETE FROM user_sessions WHERE user_id = 'U-1001';")


class Phase9AuthHttpIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        clear_auth_state()

    def tearDown(self) -> None:
        start_redis()
        clear_auth_state()

    def test_login_cookie_me_and_invalid_credentials(self) -> None:
        client = AuthenticatedClient()
        status, user, headers = client._send(
            "/auth/login", method="POST",
            body={"username": " Demo ", "password": TEST_PASSWORD},
            headers={"Origin": ALLOWED_ORIGIN},
        )
        self.assertEqual((status, user["id"]), (200, "U-1001"))
        session_cookie = next(c for c in client.cookies if c.name == "ticketing_session")
        csrf_cookie = next(c for c in client.cookies if c.name == "ticketing_csrf")
        self.assertIn("HttpOnly", session_cookie._rest)
        self.assertNotIn("HttpOnly", csrf_cookie._rest)
        self.assertEqual(session_cookie._rest.get("SameSite"), "Lax")
        self.assertNotEqual(session_cookie.value, csrf_cookie.value)
        self.assertGreaterEqual(len(headers.get_all("Set-Cookie")), 2)
        client._logged_in = True
        self.assertEqual(client.request("/auth/me")[:2], (200, user))

        for username, password in (
            ("demo", "wrong-password"),
            ("missing-user", TEST_PASSWORD),
            ("seed-holder", TEST_PASSWORD),
        ):
            other = AuthenticatedClient()
            response = other._send(
                "/auth/login", method="POST",
                body={"username": username, "password": password},
                headers={"Origin": ALLOWED_ORIGIN},
            )
            self.assertEqual(response[0], 401, response[1])
            self.assertEqual(response[1]["code"], "INVALID_CREDENTIALS")

        bad_origin = AuthenticatedClient()._send(
            "/auth/login", method="POST",
            body={"username": "demo", "password": TEST_PASSWORD},
            headers={"Origin": "https://evil.example"},
        )
        self.assertEqual((bad_origin[0], bad_origin[1]["code"]), (403, "CSRF_INVALID"))

    def test_rate_limit_rejects_after_bounded_failures(self) -> None:
        for attempt in range(6):
            status, payload, _ = AuthenticatedClient()._send(
                "/auth/login", method="POST",
                body={"username": "demo", "password": "wrong-password"},
                headers={"Origin": ALLOWED_ORIGIN},
            )
            expected = 401 if attempt < 5 else 429
            self.assertEqual(status, expected, payload)

    def test_two_cookie_jars_are_independent_and_logout_revokes_one(self) -> None:
        first = AuthenticatedClient()
        second = AuthenticatedClient()
        first.login()
        second.login()
        first_token = first.cookie("ticketing_session")
        second_token = second.cookie("ticketing_session")
        self.assertNotEqual(first_token, second_token)
        self.assertEqual(first.request("/auth/me")[0], 200)
        self.assertEqual(second.request("/auth/me")[0], 200)
        self.assertEqual(first.request("/auth/logout", method="POST")[0], 200)
        self.assertEqual(first._send("/auth/me")[0], 401)
        self.assertEqual(second.request("/auth/me")[0], 200)
        self.assertEqual(
            psql("SELECT COUNT(*) FROM user_sessions WHERE user_id='U-1001';"), "2"
        )
        self.assertEqual(
            psql("SELECT COUNT(*) FROM user_sessions WHERE user_id='U-1001' AND revoked_at IS NOT NULL;"),
            "1",
        )

    def test_csrf_and_x_user_id_spoofing(self) -> None:
        client = AuthenticatedClient()
        client.login()
        body = {"sessionId": "ses-concert-1001", "seatIds": []}
        missing = client._send("/checkout-sessions", method="POST", body=body)
        self.assertEqual((missing[0], missing[1]["code"]), (403, "CSRF_INVALID"))
        no_header = client._send(
            "/checkout-sessions", method="POST", body=body,
            headers={"Origin": ALLOWED_ORIGIN},
        )
        self.assertEqual(no_header[0], 403)
        mismatch = client._send(
            "/checkout-sessions", method="POST", body=body,
            headers={"Origin": ALLOWED_ORIGIN, "X-CSRF-Token": "wrong"},
        )
        self.assertEqual(mismatch[0], 403)
        correct = client.request("/checkout-sessions", method="POST", body=body)
        self.assertEqual((correct[0], correct[1]["code"]), (400, "INVALID_ARGUMENT"))

        spoof = client.request(
            "/orders/TKT-SEED-SOLD-ses-concert-1001",
            headers={"X-User-Id": "U-SEED-HOLDER"},
        )
        self.assertEqual((spoof[0], spoof[1]["code"]), (404, "ORDER_NOT_FOUND"))

    def test_cache_miss_and_redis_outage_fall_back_to_postgres(self) -> None:
        client = AuthenticatedClient()
        client.login()
        token_hash = psql(
            "SELECT token_hash FROM user_sessions WHERE user_id='U-1001' ORDER BY created_at DESC LIMIT 1;"
        )
        redis("DEL", "ticketing:auth-session:" + token_hash)
        self.assertEqual(client.request("/auth/me")[0], 200)

        compose("stop", "redis")
        try:
            self.assertEqual(client.request("/auth/me")[0], 200)
            fallback_login = AuthenticatedClient()
            fallback_login.login()
            self.assertEqual(fallback_login.request("/auth/me")[0], 200)
        finally:
            start_redis()

    def test_expired_database_session_is_not_restored_from_a_cache_miss(self) -> None:
        client = AuthenticatedClient()
        client.login()
        token_hash = psql(
            "SELECT token_hash FROM user_sessions WHERE user_id='U-1001' ORDER BY created_at DESC LIMIT 1;"
        )
        psql(
            "UPDATE user_sessions SET "
            "created_at=clock_timestamp()-INTERVAL '2 days', "
            "last_seen_at=clock_timestamp()-INTERVAL '1 day', "
            "idle_expires_at=clock_timestamp()-INTERVAL '1 second' "
            f"WHERE token_hash='{token_hash}';"
        )
        redis("DEL", "ticketing:auth-session:" + token_hash)
        self.assertEqual(client.request("/auth/me")[0], 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
