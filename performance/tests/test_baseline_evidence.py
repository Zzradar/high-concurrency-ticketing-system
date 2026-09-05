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
            "endurance": "Short local run.",
            "observations": "Observed evidence.",
            "correctness": "Verifier passed.",
            "candidates": "No optimization implemented.",
            "limitations": "Not production capacity.",
            "references": ["k6 official documentation"],
        }
        report = render_baseline_report.render(data)
        self.assertIn("# Phase 10A 本地性能 Baseline", report)
        self.assertIn("## Phase 10B 候选实验（未实施）", report)
        data["limitations"] = "leaked ticketing_session=value"
        with self.assertRaisesRegex(ValueError, "sensitive"):
            render_baseline_report.render(data)


if __name__ == "__main__": unittest.main()
