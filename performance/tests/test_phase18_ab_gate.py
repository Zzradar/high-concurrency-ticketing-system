import importlib.util,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('phase18_ab_gate',ROOT/'performance/scripts/phase18_ab_gate.py');gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
class Comparison(unittest.TestCase):
 def test_frozen_timeline_classification_and_sql_features(self):
  b=gate.browser(gate.read(gate.B/'browser.json'));self.assertEqual(b['requestStartsByPhase'],{'visible':30,'hidden':0,'restored':6});self.assertEqual(b['networkMaxInflight'],2);self.assertEqual(b['restoreFirstRequestMs'],4)
  for n in [5000,10000]:
   rows=gate.sql_features(gate.B,n);self.assertEqual(sum(x['calls'] for x in rows),42);self.assertEqual(sum(x['returnedRows'] for x in rows),42*n)
