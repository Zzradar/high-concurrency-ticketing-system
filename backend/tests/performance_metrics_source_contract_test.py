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
        compact = " ".join(source.split())
        self.assertIn(
            "0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0",
            compact,
        )
        self.assertIn("code >= 100 && code < 600", source)
        self.assertIn('return std::to_string(code / 100) + "xx"', source)
        self.assertIn('return "unknown"', source)

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
        labels = {
            label
            for collector in collectors
            for label in collector["labels"]
        }
        self.assertTrue(
            labels.isdisjoint(
                {"userId", "orderId", "sessionId", "checkoutSessionId", "token"}
            )
        )
        self.assertTrue(config["custom_config"]["performance_metrics"]["enabled"])

        no_metrics = json.loads(
            (
                BACKEND_ROOT / "config" / "config.performance.no_metrics.json"
            ).read_text(encoding="utf-8")
        )
        self.assertFalse(
            no_metrics["custom_config"]["performance_metrics"]["enabled"]
        )

    def test_default_configs_do_not_enable_performance_metrics(self) -> None:
        for name in ("config.json", "config.docker.json"):
            config = json.loads(
                (BACKEND_ROOT / "config" / name).read_text(encoding="utf-8")
            )
            self.assertNotIn("performance_metrics", config["custom_config"])

    def test_registration_and_build_wiring_exist(self) -> None:
        main = (BACKEND_ROOT / "src" / "main.cpp").read_text(encoding="utf-8")
        cmake = (BACKEND_ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("PerformanceMetrics::registerWithApplication();", main)
        self.assertIn("src/observability/PerformanceMetrics.cpp", cmake)
        self.assertIn("performance_metrics_source_contract", cmake)


if __name__ == "__main__":
    unittest.main(verbosity=2)
