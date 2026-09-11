"""Regression gate for the delivered Phase16 measurements and verification evidence."""
from pathlib import Path
import json,re,unittest
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'performance/experiments/phase16-availability'
def read(name):return json.loads((OUT/name).read_text(encoding='utf-8'))
class Phase16EvidenceTest(unittest.TestCase):
    def test_delta_stable_without_inventory_hot_queries(self):
        warm=read('warm-evidence.json')
        for mode in ['delta','controlled']:
            metrics=read(mode+'-k6.json')['metrics']
            self.assertEqual(metrics['http_req_failed']['values']['rate'],0)
            self.assertEqual(metrics['dropped_iterations']['values']['count'],0)
            row=next(r for r in warm['rows'] if r['mode']==mode)
            before={r['query']:r['calls'] for r in row['pgBefore']}
            for r in row['pgAfter']:
                if 'FROM session_seats' in r['query'] or 'FROM checkout_sessions' in r['query']:
                    self.assertEqual(r['calls'],before.get(r['query'],0),r['query'])
        self.assertEqual(warm['finalOutbox'],0);self.assertEqual(warm['finalActiveLeases'],0)
        self.assertEqual([r['changedSeats'] for r in warm['controlledBodySizes']],[1,10,50])
    def test_cold_fault_and_formal_authority(self):
        self.assertEqual(read('cold-timing.json')['pgFullQueries'],1)
        self.assertEqual(read('fault-and-cold.json')['cold']['fullPgQueries'],1)
        self.assertEqual(read('fault-and-cold.json')['projectorCrash']['duplicateBusinessChanges'],0)
        self.assertTrue(read('init-race.json')['postPublicationProjectionConverged'])
        self.assertTrue(read('degraded-confirm.json')['recoveredAndReleased'])
    def test_verifiers_and_browser_pass(self):
        for name in ['verifier.json','phase14-and-expiry.json']:
            result=read(name);self.assertTrue(result['passed']);self.assertFalse(any(result['checks'].values()))
        result=read('playwright.json');self.assertEqual(result['stats']['expected'],2);self.assertEqual(result['stats']['unexpected'],0)
        self.assertTrue(all(r['exitCode']==0 for r in read('final-tests.json')))
    def test_report_does_not_export_environment_and_keeps_unstable_result(self):
        env=read('playwright.json')['config']['webServer']['env']
        self.assertEqual(set(env),{'VITE_USE_MOCK_API','VITE_API_PROXY_TARGET','VITE_STRIPE_PUBLISHABLE_KEY'})
        self.assertNotIn('...process.env',(ROOT/'frontend/playwright.phase16.config.ts').read_text(encoding='utf-8'))
        self.assertGreater(read('snapshot-k6.json')['metrics']['http_req_failed']['values']['rate'],0)
        self.assertIn('失稳',(OUT/'README.md').read_text(encoding='utf-8'))
if __name__=='__main__':unittest.main()
