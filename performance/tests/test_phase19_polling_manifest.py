import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from phase19_polling_manifest import validate_browser


class PollingManifestTests(unittest.TestCase):
    def setUp(self):
        self.point = {'diagnostic': False, 'passed': True, 'revision': 'after', 'protocol': {'script': 'hash'},
            'phases': [{'name': name, 'durationMs': duration, 'activationEpochMs': start}
                for name, duration, start in [('visible',60000,0),('hidden',91000,60000),('restored',30000,151000)]],
            'visibility': [{'type':'visibilitychange','hidden':hidden,'trusted':True,'epochMs':start+5}
                for hidden,start in [(True,60000),(False,151000)]],
            'checks': {'terminalObserved': True, 'readsAfterTerminalSettled': 0,
                'hiddenNewReads':0,'logoutNewReads':0,'maxInflight':{'notifications':1},'restoredImmediateCounts':{'notifications':1}}}

    def test_valid_native_windows(self):
        validate_browser(self.point, 'after', {'script':'hash'})

    def test_refuses_external_window_changes_even_if_original_runner_passed(self):
        self.point['visibility'].insert(0, {'type':'visibilitychange','hidden':True,'trusted':True,'epochMs':10000})
        with self.assertRaises(ValueError): validate_browser(self.point, 'after', {'script':'hash'})

    def test_after_hard_gates_are_rechecked(self):
        for name in ['hiddenNewReads','logoutNewReads','readsAfterTerminalSettled']:
            point = copy.deepcopy(self.point); point['checks'][name] = 1
            with self.subTest(name=name), self.assertRaises(ValueError): validate_browser(point, 'after', {'script':'hash'})

    def test_rejects_diagnostics_short_windows_and_protocol_drift(self):
        for key,value in [('diagnostic',True),('passed',False),('protocol',{'script':'changed'})]:
            point = copy.deepcopy(self.point); point[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError): validate_browser(point, 'after', {'script':'hash'})
        self.point['phases'][1]['durationMs'] = 90000
        with self.assertRaises(ValueError): validate_browser(self.point, 'after', {'script':'hash'})


if __name__ == '__main__': unittest.main()
