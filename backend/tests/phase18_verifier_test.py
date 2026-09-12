"""Negative audit mutations roll back; production constraints and gates stay intact."""
import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'performance/verification'))
import phase18_verify as v
import phase18_admission_http_test as f
class Verifier(unittest.TestCase):
 def test_real_namespace_audit_and_rollback_negative(self):
  case=f.AdmissionHTTP();case.setUp();case.policy('OBSERVE');case.policy('PAUSED')
  f.until(lambda:v.verify()['passed'])
  statement="BEGIN;UPDATE admission_policy_audit SET new_policy=jsonb_set(new_policy,'{queueGeneration}',to_jsonb(repeat('0',32))) WHERE event_id='"+case.e+"' AND new_version=2;"+v.QUERIES['policyAuditMismatch']+';ROLLBACK;'
  self.assertGreater(int(f.sql(statement).splitlines()[-1]),0)
  self.assertTrue(v.verify()['passed'])
if __name__=='__main__':unittest.main(verbosity=2)
