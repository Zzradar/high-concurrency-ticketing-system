from pathlib import Path
import re
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (BACKEND_ROOT / "db/migrations/006_add_user_authentication.sql").read_text(encoding="utf-8")
SEED = (BACKEND_ROOT / "db/seeds/001_demo_seed.sql").read_text(encoding="utf-8")
COMPOSE = (BACKEND_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
DOCKERFILE = (BACKEND_ROOT / "Dockerfile").read_text(encoding="utf-8")
CMAKE = (BACKEND_ROOT / "CMakeLists.txt").read_text(encoding="utf-8")


class Phase9AuthSchemaContractTest(unittest.TestCase):
    def test_users_are_canonical_and_status_checked(self) -> None:
        for column in ("username", "password_hash", "status"):
            self.assertIn(f"ADD COLUMN {column} TEXT", MIGRATION)
        self.assertIn("username = lower(username)", MIGRATION)
        self.assertIn("char_length(username) BETWEEN 3 AND 64", MIGRATION)
        self.assertIn("UNIQUE (username)", MIGRATION)
        self.assertIn("status IN ('ACTIVE', 'DISABLED')", MIGRATION)

    def test_existing_users_are_backfilled_without_assuming_only_seed_users(self) -> None:
        self.assertIn("WHEN id = 'U-1001' THEN 'demo'", MIGRATION)
        self.assertIn("WHEN id = 'U-SEED-HOLDER' THEN 'seed-holder'", MIGRATION)
        self.assertIn("ELSE 'legacy-' || md5(id)", MIGRATION)
        self.assertIn("ELSE '!disabled'", MIGRATION)
        self.assertIn("ELSE 'DISABLED'", MIGRATION)

    def test_user_sessions_allow_many_per_user_and_hash_only_tokens(self) -> None:
        self.assertRegex(MIGRATION, r"CREATE TABLE user_sessions\s*\(")
        self.assertRegex(MIGRATION, r"token_hash\s+TEXT NOT NULL UNIQUE")
        self.assertIn("token_hash ~ '^[0-9a-f]{64}$'", MIGRATION)
        for clause in (
            "idle_expires_at > created_at",
            "absolute_expires_at > created_at",
            "idle_expires_at <= absolute_expires_at",
            "last_seen_at >= created_at",
            "revoked_at IS NULL OR revoked_at >= created_at",
        ):
            self.assertIn(clause, MIGRATION)
        self.assertNotIn("UNIQUE (user_id)", MIGRATION)
        self.assertIn("ON user_sessions(user_id, created_at DESC)", MIGRATION)

    def test_seed_uses_real_argon2id_demo_and_disabled_holder(self) -> None:
        self.assertIn("'demo'", SEED)
        self.assertRegex(SEED, re.escape("$argon2id$v=19$m=65536,t=2,p=1$"))
        self.assertIn("'seed-holder', '!disabled', 'DISABLED'", SEED)

    def test_notification_and_fresh_init_order(self) -> None:
        self.assertIn("'ORDER_CREATED'", MIGRATION)
        sequence = (
            "005_add_payment_lifecycle.sql",
            "006_add_user_authentication.sql",
            "007_demo_seed.sql",
            "008_verify_seed.sql",
            "009_verify_checkout_schema.sql",
            "010_verify_payment_schema.sql",
            "011_verify_auth_schema.sql",
        )
        positions = [COMPOSE.index(name) for name in sequence]
        self.assertEqual(positions, sorted(positions))

    def test_native_dependencies_are_explicit(self) -> None:
        self.assertIn("libargon2-dev", DOCKERFILE)
        self.assertIn("libargon2-1", DOCKERFILE)
        self.assertIn("find_path(ARGON2_INCLUDE_DIR", CMAKE)
        self.assertIn("find_library(ARGON2_LIBRARY", CMAKE)
        self.assertIn("OpenSSL::Crypto", CMAKE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
