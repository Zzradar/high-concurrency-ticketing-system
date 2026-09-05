import json
from pathlib import Path
import sys
import unittest
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "performance" / "scripts"))

import performance_evidence as evidence  # noqa: E402
import run_baseline  # noqa: E402
import render_baseline_report  # noqa: E402


class EvidenceTests(unittest.TestCase):
    def test_redis_info_parser_is_forward_compatible(self):
        parsed = evidence.parse_redis_info(
            "# Clients\r\nconnected_clients:12\r\n"
            "cmdstat_get:calls=3,usec=12,usec_per_call=4.0,new_field=x\r\n"
            "future_without_colon\r\n"
        )
        self.assertEqual(parsed["connected_clients"], 12)
        self.assertEqual(parsed["cmdstat_get"]["calls"], 3)
        self.assertEqual(parsed["cmdstat_get"]["new_field"], "x")

    def test_named_prometheus_queries_are_range_queries(self):
        self.assertIn("backend-rate", evidence.PROMETHEUS_QUERIES)
        self.assertIn("postgres-connections", evidence.PROMETHEUS_QUERIES)
        self.assertIn("redis-clients", evidence.PROMETHEUS_QUERIES)
        self.assertIn("container-cpu", evidence.PROMETHEUS_QUERIES)

    def test_postgres_evidence_includes_activity_and_lock_snapshots(self):
        source = Path(evidence.__file__).read_text(encoding="utf-8")
        self.assertIn("FROM pg_stat_activity", source)
        self.assertIn("FROM pg_locks", source)
        self.assertIn('postgres-activity.json', source)
        self.assertIn('postgres-locks.json', source)

    def test_full_reset_requires_explicit_second_guard(self):
        with self.assertRaisesRegex(RuntimeError, "requires --allow-destructive-reset"):
            run_baseline.reset_environment("full", "baseline", False)
        with mock.patch.object(run_baseline, "execute") as execute:
            run_baseline.reset_environment("full", "smoke", True)
        command = execute.call_args.args[0]
        self.assertEqual(command[-3:], ["--profile", "smoke", "--yes"])

    def test_logical_reset_never_deletes_volumes(self):
        with mock.patch.object(run_baseline, "logical_reset") as reset:
            run_baseline.reset_environment("logical", "baseline", False)
        reset.assert_called_once_with("baseline")
        source = Path(run_baseline.__file__).read_text(encoding="utf-8")
        self.assertNotIn("down -v", source)
        self.assertNotIn("volume prune", source)

    def test_report_renderer_has_required_sections_and_rejects_credentials(self):
        data = {
            "metadata": {"Git commit": "abc"},
            "methodology": "Measured facts.",
            "stable": {"headers": ["workload"], "rows": [["public-read"]]},
            "discovery": {"headers": ["workload"], "rows": [["public-read"]]},
            "spikes": {"headers": ["workload"], "rows": [["public-read"]]},
            "multiRequestLatency": {
                "paymentStart": {
                    "aggregateHttpRequestLatencyMs": {"p50": [1.0, 1.0], "p95": [2.0, 2.0], "p99": [3.0, 3.0]},
                    "flowDurationMs": None,
                    "note": "Single request.",
                },
                "checkout": {
                    "aggregateHttpRequestLatencyMs": {"p50": [1.0, 1.0], "p95": [2.0, 2.0], "p99": [3.0, 3.0]},
                    "createHttpRequestLatencyMs": None,
                    "confirmHttpRequestLatencyMs": None,
                    "flowDurationMs": {"metric": "iteration_duration", "p50": [4.0, 4.0], "p95": [5.0, 5.0], "p99": [6.0, 6.0]},
                    "note": "Two requests.",
                },
                "paymentLifecycle": {
                    "aggregateHttpRequestLatencyMs": {"p50": [1.0, 1.0], "p95": [2.0, 2.0], "p99": [3.0, 3.0]},
                    "payStartHttpRequestLatencyMs": None,
                    "pollHttpRequestLatencyMs": None,
                    "flowDurationMs": {"metric": "iteration_duration", "p50": [4000.0, 4000.0], "p95": [6000.0, 6000.0], "p99": [6000.0, 6000.0]},
                    "pollRequestsPerPayment": [4.0, 4.0],
                    "note": "Async flow.",
                },
                "mixedLatencyScope": "Aggregate HTTP requests.",
            },
            "extendedSteady": "60-second extended steady observation.",
            "observations": "Observed evidence.",
            "correctness": "Verifier passed.",
            "candidates": "No optimization implemented.",
            "limitations": "Not production capacity.",
            "references": ["k6 official documentation"],
        }
        report = render_baseline_report.render(data)
        self.assertIn("# Phase 10A 本地性能 Baseline", report)
        self.assertIn("## Extended steady observation", report)
        self.assertIn("## 多请求流程延迟语义", report)
        self.assertIn("## Phase 10B 候选实验（未实施）", report)
        data["limitations"] = "leaked ticketing_session=value"
        with self.assertRaisesRegex(ValueError, "sensitive"):
            render_baseline_report.render(data)

    def test_checked_in_baseline_report_matches_sanitized_source(self):
        source = REPO_ROOT / "performance" / "baseline" / "phase10a-baseline-data.json"
        report = REPO_ROOT / "performance" / "baseline" / "phase10a-baseline.md"
        rendered = render_baseline_report.render(
            json.loads(source.read_text(encoding="utf-8"))
        )
        self.assertEqual(report.read_text(encoding="utf-8"), rendered)
        self.assertIn("first observed unstable", rendered)
        self.assertIn("Phase 10B 候选实验（未实施）", rendered)

    def test_baseline_latency_and_duration_semantics_are_explicit(self):
        source = REPO_ROOT / "performance" / "baseline" / "phase10a-baseline-data.json"
        data = json.loads(source.read_text(encoding="utf-8"))
        rendered = render_baseline_report.render(data)

        self.assertNotIn("Local endurance / short soak", rendered)
        self.assertNotIn("endurance passed", rendered.lower())
        self.assertNotIn("soak passed", rendered.lower())
        self.assertIn("## Extended steady observation", rendered)
        self.assertIn("Long-duration soak / endurance test：未执行", rendered)
        self.assertIn("聚合 HTTP 请求 p95 ms", data["stable"]["headers"])
        self.assertIn("聚合 HTTP 请求延迟", data["multiRequestLatency"]["mixedLatencyScope"])

        checkout = data["multiRequestLatency"]["checkout"]
        self.assertIn("aggregateHttpRequestLatencyMs", checkout)
        self.assertIn("flowDurationMs", checkout)
        self.assertIsNone(checkout["createHttpRequestLatencyMs"])
        self.assertIsNone(checkout["confirmHttpRequestLatencyMs"])
        self.assertEqual(checkout["flowDurationMs"]["metric"], "iteration_duration")

        payment = data["multiRequestLatency"]["paymentLifecycle"]
        self.assertIn("aggregateHttpRequestLatencyMs", payment)
        self.assertIn("flowDurationMs", payment)
        self.assertIsNone(payment["payStartHttpRequestLatencyMs"])
        self.assertIsNone(payment["pollHttpRequestLatencyMs"])
        self.assertEqual(payment["flowDurationMs"]["metric"], "iteration_duration")
        self.assertEqual(payment["aggregateHttpRequestLatencyMs"]["p95"], [4.948, 4.895])
        self.assertEqual(payment["flowDurationMs"]["p95"], [6016.721, 6019.418])

    def test_baseline_capacity_and_correctness_facts_are_preserved(self):
        source = REPO_ROOT / "performance" / "baseline" / "phase10a-baseline-data.json"
        data = json.loads(source.read_text(encoding="utf-8"))
        fixed_loads = {row[0]: row[1] for row in data["stable"]["rows"]}
        self.assertEqual(fixed_loads["public-read"], "300 iter/s")
        self.assertEqual(fixed_loads["auth-read warm"], "200 iter/s")
        self.assertEqual(fixed_loads["auth-read cold"], "100 iter/s, unique sessions")
        self.assertEqual(fixed_loads["seat-map-read density 90%"], "150 iter/s")
        self.assertEqual(fixed_loads["formal-seat-contention"], "20 groups/s × 4 contenders")
        self.assertEqual(fixed_loads["temporary-hold-contention"], "20 groups/s × 4 contenders")
        self.assertEqual(fixed_loads["checkout"], "20 buyers/s")
        self.assertEqual(fixed_loads["payment-start"], "10 starts/s")
        self.assertEqual(fixed_loads["payment-lifecycle"], "5 buyers/s")
        self.assertEqual(fixed_loads["login"], "15 logins/s")
        self.assertEqual(data["discovery"]["rows"][-1][3], "固定 30/s")
        self.assertIn("verify_database.py` 均返回 0 violations", data["correctness"])
        self.assertIn("共 64 项", data["correctness"])

    def test_extended_observation_plan_preserves_raw_soak_mode(self):
        path = REPO_ROOT / "performance" / "baseline" / "phase10a-plan.json"
        plan = json.loads(path.read_text(encoding="utf-8"))
        extended = next(run for run in plan["runs"] if run["name"] == "mixed-read-extended-steady")
        self.assertIn("extended steady observation", plan["description"])
        self.assertEqual(extended["args"][extended["args"].index("--mode") + 1], "soak")
        self.assertEqual(extended["args"][extended["args"].index("--duration") + 1], "60s")


if __name__ == "__main__": unittest.main()
