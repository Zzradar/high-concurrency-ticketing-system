import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[2]

class ReportTests(unittest.TestCase):
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
