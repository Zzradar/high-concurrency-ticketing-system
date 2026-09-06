import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "performance/scripts"))
import build_static_dynamic_split_evidence as split


class SeatMapSplitTests(unittest.TestCase):
    def test_response_bytes_accept_old_and_new_probe_schema(self):
        old = {"gzip": {"rawBodyBytes": 10, "seatCount": 2,
                        "gzip": {"receivedBodyBytes": 5}}}
        new = {"gzip": {"endpoint": "seat-availability", "rawBodyBytes": 8,
                        "seatCount": 2, "gzip": {"receivedBodyBytes": 4}}}
        self.assertEqual(split.response_bytes(old)["endpoint"], "seats")
        self.assertEqual(split.response_bytes(new)["endpoint"], "seat-availability")

    def test_committed_evidence_has_required_matrix_and_hard_gates(self):
        path = (ROOT / "performance/experiments/phase10b-seat-map/"
                "static-dynamic-split-measurements.json")
        if not path.exists():
            self.skipTest("evidence is generated after controlled runs")
        evidence = json.loads(path.read_text(encoding="utf-8"))
        runs = evidence["runs"]
        stable = [run for run in runs if not run["failures"]]
        self.assertTrue(all(run["identityBefore"] == run["identityAfter"] for run in runs))
        self.assertEqual(
            sorted(run["arguments"]["rate"] for run in stable
                   if run["arguments"]["kind"] == "availability"
                   and run["arguments"]["density"] == 0
                   and not run["arguments"]["mixed"]),
            [60, 100, 150, 200],
        )
        unstable, = [run for run in runs
                     if run["arguments"]["kind"] == "availability"
                     and run["arguments"]["density"] == 0
                     and run["arguments"]["rate"] == 300]
        self.assertGreater(unstable["compute"]["rejected"], 0)
        self.assertEqual(unstable["runnerExit"], 99)
        self.assertEqual(
            sorted(run["arguments"]["rate"] for run in stable
                   if run["arguments"]["kind"] == "page-entry"),
            [10, 30, 60],
        )
        mixed, = [run for run in stable if run["arguments"]["mixed"] == 2]
        self.assertEqual(mixed["rates"], {"seat": 150, "public": 200, "auth": 200})
        self.assertFalse(evidence["scope"]["mixed4Executed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
