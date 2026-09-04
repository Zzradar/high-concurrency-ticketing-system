import json
from pathlib import Path
import unittest


BACKEND_ROOT = Path(__file__).resolve().parents[1]


class PerformanceMetricsSourceContractTest(unittest.TestCase):
    def test_metrics_use_bounded_labels_and_cumulative_histogram(self) -> None:
        source = (
            BACKEND_ROOT / "src" / "observability" / "PerformanceMetrics.cpp"
        ).read_text(encoding="utf-8")

        self.assertIn("std::chrono::steady_clock::now()", source)
        self.assertIn("request->getMatchedPathPattern()", source)
        self.assertIn('kUnmatchedRoute[] = "__unmatched__"', source)
        self.assertNotIn("getOriginalPath", source)
        self.assertIn('path == "/health" || path == "/metrics"', source)
        self.assertIn("completed->exchange(true)", source)
        self.assertIn("std::chrono::duration<double>{0}", source)
        self.assertIn("kDurationBuckets", source)

    def test_performance_config_declares_exact_metric_contract(self) -> None:
        config = json.loads(
            (BACKEND_ROOT / "config" / "config.performance.json").read_text(
                encoding="utf-8"
            )
        )
        collectors = config["plugins"][0]["config"]["collectors"]
        by_name = {collector["name"]: collector for collector in collectors}

        self.assertEqual(
            set(by_name),
            {
                "ticketing_http_requests_total",
                "ticketing_http_request_duration_seconds",
                "ticketing_http_requests_in_flight",
            },
        )
        self.assertEqual(
            by_name["ticketing_http_requests_total"]["labels"],
            ["method", "route", "status_class"],
        )
        self.assertEqual(
            by_name["ticketing_http_request_duration_seconds"]["labels"],
            ["method", "route", "status_class"],
        )
        self.assertEqual(
            by_name["ticketing_http_requests_in_flight"]["labels"], []
        )
        self.assertTrue(config["custom_config"]["performance_metrics"]["enabled"])

    def test_default_configs_do_not_enable_performance_metrics(self) -> None:
        for name in ("config.json", "config.docker.json"):
            config = json.loads(
                (BACKEND_ROOT / "config" / name).read_text(encoding="utf-8")
            )
            self.assertNotIn("performance_metrics", config["custom_config"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
