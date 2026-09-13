import importlib.util
from pathlib import Path
import unittest
from copy import deepcopy

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('phase19_freeze',ROOT/'performance/scripts/phase19_freeze.py')
freeze=importlib.util.module_from_spec(spec)
spec.loader.exec_module(freeze)


class FreezeTests(unittest.TestCase):
    def test_rejects_wrong_resource_identity_or_changed_executed_core(self):
        hashes={name:name+'-hash' for name in ['workload.js','policy.mjs','stub.py','calibrate.py']}
        identity={'limits':{'generator':{'memoryBytes':4*1024**3}},'protocolSha256':hashes}
        result={'valid':True,'vus':1000,'initializedVUs':1000,'droppedIterations':0,'interruptedOrUncompletedIterations':0}
        freeze.qualification(result,identity,hashes,1000,4)
        with self.assertRaisesRegex(ValueError,'memory identity'):
            freeze.qualification(result,identity,hashes,1000,2)
        changed={**hashes,'workload.js':'different'}
        with self.assertRaisesRegex(ValueError,'core drift'):
            freeze.qualification(result,identity,changed,1000,4)
        with self.assertRaises(ValueError):
            freeze.qualification({**result,'droppedIterations':1},identity,hashes,1000,4)


if __name__=='__main__':unittest.main()
