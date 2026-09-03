from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
AUTH_SERVICE = (ROOT / "src/services/AuthService.cpp").read_text(encoding="utf-8")
RATE_LIMIT = (ROOT / "src/services/LoginRateLimiter.cpp").read_text(encoding="utf-8")
FILTER = (ROOT / "src/filters/AuthFilter.cpp").read_text(encoding="utf-8")
CONTROLLER = (ROOT / "src/controllers/AuthController.h").read_text(encoding="utf-8")
COOKIE = (ROOT / "src/security/AuthHttp.cpp").read_text(encoding="utf-8")


class AuthHttpSourceContractTest(unittest.TestCase):
    def test_login_has_dummy_argon2_and_bounded_executor(self) -> None:
        self.assertIn("kDummyHash", AUTH_SERVICE)
        self.assertIn("passwordExecutor().verify", AUTH_SERVICE)
        self.assertIn("LoginOutcome::Busy", AUTH_SERVICE)
        self.assertNotIn("sleep", AUTH_SERVICE)

    def test_rate_limit_is_atomic_ttl_and_fail_open(self) -> None:
        self.assertIn("redis.call('INCR'", RATE_LIMIT)
        self.assertIn("if value == 1 then redis.call('EXPIRE'", RATE_LIMIT)
        self.assertIn("ticketing:login-fail:username:", RATE_LIMIT)
        self.assertIn("ticketing:login-fail:ip:", RATE_LIMIT)
        self.assertGreaterEqual(RATE_LIMIT.count("failed open"), 2)

    def test_filter_uses_cookie_context_and_csrf(self) -> None:
        self.assertIn("getCookie", FILTER)
        self.assertIn("request->attributes()->insert", FILTER)
        self.assertIn("validCsrf(request)", FILTER)
        self.assertNotIn("X-User-Id", FILTER)
        self.assertIn('"ticketing::AuthFilter"', CONTROLLER)

    def test_cookie_security_shape(self) -> None:
        self.assertIn("setHttpOnly(httpOnly)", COOKIE)
        self.assertIn("SameSite::kLax", COOKIE)
        self.assertIn('setPath("/")', COOKIE)
        self.assertIn("setSecure(config.cookieSecure)", COOKIE)
        self.assertIn("constantTimeEqual(cookie, header)", COOKIE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
