import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

PROTOCOL=Path(__file__).resolve().parents[1]/'experiments/phase19-global-polling-mixed-load/protocol'
sys.path.insert(0,str(PROTOCOL))
spec=importlib.util.spec_from_file_location('phase19_calibrate_sample',PROTOCOL/'calibrate.py')
calibrate=importlib.util.module_from_spec(spec)
spec.loader.exec_module(calibrate)

RAW='''100
1000
4
256
oom_kill 0
usage_usec 1000000
MemAvailable: 4000 kB
MemTotal: 5000 kB
pswpout 0
VmRSS: 10 kB
VmHWM: 20 kB
Threads: 3
Max open files 4096 4096 files
eth0: 100 1 0 0 0 0 0 0 200 2 0 0 0 0 0 0
12
9'''


class ResourceSampleTests(unittest.TestCase):
    def test_observes_process_cgroup_and_network_independently(self):
        with patch.object(calibrate,'run',return_value=RAW):
            result=calibrate.sample('phase19-test')
        self.assertEqual(result['rss'],10240)
        self.assertEqual(result['memory'],100)
        self.assertEqual(result['pids'],4)
        self.assertEqual(result['threads'],3)
        self.assertEqual(result['networkRxBytes'],100)
        self.assertEqual(result['networkTxBytes'],200)
        self.assertEqual(result['tcpTableEntries'],7)
        self.assertFalse(result['oom'])

    def test_oom_and_counter_reset_cannot_be_hidden(self):
        with patch.object(calibrate,'run',return_value=RAW.replace('oom_kill 0','oom_kill 1')),patch.object(calibrate.time,'monotonic',return_value=20):
            result=calibrate.sample('phase19-test',{'usageUsec':2000000,'swapOutTotal':0,'monotonic':10})
        self.assertTrue(result['oom'])
        self.assertTrue(result['restarted'])


if __name__=='__main__':unittest.main()
