import importlib.util
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location("revision_analysis",ROOT/"performance/scripts/phase18_revision_analysis.py")
analysis=importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)
BASELINE=ROOT/"performance/experiments/phase18-admission-overload/baseline"
class RevisionAnalysis(unittest.TestCase):
    def test_frozen_resource_and_payload_goldens(self):
        value=analysis.resource_features(BASELINE)
        self.assertEqual(value["samples"],46)
        self.assertEqual(value["browserBytes"],69296)
        self.assertEqual(value["k6Requests"],121)
        self.assertEqual(value["k6ErrorRate"],0)
        self.assertEqual(value["processObservedPeaks"]["VmHWM"],237556)
        self.assertEqual(value["processObservedPeaks"]["cgroupMemoryBytes"],183541760)
        self.assertEqual([x["layoutWireBytes"] for x in value["payloads"]],[20513772,41435548])
    def test_frozen_command_and_sql_goldens(self):
        value=analysis.query_features(BASELINE)
        self.assertEqual(value["browser"]["redis"]["cmdstat_eval"]["calls"],108)
        self.assertEqual(value["browser"]["redis"]["cmdstat_hget"]["calls"],8304)
        self.assertEqual(value["k6"]["redis"]["cmdstat_eval"]["calls"],363)
        queries=value["browser"]["sql"]
        self.assertTrue(any(x["calls"]==36 and x["returnedRows"]==36 for x in queries))
    def test_empty_and_zero_counter_info(self):
        self.assertEqual(analysis.redis_commands("# Commandstats\r\n"),{})
        value=analysis.redis_commands("cmdstat_eval:calls=0,usec=0,failed_calls=0,rejected_calls=0\r\n")
        self.assertEqual(int(value["cmdstat_eval"]["calls"]),0)
