import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from phase14_initialization import Initialization


class InitializationTests(unittest.TestCase):
    def test_smoke_registers_all_processes_before_waiting_but_requires_readiness(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);deadline=time.time()*1000+5000
            with Initialization(root,'run',['0','1'],deadline,lambda:time.sleep(.001),serial=False) as init:
                for shard in ('0','1'):
                    path=root/(shard+'.log');path.write_text('PHASE14_INIT_READY|run|'+shard+'|')
                    init.register(Mock(poll=Mock(return_value=None)),Mock(name=str(path)),shard)
                    init.pending[-1][1].name=str(path)
                self.assertEqual(init.ready,[])
                init.finish()
                self.assertEqual(len(init.ready),2)
            record=json.loads((root/'initialization.json').read_text())
            self.assertEqual(record['mode'],'concurrent_smoke_initialization')
            self.assertEqual(record['releaseAtMs'],deadline)
            self.assertEqual(record['status'],'pass')

    def test_readiness_preserves_order_release_and_safety_observation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);observed=threading.Event()
            def sample():observed.set();observed.wait(.001);time.sleep(.001)
            deadline=time.time()*1000+5000
            with Initialization(root,'run',['0','1'],deadline,sample) as init:
                self.assertTrue(observed.wait(1))
                for shard in ('0','1'):
                    with (root/(shard+'.log')).open('wb') as log:
                        log.write(('PHASE14_INIT_READY|run|'+shard+'|').encode());log.flush()
                        init.wait(Mock(poll=Mock(return_value=None)),log,shard)
                        self.assertEqual(len(init.ready),int(shard)+1)
            result=json.loads((root/'initialization.json').read_text())
            self.assertEqual(result['status'],'pass');self.assertEqual(result['releaseAtMs'],deadline)
            self.assertTrue(result['safetySampling']);self.assertFalse(init.thread.is_alive())

    def test_foreign_marker_cannot_release_a_shard_or_extend_deadline(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with (root/'console.log').open('wb') as log:
                log.write(b'PHASE14_INIT_READY|another-run|0|');log.flush()
                with self.assertRaisesRegex(RuntimeError,'frozen release'):
                    with Initialization(root,'run',['0'],time.time()*1000+20,lambda:time.sleep(.001)) as init:
                        init.wait(Mock(poll=Mock(return_value=None)),log,'0')
            self.assertEqual(json.loads((root/'initialization.json').read_text())['status'],'fail')

    def test_sampler_stop_aborts_even_before_readiness(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            def fail():raise RuntimeError('invalid generator cpu')
            with (root/'console.log').open('wb') as log:
                with self.assertRaisesRegex(RuntimeError,'invalid generator cpu'):
                    with Initialization(root,'run',['0'],time.time()*1000+5000,fail) as init:
                        self.assertTrue(init.stop.wait(1))
                        init.wait(Mock(poll=Mock(return_value=None)),log,'0')
            self.assertFalse(init.thread.is_alive())

    def test_exited_process_is_not_ready_even_with_a_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with (root/'console.log').open('wb') as log:
                log.write(b'PHASE14_INIT_READY|run|0|');log.flush()
                with self.assertRaisesRegex(RuntimeError,'exited before'):
                    with Initialization(root,'run',['0'],time.time()*1000+5000,lambda:time.sleep(.001)) as init:
                        init.wait(Mock(poll=Mock(return_value=0)),log,'0')


if __name__=='__main__':unittest.main()
