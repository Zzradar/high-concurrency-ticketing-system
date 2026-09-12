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
        manifest = read(EVIDENCE / "history/fc9e41a/phase18-delivery.json")
        self.assertEqual(manifest["baselineSutSha"], "ed51447154418e05ed9e4c49728f3eb114713db9")
        self.assertEqual(manifest["afterSutSha"], "4dd48c177516caf950103ce3f7751cc0fb056029")
        self.assertTrue(manifest["formalAbPassed"])
        for path, expected in manifest["artifacts"].items():
            with self.subTest(path=path):
                self.assertEqual(digest(EVIDENCE / ("history/fc9e41a/FINAL_REPORT.md" if path == "FINAL_REPORT.md" else path)), expected)
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

    def test_historical_source_long_hidden_is_native_and_silent(self):
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

class CurrentDeliveryEvidence(unittest.TestCase):
    def test_current_manifest_bindings_and_capabilities(self):
        manifest=read(EVIDENCE / "phase18-delivery.json")
        self.assertEqual(manifest["afterSutSha"],"6807a01516a75cf834ca1fac46fb1ac9abcdc53e")
        self.assertEqual(manifest["afterDirectory"],"after-v2")
        self.assertTrue(manifest["formalAbPassed"])
        for path,expected in manifest["artifacts"].items():
            self.assertEqual(digest(EVIDENCE/path),expected,path)
        for path,expected in manifest["frozenManifests"].items():
            self.assertEqual(digest(EVIDENCE/path),expected,path)
        for path,expected in manifest["protocolHashes"].items():
            self.assertEqual(digest(EVIDENCE/"protocol"/path),expected,path)
        import subprocess
        analysis=manifest["analysis"]
        for path,expected in analysis["gitBlobSha256"].items():
            self.assertEqual(hashlib.sha256(subprocess.check_output(["git","show",analysis["commit"]+":"+path],cwd=ROOT)).hexdigest(),expected)
        for name in ["layout-revision-final","final-hidden-v2"]:
            directory=EVIDENCE/"capabilities"/name
            m=read(directory/"manifest.json")
            for path,expected in m["files"].items():
                self.assertEqual(digest(directory/path),expected,path)

    def test_current_raw_bytes_and_honest_sample_counts(self):
        directory=EVIDENCE/"after-v2"
        manifest=read(directory/"manifest.json")
        self.assertEqual(manifest["source"]["sha"],"6807a01516a75cf834ca1fac46fb1ac9abcdc53e")
        self.assertFalse(manifest["source"]["gitDirty"])
        for path,expected in manifest["files"].items():
            self.assertEqual(digest(directory/path),expected["sha256"],path)
            self.assertEqual((directory/path).stat().st_size,expected["bytes"])
        summary=read(EVIDENCE/"resource-and-payload-comparison-v2.json")
        self.assertEqual(summary["before"]["k6Requests"],121)
        self.assertEqual(summary["after"]["k6Requests"],120)
        self.assertEqual(summary["after"]["browserBytes"],104440)
        comparison=read(EVIDENCE/"comparison-v2.json")
        self.assertEqual(comparison["afterBrowser"]["networkMaxInflight"],1)
        for result in comparison["layoutAndAvailability"]:
            self.assertEqual(sum(q["calls"] for q in result["afterSql"]),64)
            self.assertEqual(sum(q["calls"] for q in result["afterSql"] if q["kind"]=="fullLayout"),22)

    def test_current_native_three_period_hidden_gate(self):
        directory=EVIDENCE/"capabilities/final-hidden-v2"
        manifest=read(directory/"manifest.json")
        self.assertEqual(manifest["sourceSutSha"],"6807a01516a75cf834ca1fac46fb1ac9abcdc53e")
        self.assertEqual(digest(EVIDENCE/manifest["script"]["path"]),manifest["script"]["sha256"])
        browser=read(directory/"browser.json")
        self.assertTrue(browser["passed"])
        self.assertEqual(browser["maxInflight"],1)
        self.assertEqual(len(browser["topology"]),2)
        self.assertEqual(len({t["windowId"] for t in browser["topology"]}),1)
        self.assertEqual(len({t["browserContextId"] for t in browser["topology"]}),1)
        records=browser["timeline"][0]["records"]
        hidden=next(r["dateNow"] for r in records if r["type"]=="visibilitychange" and r["hidden"] and r["trusted"])
        restored=next(r["dateNow"] for r in records if r["type"]=="visibilitychange" and not r["hidden"] and r["trusted"] and r["dateNow"]>hidden)
        self.assertGreaterEqual(restored-hidden,90000)
        self.assertFalse([r for r in browser["requests"] if hidden<=r["startEpochMs"]<restored])
        resumed=[r for r in browser["requests"] if r["startEpochMs"]>=restored]
        self.assertEqual(sum(r.get("mode")=="snapshot" for r in resumed),1)
        self.assertLess(resumed[0]["startEpochMs"]-restored,1000)
