import sys
from pathlib import Path
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from phase14_stop_approved_projects import PROJECTS,select,swap_stable,Audit,safe

class ApprovedStopTests(unittest.TestCase):
    def test_mount_order_is_not_a_state_change(self):
        x={'Id':'id','Name':'name','Config':{'Image':'image','Labels':{}},'Image':'sha','State':{},'RestartCount':0,
           'NetworkSettings':{},'HostConfig':{},'Mounts':[{'Source':'b','Destination':'/b'},{'Source':'a','Destination':'/a'}]}
        first=safe(x);x['Mounts'].reverse();self.assertEqual(first,safe(x))
        x['Mounts'][0]['Source']='changed';self.assertNotEqual(first,safe(x))
    def test_only_exact_authorized_labels(self):
        values=[{'Config':{'Labels':{'com.docker.compose.project':x}}} for x in [*sorted(PROJECTS),'phase12-gate-other','phase14-capacity','backend','phase12-build']]
        self.assertEqual(len(select(values)),3)
        self.assertEqual(select([{'Config':{}}]),[])
    def test_each_swap_counter_must_remain_constant(self):
        self.assertTrue(swap_stable([{'pswpin':100,'pswpout':50},{'pswpin':100,'pswpout':50}]))
        for end in [{'pswpin':101,'pswpout':50},{'pswpin':100,'pswpout':51},{'pswpin':99,'pswpout':50}]:
            self.assertFalse(swap_stable([{'pswpin':100,'pswpout':50},end]))
        self.assertFalse(swap_stable([]))
    def test_prohibited_docker_verbs_rejected_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit=Audit(Path(tmp)/'evidence')
            for verb in ('down','rm','prune','-v','--volumes'):
                with self.assertRaises(ValueError):audit.docker(verb)

if __name__=='__main__':unittest.main()
