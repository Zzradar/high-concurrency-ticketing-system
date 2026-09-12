"""Evidence gates for the immutable Phase18 pre-change measurement, not business implementation tests."""
import hashlib,json,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
E=ROOT/'performance/experiments/phase18-admission-overload'
B=E/'baseline'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
class Phase18BaselineEvidence(unittest.TestCase):
 def test_exact_source_and_protocol_bytes(self):
  source=read(B/'source.json')
  self.assertEqual(source['sha'],'ed51447154418e05ed9e4c49728f3eb114713db9')
  self.assertFalse(source['gitDirty'])
  for name,digest in source['scripts'].items():
   self.assertEqual(hashlib.sha256((E/'protocol'/name).read_bytes()).hexdigest(),digest,name)
 def test_all_manifest_raw_hashes(self):
  for name,item in read(B/'manifest.json')['files'].items():
   self.assertTrue((B/name).is_file(),name)
   self.assertEqual(hashlib.sha256((B/name).read_bytes()).hexdigest(),item['sha256'],name)
 def test_uncached_layout_and_read_samples(self):
  data=read(B/'reads.json');self.assertEqual([r['seatCount']for r in data],[5000,10000])
  for row in data:
   samples=row['layout'];self.assertEqual(len(samples),41)
   self.assertEqual({s['status']for s in samples},{200})
   self.assertEqual(len({s['sha256']for s in samples}),1)
   self.assertTrue(all(not any(k.lower()=='etag'for k in s['headers'])for s in samples))
   self.assertEqual(len(row['availability']['snapshots']),20)
   self.assertEqual(len(row['availability']['emptyDeltas']),20)
 def test_native_visibility_and_real_api(self):
  b=read(B/'browser.json');self.assertTrue(b['passed'])
  self.assertEqual(len(b['topology']),2)
  self.assertEqual(b['topology'][0]['windowId'],b['topology'][1]['windowId'])
  records=next(p['records']for p in b['timeline']if '/sessions/'in p['url'])
  changes=[r for r in records if r['type']=='visibilitychange']
  self.assertTrue(any(r['hidden'] and r['trusted']for r in changes))
  hidden=next(r['dateNow']for r in changes if r['hidden'])
  self.assertTrue(any(not r['hidden']and r['trusted']and r['dateNow']>hidden for r in changes))
  self.assertEqual(b['browser']['product'],b['environment']['product'])
  for r in b['requests']:
   self.assertEqual(r['status'],200);self.assertEqual(r['fixture'],'stage0-v2')
   self.assertGreaterEqual(r['endEpochMs'],r['startEpochMs'])
  # Baseline intentionally has no assertion that hidden requests or max-in-flight meet after goals.
 def test_k6_and_burst(self):
  m=read(B/'k6-summary.json')['metrics']
  self.assertGreaterEqual(m['http_reqs']['values']['count'],120)
  self.assertEqual(m['checks']['values']['fails'],0)
  self.assertEqual(m['http_req_failed']['values']['rate'],0)
  self.assertEqual(m['dropped_iterations']['values']['count'],0)
  rows=read(B/'burst.json')['rows']
  self.assertEqual(sum(r['status']==201 for r in rows),1)
  self.assertEqual(sum(r['code']=='SEAT_CONFLICT'for r in rows),7)
 def test_database_and_resource_collectors(self):
  v=read(B/'verifier.json');self.assertTrue(v['passed'])
  for checks in [v['phase17'],v['phase15And16']['phase15'],v['phase15And16']['phase16AndOriginal']['checks']]:
   self.assertTrue(checks);self.assertTrue(all(n==0 for n in checks.values()))
  self.assertEqual(v['phase15And16']['phase16AndOriginal']['checkedRedisSeats'],15000)
  r=read(B/'resource-samples.json');self.assertFalse(r['errors']);self.assertGreater(len(r['samples']),20)
 def test_diagnostics_are_excluded(self):
  self.assertTrue(read(E/'diagnostics/index.json')['excludedFromFormalBaseline'])
  self.assertFalse(any(name.startswith('diagnostics/') for name in read(B/'manifest.json')['files']))
if __name__=='__main__':unittest.main()
