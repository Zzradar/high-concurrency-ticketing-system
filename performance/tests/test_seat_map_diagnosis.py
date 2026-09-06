import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "performance/scripts"))
import diagnose_seat_map as diagnosis


class DiagnosisTests(unittest.TestCase):
    def test_client_parser_preserves_empty_names_unknown_fields_and_missing_fields(self):
        values = diagnosis.parse_clients("id=5 addr=1.2.3.4:500 name= cmd=eval omem=200 oll=2 future=yes\n")
        self.assertEqual(values[0]["name"], "")
        self.assertEqual(values[0]["future"], "yes")
        self.assertNotIn("qbuf", values[0])

    def test_histogram_uses_delta_not_process_lifetime_and_preserves_unknown_tail(self):
        name = diagnosis.STAGE_METRIC
        before = {f'{name}_bucket{{stage="json_build",le="{le}"}}': count
                  for le, count in (("0.01", 10), ("0.1", 20), ("+Inf", 20))}
        after = {f'{name}_bucket{{stage="json_build",le="{le}"}}': count
                 for le, count in (("0.01", 12), ("0.1", 28), ("+Inf", 30))}
        value = diagnosis.stage_summary(before, after)["json_build"]
        self.assertEqual(value["samples"], 10)
        self.assertAlmostEqual(value["p50Seconds"], .055)
        self.assertIsNone(value["p95Seconds"])
        with self.assertRaisesRegex(RuntimeError, "reset"):
            diagnosis.stage_summary(after, before)

    def test_empty_histogram_has_no_fabricated_percentile(self):
        self.assertIsNone(diagnosis.quantile([(1, 0), (float("inf"), 0)], .5))

    def test_profiles_change_only_name_and_seats_per_row(self):
        original = json.loads((ROOT / "performance/data/profiles/scale-100k.json").read_text())
        for seats in (1000, 2500, 5000):
            with mock.patch.object(diagnosis.evidence, "write_json") as write, \
                 mock.patch.object(diagnosis.run_k6, "run_command") as run, \
                 mock.patch.object(diagnosis.run_k6, "clear_auth_cache"), \
                 mock.patch.object(diagnosis.run_k6, "clear_seat_holds"):
                run.return_value.stdout = ""
                diagnosis.prepare_profile(seats, Path("unused"))
                profile = write.call_args.args[1]
                self.assertEqual(profile["seatLayout"]["rows"] * profile["seatLayout"]["seatsPerRow"], seats)
                profile["name"] = original["name"]
                profile["seatLayout"]["seatsPerRow"] = original["seatLayout"]["seatsPerRow"]
                self.assertEqual(profile, original)

    def test_diagnostics_do_not_change_pools_or_business_semantics(self):
        metrics = (ROOT / "backend/src/observability/PerformanceMetrics.cpp").read_text()
        self.assertIn("std::atomic<MetricsState *>", metrics)
        self.assertIn('"db_fetch_and_materialize"', metrics)
        self.assertIn('"response_callback"', metrics)
        controller = (ROOT / "backend/src/controllers/SeatController.cpp").read_text()
        self.assertIn("responseStarted != Metrics::TimePoint{}", controller)
        self.assertIn("response->getBody().size()", controller)
        self.assertIn("newHttpJsonResponse(body)", controller)
        service = (ROOT / "backend/src/services/SeatService.cpp").read_text()
        self.assertIn('*holds.owners[index] != checkoutSessionId', service)
        self.assertIn('seats[index].status == "AVAILABLE"', service)
        config = json.loads((ROOT / "backend/config/config.performance.json").read_text())
        self.assertEqual(config["db_clients"][0]["number_of_connections"], 4)
        self.assertEqual([item["number_of_connections"] for item in config["redis_clients"]], [2, 2])


if __name__ == "__main__":
    unittest.main()
