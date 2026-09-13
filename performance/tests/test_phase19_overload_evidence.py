import importlib.util
from pathlib import Path
import unittest

FILE=Path(__file__).resolve().parents[2]/'backend/tests/phase19_overload_recovery_test.py'
spec=importlib.util.spec_from_file_location('phase19_overload_recovery',FILE)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class OverloadEvidenceTests(unittest.TestCase):
    def test_rejections_and_system_failures_remain_separate(self):
        rows=[{'status':s,'code':c,'milliseconds':ms} for s,c,ms in [(409,'ADMISSION_REQUIRED',2),(429,'RATE_LIMITED',3),(503,'SYSTEM_OVERLOADED',4),(200,None,1)]]
        result=module.summarize(rows)
        self.assertEqual(result['count'],4)
        self.assertEqual(result['outcomes'],{'409:ADMISSION_REQUIRED':1,'429:RATE_LIMITED':1,'503:SYSTEM_OVERLOADED':1,'200:None':1})
        self.assertEqual(result['maxMilliseconds'],4)
    def test_empty_capture_is_explicitly_empty_not_a_success_rate(self):
        self.assertEqual(module.summarize([]),{'count':0,'outcomes':{},'maxMilliseconds':0})
