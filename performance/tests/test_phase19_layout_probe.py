import importlib.util
from pathlib import Path
import sys
import unittest

PROTOCOL=Path(__file__).resolve().parents[1]/'experiments/phase19-global-polling-mixed-load/protocol'
sys.path.insert(0,str(PROTOCOL))
spec=importlib.util.spec_from_file_location('phase19_layout_probe',PROTOCOL/'layout_probe.py')
probe=importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class LargeLayoutTests(unittest.TestCase):
    def test_large_layout_reuses_valid_generator_profile(self):
        profile=probe.large_profile()
        shape=probe.generator.validate_profile(profile)
        self.assertEqual(shape.seats,10000)
        self.assertEqual(shape.sessions,1)
        self.assertEqual(sum(z['rows'] for z in profile['priceZones']),100)


if __name__=='__main__':unittest.main()
