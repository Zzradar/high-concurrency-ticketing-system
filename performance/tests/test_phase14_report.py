import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]

class ReportTests(unittest.TestCase):
    def test_approved_stop_evidence_matches_exact_scope_and_new_windows(self):
        data=json.loads((ROOT/'performance/experiments/phase14-capacity/approved-project-stop-evidence.json').read_text(encoding='utf-8'))
        self.assertEqual(set(data['authorizedProjects']),{'phase12-2b-gate','phase12-approved','phase12-gate'})
        selected=data['selectedBefore'];self.assertEqual(len(selected),12)
        self.assertEqual({x['project'] for x in selected},set(data['authorizedProjects']))
        self.assertEqual(len(data['operations']),1)
        self.assertEqual(data['operations'][0]['argv'][:2],['docker','stop'])
        self.assertEqual(set(data['operations'][0]['argv'][2:]),{x['id'] for x in selected})
        for row in selected:
            for key in ('ports','mounts','composeFiles','image','state'):self.assertIn(key,row)
        self.assertEqual({x['Name'] for x in data['volumesBefore']},{x['Name'] for x in data['volumesAfter']})
        self.assertTrue(data['checks']['otherContainersUnchanged'])
        samples=[]
        for window in data['windows']:
            self.assertGreaterEqual(window['seconds'],60);self.assertTrue(window['stable']);samples+=window['samples']
        for key in ('pswpin','pswpout'):self.assertEqual(len({x[key] for x in samples}),1)

    def test_checkpoint_never_promotes_smoke_to_formal_capacity(self):
        path=ROOT/'performance/experiments/phase14-capacity/evidence-summary.json'
        data=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(data['status'],'implementation_incomplete_environment_stop')
        self.assertTrue(data['notFormalCapacityEvidence'])
        self.assertGreater(data['stop']['swapInAfter'],data['stop']['swapInBefore'])
        self.assertGreater(data['generation']['osPeakWorkingSetBytes'],0)
        self.assertEqual([x['matched'] for x in data['authCalibration']['auth']],[1000,1000])
        for row in data['runs']:
            self.assertEqual(row['mode'],'smoke')
            self.assertNotEqual(row.get('verdict',{}).get('capacity',{}).get('status'),'pass')
        for forbidden in ('sessionToken','csrfToken','ticketing_session=','sk_test_','whsec_'):
            self.assertNotIn(forbidden,path.read_text(encoding='utf-8'))

if __name__=='__main__':unittest.main()
