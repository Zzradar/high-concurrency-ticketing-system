"""Historical capability evidence binds to its recorded source commit, not future SUT edits."""
import hashlib,json,subprocess,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
class CapabilityEvidence(unittest.TestCase):
 def test_waiting_room_source_and_raw_logs(self):
  directory=ROOT/'performance/experiments/phase18-admission-overload/capabilities/waiting-room'
  m=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
  self.assertEqual(m['status'],'CAPABILITY_BATCH_PASS_NOT_FINAL_DELIVERY')
  for name,digest in m['files'].items():
   raw=subprocess.check_output(['git','cat-file','blob',m['sourceCommit']+':'+name],cwd=ROOT)
   self.assertEqual(hashlib.sha256(raw).hexdigest(),digest,name)
  for name,digest in m['logs'].items():self.assertEqual(hashlib.sha256((directory/name).read_bytes()).hexdigest(),digest,name)
 def test_layout_revision_source_and_evidence(self):
  directory=ROOT/'performance/experiments/phase18-admission-overload/capabilities/layout-revision'
  m=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
  for name,digest in m['productionGitBlobSha256'].items():
   raw=subprocess.check_output(['git','show',m['productionSourceCommit']+':'+name],cwd=ROOT)
   self.assertEqual(hashlib.sha256(raw).hexdigest(),digest,name)
  for name,digest in m['files'].items():
   self.assertEqual(hashlib.sha256((directory/name).read_bytes()).hexdigest(),digest,name)
  evidence=json.loads((directory/'independent-layout.json').read_text())
  self.assertNotEqual(evidence['before']['sha256'],evidence['afterUnconditional']['sha256'])
  self.assertEqual(evidence['afterConditional']['status'],200)
  status=json.loads((directory.parents[1]/'AFTER_STATUS.json').read_text())
  self.assertEqual(status['after']['status'],'SUPERSEDED_INVALIDATED_BY_ETAG_DEFECT')
if __name__=='__main__':unittest.main()
