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

    def test_resource_queries_scope_k6_to_this_run_and_reject_invalid_token(self):
        with mock.patch.object(diagnosis.run_k6, "read_json", return_value={"shortRunToken": "1234abcd"}), \
             mock.patch.object(diagnosis.evidence, "query_range") as query, \
             mock.patch.object(diagnosis.evidence, "write_json"):
            diagnosis.collect_run_resources(Path("unused"), Path("run"), 1, 2)
            self.assertEqual(query.call_count, 9)
            k6_queries = [call.args[0] for call in query.call_args_list if "k6-" in call.args[0]]
            self.assertEqual(len(k6_queries), 3)
            self.assertTrue(all('name="ticketing-phase10a-k6-1234abcd"' in value for value in k6_queries))
        with mock.patch.object(diagnosis.run_k6, "read_json", return_value={"shortRunToken": "invalid"}):
            with self.assertRaises(ValueError):
                diagnosis.collect_run_resources(Path("unused"), Path("run"), 1, 2)

    def test_encoding_probe_compares_default_and_explicit_gzip_without_changing_workload(self):
        probe = (ROOT / "performance/k6/diagnostics/seat-map-encoding.js").read_text()
        self.assertIn("['default', 'gzip']", probe)
        self.assertIn("'Accept-Encoding': 'gzip'", probe)
        self.assertIn("response.headers['Content-Encoding']", probe)
        self.assertIn("response.headers['Content-Length']", probe)
        self.assertIn("response.headers['Transfer-Encoding']", probe)
        workload = (ROOT / "performance/k6/workloads/seat-map-read.js").read_text()
        self.assertNotIn("Accept-Encoding", workload)

    def test_checked_in_measurements_cover_matrix_and_recovery_without_fabricated_success(self):
        directory = ROOT / "performance/experiments/phase10b-seat-map"
        data = json.loads((directory / "measurements.json").read_text(encoding="utf-8"))
        runs = data["runs"]
        self.assertEqual(len(runs), 10)
        matrix = [r for r in runs if r["arguments"]["duration"] == 15]
        self.assertEqual({(r["arguments"]["seats"], r["arguments"]["rate"]) for r in matrix},
                         {(seats, rate) for seats in (1000, 2500, 5000) for rate in (10, 30, 60)})
        for run in runs:
            self.assertEqual((run["runnerExit"], run["verifierExit"], run["samplingErrors"]), (0, 0, 0))
            self.assertEqual(run["gzip"]["seatCount"], run["arguments"]["seats"])
            self.assertTrue(run["gzip"]["bodyEquality"])
            self.assertEqual(len(run["stages"]), 12)
            # The exporter caches /metrics for 5s. Preserve the measured
            # snapshot/SQL window mismatch; do not invent exact sample alignment.
            expected_gap = 2 if run["runId"].endswith("-2374") else 0
            self.assertEqual(run["postgres"]["calls"] - run["stages"]["db_fetch_and_materialize"]["samples"], expected_gap)
            self.assertEqual(run["resources"]["k6"]["workingSetBytes"]["seriesCount"], 1)
        drain = next(r for r in runs if r["arguments"]["drain_seconds"])
        self.assertGreater(drain["rssBytes"]["after"], drain["rssBytes"]["before"])
        self.assertLess(drain["rssBytes"]["after"], drain["rssBytes"]["peak"])
        self.assertEqual(drain["timeline"][-1]["inFlight"], 0)
        self.assertEqual(drain["timeline"][-1]["sumClientOmem"], 0)
        self.assertGreaterEqual(drain["timeline"][-1]["epoch"] - drain["runnerFinishedEpoch"], 180)
        self.assertLess(drain["stages"]["owner_parse"]["samples"], drain["stages"]["redis_lookup"]["samples"])
        report = (directory / "diagnosis.md").read_text(encoding="utf-8")
        self.assertIn("B：部分恢复", report)
        self.assertIn("默认 Seat Map 请求不接受 gzip", report)
        self.assertIn("不能称为 Redis server execution", report)
        self.assertIn("未进入真正 B-3 优化", report)
        self.assertIn("151 / 153", report)
        self.assertIn("5 秒缓存", report)
        for run in runs:
            self.assertIn(run["runId"], report)

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
        self.assertNotIn("getBody()", controller)
        self.assertNotIn('"json_serialize"', metrics)
        self.assertIn("newHttpJsonResponse(body)", controller)
        service = (ROOT / "backend/src/services/SeatService.cpp").read_text()
        overlay = (ROOT / "backend/src/services/SeatDisplayStatus.cpp").read_text()
        self.assertGreaterEqual(service.count("displaySeatStatus("), 2)
        self.assertIn('formalStatus != "AVAILABLE"', overlay)
        self.assertIn('*temporaryHoldOwner != ownCheckoutSessionId', overlay)
        config = json.loads((ROOT / "backend/config/config.performance.json").read_text())
        self.assertEqual(config["db_clients"][0]["number_of_connections"], 4)
        self.assertEqual([item["number_of_connections"] for item in config["redis_clients"]], [2, 2])


if __name__ == "__main__":
    unittest.main()
