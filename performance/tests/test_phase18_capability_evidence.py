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
if __name__=='__main__':unittest.main()
