import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from phase19_l3_repeatability import qualify

class L3RepeatabilityTest(unittest.TestCase):
    def setUp(self):
        self.rounds = [{'prefix': f'fresh-{i}', 'initialStateSha256': 'same-state',
            'initialVerifierPassed': True, 'points': [
                {'name': n, 'valid': True, 'dropped': 0, 'interrupted': 0,
                 'unexpectedErrors': 0, 'http503': 0, 'deltaPerSecond': 500,
                 'writePerSecond': 42.85, 'inventoryPassed': True}
                for n in ['precheck', 'l1', 'l2', 'l3']]} for i in range(3)]
    def test_three_independent_passes(self):
        self.assertTrue(qualify(self.rounds)['qualified'])
    def test_first_failure_cannot_be_replaced_by_retry(self):
        self.rounds[0]['points'][-1]['valid'] = False
        self.rounds[0]['points'].append(copy.deepcopy(self.rounds[1]['points'][-1]))
        self.assertFalse(qualify(self.rounds)['qualified'])
    def test_warm_environment_reuse_rejected(self):
        self.rounds[2]['prefix'] = self.rounds[0]['prefix']
        self.assertFalse(qualify(self.rounds)['qualified'])
    def test_initial_state_mismatch_rejected(self):
        self.rounds[2]['initialStateSha256'] = 'different'
        self.assertFalse(qualify(self.rounds)['qualified'])
    def test_missing_initial_verification_rejected(self):
        self.rounds[1]['initialVerifierPassed'] = False
        self.assertFalse(qualify(self.rounds)['qualified'])
    def test_each_zero_error_condition_enforced(self):
        for key in ['dropped', 'interrupted', 'unexpectedErrors', 'http503']:
            with self.subTest(key=key):
                rounds = copy.deepcopy(self.rounds)
                rounds[0]['points'][-1][key] = 1
                self.assertFalse(qualify(rounds)['qualified'])
    def test_rates_not_rounded_up(self):
        for key, value in [('deltaPerSecond', 499.999), ('writePerSecond', 42.849)]:
            with self.subTest(key=key):
                rounds = copy.deepcopy(self.rounds)
                rounds[0]['points'][-1][key] = value
                self.assertFalse(qualify(rounds)['qualified'])
    def test_nonfinite_rates_rejected(self):
        for value in [float('nan'), float('inf'), None]:
            with self.subTest(value=value):
                rounds = copy.deepcopy(self.rounds)
                rounds[0]['points'][-1]['deltaPerSecond'] = value
                self.assertFalse(qualify(rounds)['qualified'])
    def test_invariants_required(self):
        self.rounds[0]['points'][-1]['inventoryPassed'] = False
        self.assertFalse(qualify(self.rounds)['qualified'])
    def test_lower_tier_failure_not_hidden(self):
        self.rounds[1]['points'][1]['valid'] = False
        self.assertFalse(qualify(self.rounds)['qualified'])
    def test_three_rounds_required(self):
        self.assertFalse(qualify(self.rounds[:2])['qualified'])
    def test_order_required(self):
        self.rounds[0]['points'].reverse()
        self.assertFalse(qualify(self.rounds)['qualified'])
if __name__ == '__main__': unittest.main()