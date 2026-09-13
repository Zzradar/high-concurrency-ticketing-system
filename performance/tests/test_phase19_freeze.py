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
        with self.assertRaisesRegex(ValueError,'outside core'):
            freeze.qualification(result,identity,{**hashes,'resource_gate.py':'new-safety-rule'},1000,4)

    def test_higher_maximum_requires_every_preceding_qualification(self):
        self.assertEqual(freeze.qualified_tiers(1000),[100,250,500,1000])
        self.assertEqual(freeze.qualified_tiers(2000),[100,250,500,1000,2000])
        self.assertEqual(freeze.qualified_tiers(3000),[100,250,500,1000,2000,3000])
        with self.assertRaises(ValueError):freeze.qualified_tiers(5000)

    def test_new_qualification_identity_cannot_escape_private_parent(self):
        parent=Path('private')
        self.assertEqual(freeze.qualification_directory(parent,4,2000,'phase19-r2-4g-{vus}'),parent/'phase19-r2-4g-2000')
        for template in ['../phase19-{vus}','phase19-{vus}/child','other-{vus}','phase19-fixed']:
            with self.assertRaises(ValueError):freeze.qualification_directory(parent,4,2000,template)


if __name__=='__main__':unittest.main()
