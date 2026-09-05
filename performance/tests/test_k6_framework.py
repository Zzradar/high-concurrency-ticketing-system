from pathlib import Path
import sys
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
PERFORMANCE_ROOT = REPO_ROOT / "performance"
K6_ROOT = PERFORMANCE_ROOT / "k6"
sys.path.insert(0, str(PERFORMANCE_ROOT / "scripts"))

import run_k6  # noqa: E402


def source(relative: str) -> str:
    return (PERFORMANCE_ROOT / relative).read_text(encoding="utf-8")


class K6ConfigurationTests(unittest.TestCase):
    def test_k6_image_profile_mounts_and_remote_write_receiver_are_fixed(self):
        compose = source("docker-compose.performance.yml")
        self.assertIn("image: grafana/k6:2.2.0", compose)
        self.assertIn('profiles: ["load"]', compose)
        self.assertIn("./k6:/scripts:ro", compose)
        self.assertIn("./generated:/data:ro", compose)
        self.assertIn("./results:/results", compose)
        self.assertIn("--web.enable-remote-write-receiver", compose)
        self.assertIn("http://prometheus:9090/api/v1/write", compose)
        self.assertIn("K6_SUMMARY_TREND_STATS: p(50),p(95),p(99),min,max", compose)

    def test_system_tags_are_bounded_and_no_remote_javascript_is_imported(self):
        config = source("k6/lib/config.js")
        for tag in ("status", "method", "name", "scenario", "expected_response", "error_code"):
            self.assertIn(f"'{tag}'", config)
        for tag in ("'url'", "'vu'", "'iter'", "'ip'", "'error'"):
            self.assertNotIn(tag, config)
        for path in K6_ROOT.rglob("*.js"):
            contents = path.read_text(encoding="utf-8")
            self.assertNotRegex(contents, r"from\s+['\"]https?://", path)

    def test_arrival_rate_requires_explicit_preallocated_vus_and_has_no_sleep(self):
        scenarios = source("k6/lib/scenarios.js")
        self.assertIn("constant-arrival-rate", scenarios)
        self.assertIn("ramping-arrival-rate", scenarios)
        self.assertIn("positiveInteger('PREALLOCATED_VUS')", scenarios)
        self.assertNotIn("maxVUs", scenarios)
        for path in K6_ROOT.rglob("*.js"):
            self.assertNotIn("sleep(", path.read_text(encoding="utf-8"), path)

    def test_thresholds_are_correctness_only_and_discovery_is_non_blocking(self):
        scenarios = source("k6/lib/scenarios.js")
        self.assertIn("ticketing_system_error_total: ['count==0']", scenarios)
        self.assertIn("ticketing_unexpected_total: ['count==0']", scenarios)
        self.assertIn("dropped_iterations: ['count==0']", scenarios)
        self.assertIn("if (mode === 'discovery')", scenarios)
        self.assertNotRegex(scenarios, r"http_req_duration\s*:")

    def test_results_are_ignored_and_summary_paths_are_run_scoped(self):
        rules = source("results/.gitignore").splitlines()
        self.assertIn("*", rules)
        self.assertIn("!.gitignore", rules)
        summary = source("k6/lib/summary.js")
        self.assertIn("k6-summary.json", summary)
        self.assertIn("business-summary.json", summary)
        for sensitive in ("sessionToken", "csrfToken", "idempotencyKey"):
            self.assertNotIn(sensitive, summary)


class RunnerTests(unittest.TestCase):
    def test_runner_uses_boundary_headroom_for_steady_one_shot_pools(self):
        parser = run_k6.build_parser()
        args = parser.parse_args(
            [
                "formal-seat-contention",
                "--mode", "steady",
                "--group-rate", "2",
                "--duration", "10s",
                "--preallocated-vus", "8",
                "--contenders", "4",
            ]
        )
        plan = run_k6.build_pool_plan(args)
        self.assertEqual(plan.planned_iterations_upper_bound, 20)
        self.assertEqual(plan.pool_headroom, 8)
        self.assertEqual(plan.pool_required, 28)
        with self.assertRaisesRegex(run_k6.RunError, "requires 28 unique Seats"):
            run_k6.validate_args(args, session_count=100, seat_count=20)
        self.assertEqual(
            run_k6.validate_args(args, session_count=100, seat_count=28), plan
        )
        with self.assertRaisesRegex(run_k6.RunError, "only 27 are available"):
            run_k6.validate_args(args, session_count=100, seat_count=27)

    def test_runner_uses_peak_rate_or_vus_for_boundary_headroom(self):
        parser = run_k6.build_parser()
        args = parser.parse_args(
            [
                "auth-read", "--mode", "steady", "--auth-mode", "cold",
                "--auth-pool-size", "50", "--rate", "10", "--duration", "5s",
                "--preallocated-vus", "4",
            ]
        )
        plan = run_k6.build_pool_plan(args)
        self.assertEqual(plan, run_k6.PoolPlan(50, 10, 60))
        with self.assertRaisesRegex(run_k6.RunError, "requires 60 unique offline Sessions"):
            run_k6.validate_args(args, session_count=50, seat_count=100)
        self.assertEqual(
            run_k6.validate_args(args, session_count=60, seat_count=100), plan
        )

    def test_runner_discovery_upper_bound_and_smoke_exact_pool(self):
        parser = run_k6.build_parser()
        discovery = parser.parse_args(
            [
                "formal-seat-contention", "--mode", "discovery",
                "--start-rate", "2", "--target-rate", "10",
                "--ramp-duration", "10s", "--hold-duration", "5s",
                "--preallocated-vus", "4",
            ]
        )
        self.assertEqual(
            run_k6.build_pool_plan(discovery), run_k6.PoolPlan(150, 10, 160)
        )
        smoke = parser.parse_args(
            ["formal-seat-contention", "--mode", "smoke", "--contenders", "4"]
        )
        self.assertEqual(run_k6.build_pool_plan(smoke), run_k6.PoolPlan(3, 0, 3))
        self.assertEqual(
            run_k6.validate_args(smoke, session_count=4, seat_count=3),
            run_k6.PoolPlan(3, 0, 3),
        )

    def test_runner_validates_contention_bounds(self):
        parser = run_k6.build_parser()
        args = parser.parse_args(
            [
                "formal-seat-contention", "--mode", "steady",
                "--group-rate", "2", "--duration", "10s",
                "--preallocated-vus", "8", "--contenders", "21",
            ]
        )
        args.contenders = 21
        with self.assertRaisesRegex(run_k6.RunError, "between 2 and 20"):
            run_k6.validate_args(args, session_count=100, seat_count=28)

    def test_runner_never_uses_prune_or_embeds_result_credentials(self):
        runner = source("scripts/run_k6.py")
        self.assertNotIn("docker volume prune", runner)
        self.assertNotIn("docker system prune", runner)
        self.assertIn('errors="replace"', runner)
        self.assertIn('manifest["redisRestoreExitCode"]', runner)
        self.assertIn('manifest["postRedisObservabilityExitCode"]', runner)
        self.assertIn('result_code = 1', runner)
        for key in (
            "runId", "startUtc", "gitHead", "datasetProfile", "workload",
            "mode", "plannedIterationsUpperBound", "poolRequired",
            "poolAvailable", "poolHeadroom", "k6Image", "k6Version",
            "k6ExitCode", "verdict",
        ):
            self.assertIn(f'"{key}"', runner)
        self.assertLess(
            runner.index("series = verify_remote_write"),
            runner.index('if code == 99:'),
        )


if __name__ == "__main__":
    unittest.main()
