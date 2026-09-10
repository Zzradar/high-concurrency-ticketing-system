import json
from pathlib import Path
import subprocess
import sys
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'performance/scripts'))
from phase14_model import load_targets

class FlowBehaviorTests(unittest.TestCase):
    def test_real_javascript_flow_with_deterministic_http_and_time(self):
        result=subprocess.run(['node','--experimental-vm-modules','performance/tests/phase14_flow_behavior.mjs'],
            input=json.dumps(load_targets(smoke=True)),capture_output=True,text=True,encoding='utf-8',cwd=ROOT,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

if __name__=='__main__':unittest.main()
