"""Post-measurement delivery integrity; does not change the frozen protocol."""
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "performance/experiments/phase18-admission-overload"

def read(path):
    return json.loads(path.read_text(encoding="utf-8"))

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

class DeliveryEvidence(unittest.TestCase):
    def test_delivery_bindings_and_source_identity(self):
        manifest = read(EVIDENCE / "phase18-delivery.json")
        self.assertEqual(manifest["baselineSutSha"], "ed51447154418e05ed9e4c49728f3eb114713db9")
        self.assertEqual(manifest["afterSutSha"], "4dd48c177516caf950103ce3f7751cc0fb056029")
        self.assertTrue(manifest["formalAbPassed"])
        for path, expected in manifest["artifacts"].items():
            with self.subTest(path=path):
                self.assertEqual(digest(EVIDENCE / path), expected)
        for path, expected in manifest["frozenManifests"].items():
            self.assertEqual(digest(EVIDENCE / path), expected)
        for path, expected in manifest["protocolHashes"].items():
            self.assertEqual(digest(EVIDENCE / "protocol" / path), expected)

    def test_all_after_raw_bytes_match_frozen_manifest(self):
        manifest = read(EVIDENCE / "after/manifest.json")
        self.assertGreater(len(manifest["files"]), 50)
        for path, expected in manifest["files"].items():
            with self.subTest(path=path):
                raw = (EVIDENCE / "after" / path).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), expected["sha256"])
                self.assertEqual(len(raw), expected["bytes"])

    def test_final_source_long_hidden_is_native_and_silent(self):
        directory = EVIDENCE / "capabilities/final-hidden"
        manifest = read(directory / "manifest.json")
        self.assertEqual(manifest["sourceSutSha"], "4dd48c177516caf950103ce3f7751cc0fb056029")
        for path, expected in manifest["files"].items():
            self.assertEqual(digest(directory / path), expected)
        script = manifest["script"]
        self.assertEqual(digest(EVIDENCE / script["path"]), script["sha256"])
        browser = read(directory / "browser.json")
        self.assertTrue(browser["passed"])
        self.assertEqual(browser["maxInflight"], 1)
        targets = browser["topology"]
        self.assertEqual(len(targets), 2)
        self.assertEqual(len({x["windowId"] for x in targets}), 1)
        self.assertEqual(len({x["browserContextId"] for x in targets}), 1)
        records = browser["timeline"][0]["records"]
        hidden = next(x["dateNow"] for x in records if x["type"] == "visibilitychange" and x["hidden"] and x["trusted"])
        restored = next(x["dateNow"] for x in records if x["type"] == "visibilitychange" and not x["hidden"] and x["trusted"] and x["dateNow"] > hidden)
        self.assertGreaterEqual(restored - hidden, 90000)
        self.assertFalse([r for r in browser["requests"] if hidden <= r["startEpochMs"] < restored])
        requests = [r for r in browser["requests"] if r["startEpochMs"] >= restored]
        self.assertEqual(sum(r.get("mode") == "snapshot" for r in requests), 1)
        self.assertLess(requests[0]["startEpochMs"] - restored, 1000)
