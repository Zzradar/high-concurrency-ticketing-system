import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "performance" / "data"))

import generate_dataset  # noqa: E402
sys.path.insert(0, str(REPO_ROOT / "performance" / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "performance" / "verification"))
import reset_environment  # noqa: E402
import verify_database  # noqa: E402


class ProfileTests(unittest.TestCase):
    def test_checked_in_profiles_are_valid_and_have_expected_shapes(self):
        smoke, _ = generate_dataset.load_profile("smoke")
        baseline, _ = generate_dataset.load_profile("baseline")

        self.assertEqual(
            generate_dataset.validate_profile(smoke),
            generate_dataset.DatasetShape(8, 1, 4, 18, 72),
        )
        self.assertEqual(
            generate_dataset.validate_profile(baseline),
            generate_dataset.DatasetShape(10000, 2, 20, 1000, 20000),
        )

    def test_profile_validation_fails_before_database_work(self):
        profile, _ = generate_dataset.load_profile("smoke")
        broken = json.loads(json.dumps(profile))
        broken["priceZones"][0]["rows"] = 99
        with self.assertRaisesRegex(ValueError, "exactly cover"):
            generate_dataset.validate_profile(broken)

    def test_ids_and_profile_hash_are_deterministic(self):
        profile, _ = generate_dataset.load_profile("smoke")
        self.assertEqual(
            generate_dataset.performance_id("session-seat", 1, 2, 3),
            "perf-ss-001-002-000003",
        )
        expected = hashlib.sha256(generate_dataset.canonical_json(profile)).hexdigest()
        self.assertEqual(generate_dataset.profile_sha256(profile), expected)
        self.assertEqual(
            generate_dataset.profile_sha256(profile),
            generate_dataset.profile_sha256(json.loads(json.dumps(profile))),
        )

    def test_session_manifest_has_required_fields_and_token_shapes(self):
        credentials = generate_dataset.generate_session_credentials(2)
        manifest = generate_dataset.public_sessions(credentials)
        self.assertEqual(
            set(manifest[0]),
            {"userId", "username", "authSessionId", "sessionToken", "csrfToken"},
        )
        self.assertEqual(len(manifest), 2)
        self.assertRegex(manifest[0]["sessionToken"], r"^[0-9a-f]{64}$")
        self.assertRegex(manifest[0]["csrfToken"], r"^[0-9a-f]{64}$")
        self.assertNotEqual(manifest[0]["sessionToken"], manifest[0]["csrfToken"])
        self.assertEqual(
            credentials[0]["tokenHash"],
            hashlib.sha256(manifest[0]["sessionToken"].encode("utf-8")).hexdigest(),
        )

    def test_generated_credentials_are_gitignored(self):
        rules = (generate_dataset.GENERATED_ROOT / ".gitignore").read_text(
            encoding="utf-8"
        )
        self.assertIn("*", rules.splitlines())
        self.assertIn("!.gitignore", rules.splitlines())

    def test_auth_timeouts_are_read_from_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "custom_config": {
                            "authentication": {
                                "idle_timeout_seconds": 123,
                                "absolute_timeout_seconds": 456,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(generate_dataset.load_auth_timeouts(path), (123, 456))

    def test_auth_smoke_does_not_print_raw_token(self):
        credential = {
            "userId": "perf-user-000001",
            "sessionToken": "a" * 64,
        }
        response = mock.MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.read.return_value = json.dumps(
            {"id": credential["userId"]}
        ).encode("utf-8")
        with mock.patch.object(generate_dataset, "build_opener") as opener:
            opener.return_value.open.return_value = response
            generate_dataset.auth_me_smoke("http://example.test", credential)
            request = opener.return_value.open.call_args.args[0]
            self.assertIn("ticketing_session", request.headers["Cookie"])


class ResetAndVerifierTests(unittest.TestCase):
    def test_reset_guard_accepts_only_named_performance_volumes(self):
        reset_environment.validate_volume_names(
            "ticketing-phase10a",
            [
                "ticketing_phase10a_postgres_data",
                "ticketing_phase10a_prometheus_data",
            ],
        )
        with self.assertRaisesRegex(reset_environment.ResetGuardError, "non-Performance"):
            reset_environment.validate_volume_names(
                "ticketing-phase10a", ["backend_ticketing_postgres_data"]
            )
        with self.assertRaisesRegex(reset_environment.ResetGuardError, "expected"):
            reset_environment.validate_volume_names(
                "ticketing", ["ticketing_phase10a_postgres_data"]
            )

    def test_reset_without_yes_is_a_non_destructive_plan(self):
        model = {
            "name": "ticketing-phase10a",
            "volumes": {
                "database": {"name": "ticketing_phase10a_postgres_data"}
            },
        }
        with mock.patch.object(reset_environment.Path, "cwd", return_value=REPO_ROOT), mock.patch.object(
            reset_environment, "read_compose_model", return_value=model
        ), mock.patch.object(reset_environment, "run_command") as run, mock.patch.object(
            reset_environment, "clear_generated"
        ) as clear:
            reset_environment.reset("smoke", confirmed=False)
        run.assert_not_called()
        clear.assert_not_called()

    def test_verifier_parsing_and_violation_result(self):
        clean = "\n".join(f"{name}\t0" for name in sorted(verify_database.EXPECTED_CHECKS))
        parsed = verify_database.parse_verifier_output(clean)
        self.assertTrue(all(count == 0 for count in parsed.values()))
        broken = clean.replace("active_reservation_seat_mismatch\t0", "active_reservation_seat_mismatch\t1")
        parsed = verify_database.parse_verifier_output(broken)
        self.assertEqual(parsed["active_reservation_seat_mismatch"], 1)

    def test_verifier_rejects_missing_checks(self):
        with self.assertRaisesRegex(ValueError, "check set mismatch"):
            verify_database.parse_verifier_output("effective_seat_overlap\t0")


if __name__ == "__main__":
    unittest.main()
