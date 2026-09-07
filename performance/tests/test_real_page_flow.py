from pathlib import Path
import json
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "performance/scripts"))
import build_real_page_flow_evidence as evidence


class RealPageFlowTests(unittest.TestCase):
    def test_browser_recorder_covers_three_real_ui_milestones(self):
        source = (ROOT / "performance/scripts/record_real_page_flow.mjs").read_text(encoding="utf-8")
        for fragment in (
            "anonymousInitial", "authenticatedInitial", "afterFirstSelection",
            "afterSecondSelection", "checkoutSessionId", "layoutReads !== 1",
            "availabilityReads !== 3", "legacySeatReads !== 0",
        ):
            self.assertIn(fragment, source)
        self.assertIn("requests.map(item => ({...item, query: {...item.query}}))", source)

    def test_capacity_page_entry_follows_session_then_parallel_children(self):
        source = (ROOT / "performance/k6/diagnostics/post-offload-capacity.js").read_text(encoding="utf-8")
        session_index = source.index("const session = http.get")
        batch_index = source.index("const [event, layout, availability] = http.batch")
        self.assertLess(session_index, batch_index)
        for fragment in ("eventPayload.id === eventId", "availabilityIds.size === layoutIds.size",
                         "record('page', response"):
            self.assertIn(fragment, source)

    def test_transfer_series_shows_first_load_cost_and_refresh_benefit(self):
        sizes = {
            "legacy0": {"raw": 100, "gzip": 50},
            "layout": {"raw": 80, "gzip": 40},
            "availability0": {"raw": 30, "gzip": 20},
        }
        rows = evidence.transfer_series(sizes, 0)
        self.assertGreater(rows[0]["splitGzipBytes"], rows[0]["legacyGzipBytes"])
        self.assertLess(rows[2]["splitGzipBytes"], rows[2]["legacyGzipBytes"])

    def test_checked_in_evidence_preserves_page_success_and_mixed_failure(self):
        path = ROOT / "performance/experiments/phase10b-seat-map/real-page-flow-measurements.json"
        if not path.exists():
            self.skipTest("evidence is generated after controlled runs")
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(payload["runs"]), 5)
        for milestone in ("anonymousInitial", "authenticatedInitial", "afterFirstSelection",
                          "afterSecondSelection"):
            snapshot = payload["browserFlow"][milestone]
            self.assertEqual(len(snapshot["requests"]), snapshot["requestCount"])
        page_runs = [run for run in payload["runs"]
                     if run["manifest"]["arguments"]["kind"] == "page-entry"]
        self.assertEqual([run["manifest"]["arguments"]["rate"] for run in page_runs], [10, 30, 60])
        self.assertTrue(all(not run["manifest"]["failures"] for run in page_runs))
        mixed = {run["manifest"]["arguments"]["mixed"]: run for run in payload["runs"]
                 if run["manifest"]["arguments"]["mixed"]}
        self.assertEqual(mixed[1]["manifest"]["compute"]["rejected"], 0)
        self.assertEqual(mixed[2]["manifest"]["compute"]["rejected"], 69)
        self.assertEqual(mixed[2]["manifest"]["runnerExit"], 99)
        self.assertFalse(payload["scope"]["mixed4Executed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
