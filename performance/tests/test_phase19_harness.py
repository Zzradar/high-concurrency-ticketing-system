import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

PROTOCOL = Path(__file__).resolve().parents[1] / 'experiments/phase19-global-polling-mixed-load/protocol'
sys.path.insert(0, str(PROTOCOL))
spec = importlib.util.spec_from_file_location('phase19_harness', PROTOCOL / 'harness.py')
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


class RedisObservationTests(unittest.TestCase):
    def setUp(self):
        self.stack = object.__new__(harness.Stack)
        self.stack.prefix = 'phase19-test'

    def test_info_is_raw_text_even_in_cli_json_mode(self):
        raw = '# Memory\nused_memory:123\n'
        with patch.object(harness, 'run', return_value=raw):
            self.assertEqual(self.stack.redis('INFO', 'memory'), raw)

    def test_structured_responses_remain_json(self):
        with patch.object(harness, 'run', return_value='["one","two"]'):
            self.assertEqual(self.stack.redis('LRANGE', 'key', '0', '-1'), ['one', 'two'])

    def test_cli_error_is_not_successful_observation(self):
        with patch.object(harness, 'run', return_value='error:ERR unknown command'):
            with self.assertRaises(RuntimeError):
                self.stack.redis('INFO', 'memory')


if __name__ == '__main__':
    unittest.main()
