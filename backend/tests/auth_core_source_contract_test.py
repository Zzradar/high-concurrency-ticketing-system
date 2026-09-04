from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
CRYPTO = (ROOT / "src/security/Crypto.cpp").read_text(encoding="utf-8")
HASHER = (ROOT / "src/security/PasswordHasher.cpp").read_text(encoding="utf-8")
EXECUTOR = (ROOT / "src/security/PasswordHashExecutor.cpp").read_text(encoding="utf-8")
SESSION_REPOSITORY = (ROOT / "src/repositories/UserSessionRepository.cpp").read_text(encoding="utf-8")
CACHE = (ROOT / "src/services/AuthSessionCache.cpp").read_text(encoding="utf-8")
SERVICE = (ROOT / "src/services/AuthSessionService.cpp").read_text(encoding="utf-8")


class AuthCoreSourceContractTest(unittest.TestCase):
    def test_session_timeout_parameters_keep_postgres_int8_type(self) -> None:
        self.assertIn("$4::bigint * INTERVAL '1 second'", SESSION_REPOSITORY)
        self.assertIn("$5::bigint * INTERVAL '1 second'", SESSION_REPOSITORY)
        self.assertIn("$2::bigint * INTERVAL '1 second'", SESSION_REPOSITORY)

    def test_token_uses_csprng_and_sha256(self) -> None:
        self.assertIn("RAND_bytes", CRYPTO)
        self.assertIn("EVP_sha256", CRYPTO)
        self.assertIn("CRYPTO_memcmp", CRYPTO)

    def test_password_verification_is_argon2id_and_bounded(self) -> None:
        self.assertIn("argon2id_verify", HASHER)
        self.assertIn("argon2id_hash_encoded", HASHER)
        self.assertIn("queue_.size() >= queueCapacity_", EXECUTOR)
        self.assertNotIn("detach()", EXECUTOR)
        self.assertNotIn("std::async", EXECUTOR)

    def test_database_stores_hash_and_uses_authoritative_clock(self) -> None:
        self.assertIn("token_hash", SESSION_REPOSITORY)
        self.assertNotIn("rawToken", SESSION_REPOSITORY)
        self.assertIn("clock_timestamp()", SESSION_REPOSITORY)
        self.assertIn("LEAST(", SESSION_REPOSITORY)
        self.assertIn("revoked_at IS NULL", SESSION_REPOSITORY)

    def test_cache_is_namespaced_and_database_fallback_exists(self) -> None:
        self.assertIn('getRedisClient("auth_sessions")', CACHE)
        self.assertIn('"ticketing:auth-session:"', CACHE)
        self.assertIn("loadFromDatabase(tokenHash", SERVICE)
        self.assertIn("validateCachedRecord(tokenHash", SERVICE)
        self.assertIn("repository_.isActive(", SERVICE)
        self.assertIn("auth.id = $1", SESSION_REPOSITORY)
        self.assertIn("auth.token_hash = $2", SESSION_REPOSITORY)
        self.assertIn("lastSeenWriteIntervalSeconds", SERVICE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
