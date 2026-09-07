import json
from pathlib import Path
import unittest


PERFORMANCE_ROOT = Path(__file__).resolve().parents[1]


class Phase11ObservabilityContractTest(unittest.TestCase):
    def test_stack_has_migration_and_dashboard_queries(self) -> None:
        compose = (PERFORMANCE_ROOT / "docker-compose.performance.yml").read_text(
            encoding="utf-8"
        )
        dashboard_path = (PERFORMANCE_ROOT / "observability" / "grafana" /
                          "dashboards" / "phase10a-overview.json")
        dashboard_text = dashboard_path.read_text(encoding="utf-8")
        json.loads(dashboard_text)

        self.assertIn("007_add_payment_provider_recovery.sql", compose)
        for metric in (
            "ticketing_payment_provider_requests_total",
            "ticketing_payment_webhooks_total",
            "ticketing_payment_reconciliation_total",
            "ticketing_payment_reconciliation_pending",
            "ticketing_refunds_by_status",
        ):
            self.assertIn(metric, dashboard_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
