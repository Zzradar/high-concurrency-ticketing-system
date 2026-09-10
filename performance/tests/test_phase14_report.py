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

    def test_policy_followup_preserves_failure_and_reports_real_checks(self):
        path=ROOT/'performance/experiments/phase14-capacity/smoke-policy-followup.json'
        data=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(data['status'],'incomplete_u2_delivery_guard_stop')
        self.assertTrue(data['historicalFailureUnchanged']['passed'])
        self.assertEqual(data['historicalFailureUnchanged']['changedFiles'],[])
        row=data['u2']['delivery']['refresh_0'];self.assertEqual((row['planned'],row['started']),(10,9))
        self.assertEqual(data['u2']['verdict']['capacity']['status'],'not_applicable')
        self.assertEqual(sum(x['tests'] for x in data['regressions']['modules'])+data['paymentFailure']['tests'],57)
        self.assertTrue(data['liveMetrics']['passed'])
        self.assertTrue(all(x['passed'] for x in data['exporter']['checks']))
        self.assertEqual(data['exporter']['cleanup']['remainingFixtureConnections'],0)
        self.assertEqual(data['overhead']['comparison']['capacity'],'not_applicable')
        self.assertTrue(all(x['requests']==x['planned'] and x['dropped']==0 for x in data['overhead']['legs']))

    def test_v2_matrix_retains_failures_and_never_claims_formal_capacity(self):
        data=json.loads((ROOT/'performance/experiments/phase14-capacity/v2-evidence-summary.json').read_text(encoding='utf-8'))
        self.assertEqual(len(data['runs']),25);self.assertEqual(data['newV2MatrixRuns'],21)
        self.assertTrue(data['configuration']['businessConfigurationUnchanged'])
        self.assertEqual(data['configuration']['historyChangedFiles'],[])
        for row in data['runs']:
            self.assertTrue(row['functionalSmoke']);self.assertTrue(row['correctness']['passed'])
            self.assertEqual(row['verdict']['measurement_validity']['status'],'fail')
            self.assertEqual(row['verdict']['capacity']['status'],'not_applicable')
            if 'delivery' in row:
                self.assertEqual(row['dropped'],0)
                for delivered in row['delivery'].values():
                    if delivered['planned'] is not None:self.assertEqual(delivered['planned'],delivered['started'])
                    self.assertEqual(delivered['started'],delivered['completed'])
        for probe in data['deliveryProbes']:
            self.assertGreater(probe['boundaryTicks'],0);self.assertEqual(probe['httpRequests'],30)
            self.assertEqual(probe['nativeIterations'],probe['businessCompleted']+probe['boundaryTicks'])
        for retry in data['h3PersistentSamplingRetests']:
            self.assertTrue(retry['connection']['closed']);self.assertTrue(retry['connection']['readOnly'])
            self.assertLess(retry['light']['maxGapSeconds'],retry['light']['intervalSeconds']*2)
        self.assertFalse(data['samplingComparisons'][1]['comparison']['passed'])
        self.assertTrue(data['samplingComparisons'][2]['comparison']['passed'])
        self.assertEqual(data['samplingComparisons'][2]['input']['baselineSeconds'],60)
        self.assertTrue(data['browser']['layoutAvailabilityOverlapObserved'])
        for row in data['browser']['afterSecondSelection']['requests']:
            if row['method'] in ('POST','PUT'):self.assertTrue(row['hasSessionCookie'] and row['hasCsrfHeader'])
        self.assertEqual(data['externalContainerAudit']['changed'],[])

    def test_v3_completion_keeps_startup_and_diagnostics_separate(self):
        data=json.loads((ROOT/'performance/experiments/phase14-capacity/v3-evidence-summary.json').read_text(encoding='utf-8'))
        self.assertEqual(data['status'],'code_tests_and_local_functional_rehearsal_complete')
        self.assertEqual(len(data['runs']),12);self.assertTrue(data['browser']['startupContract']['passed'])
        self.assertTrue(data['historyAudit']['unchangedBusinessConfig'])
        self.assertEqual(data['historyAudit']['v2VerdictsUnchanged'],25)
        for row in data['runs']:
            self.assertTrue(row['functionalSmoke']);self.assertTrue(row['correctness']['passed']);self.assertEqual(row['dropped'],0)
            for key in ('capacity','overload_protection','formal_recovery'):self.assertEqual(row['verdict'][key]['status'],'not_applicable')
            self.assertIn('formalRecovery',row['verdict']['diagnostic'])
            for count in row['startupDelivery'].values():
                self.assertEqual(count['planned'],count['started']);self.assertEqual(count['started'],count['completed'])
            if row['case'].startswith('L'):
                self.assertEqual(row['startupDelivery']['startup']['planned'],0)
                self.assertTrue(row['backgroundStartup']['finishedBeforeRelease']);self.assertTrue(row['backgroundStartup']['check']['passed'])
            else:self.assertEqual(row['startupDelivery']['startup']['planned'],20)
        self.assertFalse(data['preservedFirstFailure']['correctness']['passed'])
        self.assertEqual(data['samplingDiagnostic']['comparison']['status'],'not_applicable')
        for leg in data['samplingDiagnostic']['legs']:
            self.assertEqual(leg['requests'],1200);self.assertEqual(leg['failures'],0);self.assertEqual(leg['dropped'],0)
        self.assertEqual(data['externalContainerAudit']['changed'],[])
        self.assertEqual(data['checks']['ctest']['passed'],30)

if __name__=='__main__':unittest.main()
