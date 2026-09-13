import importlib.util
from pathlib import Path
import sys
import unittest
import threading
from unittest.mock import patch

PROTOCOL = Path(__file__).resolve().parents[1] / 'experiments/phase19-global-polling-mixed-load/protocol'
sys.path.insert(0, str(PROTOCOL))
spec = importlib.util.spec_from_file_location('phase19_propagation', PROTOCOL / 'propagation.py')
propagation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(propagation)


class PropagationTests(unittest.TestCase):
    def test_resource_stop_prevents_new_observer_request(self):
        observer=object.__new__(propagation.Observer)
        observer.cancel=threading.Event()
        observer.cancel.set()
        observer.next_read=0
        with self.assertRaisesRegex(RuntimeError,'resource gate'):
            observer.read()

    def test_cached_held_cannot_prove_formal_projection(self):
        observer = object.__new__(propagation.Observer)
        observer.state = {'seat': 'HELD'}
        reads = []
        def read():
            reads.append(1)
            observer.changed = {'seat'} if len(reads) == 2 else set()
            return 11+len(reads)
        observer.read = read
        with patch.object(propagation.time, 'perf_counter', return_value=10):
            result = observer.wait_for('seat', 'HELD', 10, 'formal', 'confirm', require_change=True)
        self.assertEqual(len(reads), 2)
        self.assertEqual(result['milliseconds'], 3000)
        self.assertTrue(result['matched'])

    def test_timeout_is_a_mismatch_not_a_latency_sample(self):
        observer = object.__new__(propagation.Observer)
        with patch.object(propagation.time, 'perf_counter', return_value=41):
            result = observer.wait_for('seat', 'AVAILABLE', 10, 'convergence', 'cancel')
        self.assertFalse(result['matched'])
        self.assertIsNone(result['milliseconds'])

    def test_dwell_requires_two_actual_planned_read_opportunities(self):
        observer = object.__new__(propagation.Observer)
        observer.read = lambda: None
        with patch.object(propagation.time, 'perf_counter', side_effect=[0, 0, 20]):
            with self.assertRaisesRegex(RuntimeError, 'two planned'):
                observer.dwell(10)


if __name__ == '__main__':
    unittest.main()
