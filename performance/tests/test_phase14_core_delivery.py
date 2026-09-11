"""Cross-check the delivered safety stop against preserved measurement evidence."""
import json,re,unittest
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'performance/scripts'))
from phase14_model import load_targets

class CoreDeliveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r=json.loads((ROOT/'docs/phase14_core_results.json').read_text(encoding='utf-8'))

    def test_initialization_qualification_does_not_become_capacity_pass(self):
        r=self.r;self.assertEqual(r['targetsSha256'],load_targets()['sourceSha256'])
        self.assertEqual(r['measuredCommit'],'9006ee822e557255e244364495fbe251a1a25b18')
        self.assertEqual(len(r['method1']['coldRuns']),2)
        for run in r['method1']['coldRuns']:
            self.assertEqual(run['status'],'pass');self.assertLess(run['readySeconds'],30)
            self.assertEqual(run['mainVUs'],10000);self.assertEqual(run['probeVUs'],384)
            self.assertEqual(run['httpRequests']+run['mainStarted']+run['paymentStarted'],0)
            self.assertTrue(run['databaseUnchanged']);self.assertFalse(run['swap'])
        self.assertFalse(r['method2']['used'])
        self.assertEqual(r['smoke']['passed'],r['smoke']['total']);self.assertEqual(r['smoke']['total'],25)
        self.assertEqual(r['g0']['status'],r['qualification']['status']);self.assertEqual(r['qualification']['status'],'pass')
        rows=r['campaign']['runs'];self.assertEqual(len(rows),10)
        self.assertEqual(rows[0]['status'],'invalid_measurement')
        self.assertTrue(all(x['status']=='not_run' for x in rows[1:]))
        self.assertEqual(len(r['excludedFromCorePlan']),14)
        self.assertIn('--core',r['manifest']['argv'])

    def test_fragment_http_counts_conserve_and_are_not_full_window(self):
        d=self.r['u1Diagnostic'];n=sum(d['httpRequestsByScenario'].values())
        self.assertEqual(n,sum(d['httpStatusCounts'].values()));self.assertEqual(n,d['httpLatencyMs']['all']['count'])
        self.assertIsNone(d['formalThroughput']);self.assertIsNone(d['formalBusinessFailureRate'])
        self.assertEqual(n,1977);self.assertLess(d['observedRequestSpanSeconds'],10)
        self.assertEqual(d['admittedMainUsers'],178);self.assertEqual(d['delivery']['main']['interrupted'],178)
        self.assertAlmostEqual(d['observedFragmentRps']*d['observedRequestSpanSeconds'],n)
        self.assertFalse(d['originalCorrectness']['passed']);self.assertFalse(d['finalCorrectness']['passed'])
        self.assertTrue(all(v==0 for v in d['finalCorrectness']['global'].values()))
        final=d['finalCorrectness']['scoped']['paymentTerminal']
        self.assertEqual(final['orders'],final['paid']);self.assertEqual(final['invalid'],0)
        self.assertNotEqual(final['paid'],d['paymentTerminalLog']['success'])

    def test_resource_stop_and_cleanup_do_not_claim_host_fd_detection(self):
        r=self.r;self.assertEqual(r['fdEvidence']['softLimit'],1024)
        self.assertFalse(r['fdEvidence']['hostLevelFdGuardTriggered'])
        self.assertIsNone(r['fdEvidence']['containerUlimits'])
        c=r['cleanup'];self.assertEqual(c['status'],'pass');s=c['services']
        self.assertLess(s['elapsedSeconds'],14400)
        self.assertTrue(all(x['running']==0 for x in s['containers'].values()))
        self.assertTrue(s['imagesPreserved'] and s['historicalEvidencePreserved'])
        self.assertEqual(len(s['volumes']['sut']),2)
        self.assertTrue(c['ssh']['load']['negativeAuthenticationCheck'])
        self.assertFalse(c['ssh']['load']['remainingPrivateKey'])
        self.assertEqual(c['ssh']['sut']['removedAuthorizations'],1)

    def test_report_links_and_privacy(self):
        p=ROOT/'docs/phase14_core_results.md';text=p.read_text(encoding='utf-8')
        for target in re.findall(r'\]\(([^)]+)\)',text):
            self.assertTrue((p.parent/target).is_file(),target)
        self.assertIn('停止容器不会停止 ECS',text)
        self.assertIn('原运行整体对账仍失败',text)
        joined=text+json.dumps(self.r,ensure_ascii=False)
        self.assertNotRegex(joined,r'-----BEGIN .*PRIVATE KEY')
        self.assertNotRegex(joined,r'https?://[^\s/]+:[^\s/@]+@')
        self.assertNotRegex(joined,r'\b(?:\d{1,3}\.){3}\d{1,3}\b')

if __name__=='__main__':unittest.main()
