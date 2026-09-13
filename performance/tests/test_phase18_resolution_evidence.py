"""Immutable v3 identity, raw evidence and namespace regression delivery gates."""
import hashlib,json,re,subprocess,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
E=ROOT/'performance/experiments/phase18-admission-overload'
SUT='3a9e0c1311add748c7faec956bb6c9266ed7d5ba'
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
class ResolutionEvidence(unittest.TestCase):
 def test_after_manifest_every_raw_byte_and_frozen_protocol(self):
  directory=E/'after-v3';m=read(directory/'manifest.json')
  self.assertEqual(m['source']['sha'],SUT);self.assertFalse(m['source']['gitDirty'])
  self.assertEqual(m['source']['scripts'],read(E/'baseline/manifest.json')['source']['scripts'])
  self.assertEqual(sha(directory/'manifest.json'),'d1614a9761f8f0819be6e9da71677f096cc76d5beadf093e52915580f6f56440')
  for name,v in m['files'].items():
   self.assertEqual(sha(directory/name),v['sha256'],name);self.assertEqual((directory/name).stat().st_size,v['bytes'])
 def test_all_six_installed_invoker_functions_are_path_controlled(self):
  c=E/'capabilities/layout-resolution';m=read(c/'manifest.json')
  self.assertEqual(m['productionSourceCommit'],SUT);self.assertTrue(m['capabilityBinaryMatchesAfter'])
  for name,v in m['files'].items():self.assertEqual(sha(c/name),v,name)
  defs=read(c/'installed-functions.json');self.assertEqual(len(defs),6)
  for f in defs:
   self.assertEqual(f['schema'],'public');self.assertFalse(f['securityDefiner']);self.assertEqual(f['proconfig'],['search_path=pg_catalog'])
   self.assertNotIn('current_schema()',f['definition'])
  old=read(c/'original-independent-failure.json');new=read(c/'schema-shadow-counterexample.json')
  self.assertEqual(old['conditional']['status'],304);self.assertEqual(old['revisionAfter'],old['revisionBefore'])
  self.assertEqual(new['conditional']['status'],200);self.assertEqual(new['revisionAfter'],new['revisionBefore']+1)
  self.assertNotEqual(new['after']['etag'],new['before']['etag']);self.assertEqual(new['restored']['sha256'],new['before']['sha256'])
 def test_complete_regression_logs_and_closed_failures(self):
  c=E/'capabilities/layout-resolution'
  names=['resolution-schema-final','revision-schema','layout-http-all','layout-publish','phase17-auth-zone','phase17-verifier','phase18_availability_fault_test-r2','phase11_stripe_integration_test','phase11_crash_window_integration_test','phase12_buyer_refund_integration_test','phase18_refund_verifier_fixture','phase18_multi_instance_test','phase18_off_regression']
  names+=['phase15_migration_test','phase17_schema_test','phase18_schema_test','phase18_policy_http_test','phase18_admission_http_test','phase18_waiting_room_test','phase18_token_bucket_test','phase18_traffic_http_test','phase18_public_contract_test','phase18_inventory_fault_test','phase18_checkout_crash_test','phase18_metrics_http_test','phase18_verifier_test']
  for name in names:
   text=(c/(name+'.log')).read_text(encoding='utf-8');self.assertRegex(text,r'(?m)^OK\s*$');self.assertNotRegex(text,r'FAILED \(')
  self.assertIn('100% tests passed',(E/'after-v3/backend-ctest.log').read_text())
  frontend=read(c/'frontend-tests.json');self.assertEqual(frontend['numFailedTests'],0);self.assertEqual(frontend['numPassedTests'],288)
  self.assertIn('phase18_availability_fault_test.log',read(c/'manifest.json')['closedDiagnosticFiles'])
 def test_layout_sql_totals_come_from_raw_snapshots(self):
  totals=read(E/'layout-total-sql-v3.json')
  for side,folder in [('before','baseline'),('after','after-v3')]:
   for n in [5000,10000]:
    before={r['queryid']:r for r in read(E/folder/f'layout-{n}-before-database.json')['pg']}
    rows=read(E/folder/f'layout-{n}-after-database.json')['pg'];t=totals[side][str(n)]
    self.assertEqual(t['allTrackedCalls'],sum(r['calls']-before.get(r['queryid'],{}).get('calls',0) for r in rows))
    self.assertEqual(t['allTrackedReturnedRows'],sum(r['rows']-before.get(r['queryid'],{}).get('rows',0) for r in rows))
  c=read(E/'comparison-v3.json');self.assertTrue(c['passed']);self.assertEqual(c['afterSutSha'],SUT)
  for v in c['layoutAndAvailability']:
   self.assertEqual(sum(q['calls'] for q in v['afterSql']),64)
   self.assertEqual(sum(q['calls'] for q in v['afterSql'] if q['kind']=='fullLayout'),22)
 def test_native_hidden_restoration_and_long_probe(self):
  for folder,long in [('after-v3',False),('capabilities/final-hidden-v3',True)]:
   d=read(E/folder/'browser.json');self.assertTrue(d['passed']);self.assertEqual(d['maxInflight'],1)
   records=next(t['records'] for t in d['timeline'] if '/sessions/' in t['url'])
   h=next(r['dateNow'] for r in records if r['type']=='visibilitychange' and r['hidden'] and r['trusted'])
   v=next(r['dateNow'] for r in records if r['type']=='visibilitychange' and not r['hidden'] and r['trusted'] and r['dateNow']>h)
   self.assertGreaterEqual(v-h,90000 if long else 10000)
   self.assertFalse([r for r in d['requests'] if h<=r['startEpochMs']<v]);resumed=[r for r in d['requests'] if r['startEpochMs']>=v]
   self.assertEqual(sum(r.get('mode')=='snapshot' for r in resumed),1);self.assertLess(resumed[0]['startEpochMs']-v,1000)
   self.assertEqual(len(d['topology']),2);self.assertEqual(len({r['windowId'] for r in d['topology']}),1);self.assertEqual(len({r['browserContextId'] for r in d['topology']}),1)
  m=read(E/'capabilities/final-hidden-v3/manifest.json');self.assertEqual(m['sourceSutSha'],SUT)
  for p,h in m['files'].items():self.assertEqual(sha(E/'capabilities/final-hidden-v3'/p),h)
 def test_old_migrations_and_protected_directories_unchanged(self):
  paths=['backend/db/migrations/'+f'{n:03d}*' for n in range(1,16)]
  paths+=['performance/experiments/phase18-admission-overload/'+p for p in ['baseline','protocol','diagnostics','after','after-v2']]
  self.assertEqual(subprocess.check_output(['git','diff','--name-only','8a62d57','HEAD','--',*paths],cwd=ROOT),b'')
  self.assertEqual(sha(E/'history/8a62d57/phase18-delivery.json'),'b3690ca98faf5f588cd5428809a9ea98b4c42e0811bf104f3c752e1ea8ef1126')
