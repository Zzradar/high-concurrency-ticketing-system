"""Run only against an isolated Phase18 API with a generated admission secret."""
import concurrent.futures,json,os,subprocess,threading,unittest
os.environ['TICKETING_BASE_URL']=os.environ['PHASE18_BASE_URL']
from auth_test_support import AuthenticatedClient,anonymous_request
PG=os.environ['PHASE18_POSTGRES_CONTAINER']
def sql(q):
 p=subprocess.run(['docker','exec','-i',PG,'psql','-U','postgres','-qAt','-v','ON_ERROR_STOP=1'],input=q,text=True,encoding='utf-8',capture_output=True)
 if p.returncode:raise AssertionError(p.stderr)
 return p.stdout.strip()
class PolicyHTTP(unittest.TestCase):
 def setUp(self):
  self.e=sql('SELECT id FROM events ORDER BY id LIMIT 1');self.path='/admin/events/'+self.e+'/admission-policy'
  sql('DELETE FROM admission_policy_audit;DELETE FROM event_admission_policies;')
  self.a=AuthenticatedClient('admin');self.a.login()
  self.body=dict(mode='OFF',prequeueSeconds=0,maxActiveUsers=10,admissionRatePerSecond=2,leaseSeconds=30,expectedPolicyVersion=0)
 def put(self,body=None):return self.a.request(self.path,method='PUT',body=body or self.body)
 def test_off_auth_csrf_strict_input_and_synthetic_policy(self):
  self.assertEqual(anonymous_request(self.path)[0],401)
  self.assertEqual(AuthenticatedClient().request(self.path)[0],403)
  status,p,headers=self.a.request(self.path);self.assertEqual(status,200);self.assertEqual(p['policyVersion'],0);self.assertEqual(p['mode'],'OFF');self.assertIsNone(p['maxActiveUsers'])
  self.assertEqual(self.a.request(self.path,method='PUT',body=self.body,csrf=False)[0],403)
  self.assertEqual(self.a.request(self.path,method='PUT',body=self.body,headers={'Origin':'https://invalid.example'})[0],403)
  for field in ['prequeueSeconds','maxActiveUsers','admissionRatePerSecond','leaseSeconds','expectedPolicyVersion']:
   for bad in [True,[],{},None,'1',1.0,-1,9007199254740992]:
    with self.subTest(field=field,value=bad):self.assertEqual(self.put({**self.body,field:bad})[0],400)
  self.assertEqual(sql('SELECT count(*) FROM admission_policy_audit'),'0')
  self.assertEqual(self.put()[0],200)
  self.assertEqual(self.put()[0],409)
  self.assertEqual(self.a.request('/admin/events/missing/admission-policy')[0],404)
 def test_missing_secret_rejects_activation_and_readiness(self):
  import urllib.request
  from urllib.error import HTTPError
  other=os.environ['PHASE18_NO_SECRET_BASE_URL']
  def get_health():
   try:r=urllib.request.urlopen(other+'/health',timeout=5)
   except HTTPError as e:r=e
   with r:return r.status,json.loads(r.read())
  self.assertEqual(get_health()[0],200)
  old=os.environ['TICKETING_BASE_URL'];os.environ['TICKETING_BASE_URL']=other
  try:
   # AuthenticatedClient resolves its module BASE_URL, so explicitly patch that module for this instance.
   import auth_test_support as support
   previous=support.BASE_URL;support.BASE_URL=other
   try:
    c=AuthenticatedClient('admin');c.login()
    self.assertEqual(c.request(self.path,method='PUT',body={**self.body,'mode':'OBSERVE'})[0],503)
   finally:support.BASE_URL=previous
  finally:os.environ['TICKETING_BASE_URL']=old
  self.assertEqual(sql('SELECT count(*) FROM admission_policy_audit'),'0')
  self.assertEqual(self.put({**self.body,'mode':'OBSERVE'})[0],200)
  self.assertEqual(get_health(),(503,{'status':'degraded','code':'ADMISSION_SECRET_UNAVAILABLE'}))
  self.assertEqual(self.put({**self.body,'expectedPolicyVersion':1})[0],200)
  self.assertEqual(get_health()[0],200)
 def test_concurrent_create_and_update_one_winner_one_audit(self):
  clients=[AuthenticatedClient('admin') for _ in range(8)]
  for c in clients:c.login()
  for expected in [0,1]:
   barrier=threading.Barrier(8)
   def call(i):
    barrier.wait(timeout=10)
    return clients[i].request(self.path,method='PUT',body={**self.body,'expectedPolicyVersion':expected})[0]
   with concurrent.futures.ThreadPoolExecutor(8) as pool:results=list(pool.map(call,range(8)))
   self.assertEqual(results.count(200),1);self.assertEqual(results.count(409),7)
  self.assertEqual(sql('SELECT count(*) FROM admission_policy_audit'),'2')
  self.assertEqual(sql("SELECT count(*) FROM admission_policy_audit WHERE (new_policy->>'policyVersion')::bigint<>new_version OR (old_policy->>'policyVersion')::bigint<>old_version"),'0')
 def test_shadow_cannot_be_promoted_through_pause(self):
  generations=[]
  for version,mode in enumerate(['OBSERVE','PAUSED','ENFORCED']):
   status,p,_=self.put({**self.body,'expectedPolicyVersion':version,'mode':mode})
   self.assertEqual(status,200)
   generations.append(p['queueGeneration'])
  self.assertNotEqual(generations[0],generations[1], 'PAUSED must not retain an OBSERVE shadow generation')
  self.assertEqual(generations[1],generations[2], 'Resuming PAUSED must preserve the real queue generation')
 def test_generation_transitions_and_normalized_audit(self):
  previous=None
  for version,mode in enumerate(['OBSERVE','ENFORCED','PAUSED','ENFORCED','OFF','ENFORCED']):
   status,p,_=self.put({**self.body,'expectedPolicyVersion':version,'mode':mode})
   self.assertEqual(status,200);self.assertEqual(p['policyVersion'],version+1)
   if version in [1,5]:self.assertNotEqual(p['queueGeneration'],previous)
   if version in [2,3,4]:self.assertEqual(p['queueGeneration'],previous)
   previous=p['queueGeneration']
  self.assertEqual(sql('SELECT count(*) FROM admission_policy_audit'),'6')
  self.assertEqual(sql("SELECT count(*) FROM admission_policy_audit WHERE old_policy ? 'expectedPolicyVersion' OR new_policy ? 'expectedPolicyVersion'"),'0')
if __name__=='__main__':unittest.main(verbosity=2)
