import importlib.util
from pathlib import Path
import unittest

FILE = Path(__file__).resolve().parents[1] / 'experiments/phase19-global-polling-mixed-load/protocol/resource_gate.py'
spec = importlib.util.spec_from_file_location('phase19_resource_gate', FILE)
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class ResourceGateTests(unittest.TestCase):
    def sample(self, **kw):
        return dict(memory=10, memoryLimit=100, fd=2, fdLimit=100, linuxAvailable=70, linuxTotal=100, cpuFraction=.2, **kw)

    def test_missing_evidence_cannot_pass(self):
        self.assertIsNotNone(gate.stop_reason([]))
        self.assertIsNotNone(gate.stop_reason([{}]))
        self.assertIsNone(gate.stop_reason([self.sample()]))

    def test_memory_fd_and_linux_boundaries(self):
        for key, value in [('memory', 85), ('fd', 80), ('linuxAvailable', 24)]:
            self.assertIsNotNone(gate.stop_reason([{**self.sample(), key: value}]))

    def test_cpu_requires_three_consecutive_observations(self):
        high = {**self.sample(), 'cpuFraction': .91}
        self.assertIsNone(gate.stop_reason([high, high]))
        self.assertIsNotNone(gate.stop_reason([high, high, high]))
        self.assertIsNone(gate.stop_reason([high, self.sample(), high]))

    def test_swap_oom_and_restarts_fail(self):
        self.assertIsNotNone(gate.stop_reason([self.sample(oom=True)]))
        self.assertIsNotNone(gate.stop_reason([self.sample(restarted=True)]))
        self.assertIsNotNone(gate.stop_reason([self.sample(swapOutPages=1)]*3))

    def test_unqualified_samples_cannot_make_estimate_safe(self):
        self.assertEqual(gate.estimate([], 100, 100, 90, 10)['status'], 'INCONCLUSIVE')
        samples = [dict(vus=v, peakBytes=v, valid=True) for v in [100, 250, 500]]
        result = gate.estimate(samples, 1000000, 1000000, 900000, 10000)
        self.assertEqual(result['status'], 'INCONCLUSIVE')
        self.assertFalse(result['actualTensOfThousandsExecuted'])

    def test_max_observed_marginal_and_margin_are_preserved(self):
        samples = [dict(vus=v, peakBytes=m, valid=True) for v, m in [(100, 100), (250, 250), (500, 1000)]]
        result = gate.estimate(samples, 1000, 1000, 900, 100)
        self.assertEqual(result['maxMarginalBytesPerVU'], 3)
        self.assertEqual(result['targets'][0]['conservativeBytes'], 29500)
        self.assertGreaterEqual(result['targets'][0]['generatorWith30PercentMarginBytes'], 29500*1.3)
        self.assertEqual(result['status'], 'UNSAFE')


if __name__ == '__main__':
    unittest.main()
