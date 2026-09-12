"""Only finite public admission metadata; no queue identity or capacity disclosure."""
import unittest
import phase18_admission_http_test as fixture
class PublicAdmissionContract(unittest.TestCase):
 setUp=fixture.AdmissionHTTP.setUp
 policy=fixture.AdmissionHTTP.policy
 def test_public_summaries_are_minimal_and_observe_is_not_required(self):
  for mode in ['OFF','OBSERVE','PAUSED','ENFORCED']:
   self.policy(mode)
   for path in ['/events/'+self.e,'/sessions/'+self.s]:
    status,body,headers=self.u.request(path);self.assertEqual(status,200)
    summary=body['admission'];self.assertEqual(set(summary),{'required','state','prequeueStartsAt'})
    self.assertIs(type(summary['required']),bool)
    self.assertEqual(summary['required'],mode in ['PAUSED','ENFORCED'])
    self.assertEqual(summary['state'],'NOT_REQUIRED' if mode in ['OFF','OBSERVE'] else 'PAUSED' if mode=='PAUSED' else 'OPEN')
    if mode in ['OFF','OBSERVE']:self.assertIsNone(summary['prequeueStartsAt'])
    else:self.assertRegex(summary['prequeueStartsAt'],r'^\d{4}-\d{2}-\d{2}T.*Z$')
    self.assertIn('no-store',headers.get('Cache-Control',headers.get('cache-control','')))
   events=self.u.request('/events')[1];sessions=self.u.request('/events/'+self.e+'/sessions')[1]
   self.assertEqual(next(e for e in events if e['id']==self.e)['admission']['required'],mode in ['PAUSED','ENFORCED'])
   self.assertEqual(next(s for s in sessions if s['id']==self.s)['admission']['required'],mode in ['PAUSED','ENFORCED'])
 def test_guard_conflict_carries_queue_state_without_authorizing_stock(self):
  policy=self.policy('PAUSED')
  status,body,_=self.u.request('/sessions/'+self.s+'/seat-availability?zone=A')
  self.assertEqual(status,409);self.assertEqual(body['code'],'ADMISSION_REQUIRED')
  self.assertEqual(body['state'],'NOT_JOINED');self.assertEqual(body['queueGeneration'],policy['queueGeneration'])
  self.assertIs(type(body['pollAfterMs']),int);self.assertGreaterEqual(body['pollAfterMs'],500)
  self.assertIsNone(body['admittedUntil'])
if __name__=='__main__':unittest.main(verbosity=2)
