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
  # This test resets PostgreSQL policy versions between cases. Retire exactly those
  # fixture Redis namespaces too, otherwise the monotonic version fence correctly
  # rejects the artificial lower versions left by the SQL-only reset.
  import hashlib
  redis_container=os.environ['PHASE18_REDIS_CONTAINER'];assert redis_container.startswith('phase18-')
  for event,generation in (line.split('|') for line in sql('SELECT event_id,queue_generation FROM event_admission_policies').splitlines()):
   root='ticketing:admission:{evt:'+hashlib.sha256(event.encode()).hexdigest()+'}:'
   keys=[root+'runtime']+[root+generation+':'+suffix for suffix in ['prequeue','waiting','presence','active','heartbeat','sequence','release','pause']]
   result=subprocess.run(['docker','exec',redis_container,'redis-cli','DEL',*keys],capture_output=True,text=True)
   self.assertEqual(result.returncode,0,result.stderr)
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
    return clients[i].request(self.path,method='PUT',body={**self.body,'expectedPolicyVersion':expected,'mode':'OBSERVE' if expected==0 else 'ENFORCED'})
   with concurrent.futures.ThreadPoolExecutor(8) as pool:results=list(pool.map(call,range(8)))
   self.assertEqual(sum(r[0]==200 for r in results),1);self.assertEqual(sum(r[0]==409 for r in results),7)
   winner=next(r[1] for r in results if r[0]==200)
   self.assertEqual(self.a.request(self.path)[1],winner)
   self.assertEqual(sql('SELECT count(*) FROM admission_policy_audit'),str(expected+1))
   self.assertEqual(sql("SELECT new_policy->>'queueGeneration' FROM admission_policy_audit ORDER BY new_version DESC LIMIT 1"),winner['queueGeneration'])
  self.assertEqual(sql('SELECT count(*) FROM admission_policy_audit'),'2')
  self.assertEqual(sql("SELECT count(*) FROM admission_policy_audit WHERE (new_policy->>'policyVersion')::bigint<>new_version OR (old_policy->>'policyVersion')::bigint<>old_version"),'0')
 def test_all_namespace_transitions_and_off_reenable(self):
  modes={'OFF':'NONE','OBSERVE':'SHADOW','PAUSED':'FORMAL','ENFORCED':'FORMAL'}
  version=0
  for source,old_space in modes.items():
   for target,new_space in modes.items():
    with self.subTest(source=source,target=target):
     status,before,_=self.put({**self.body,'mode':source,'expectedPolicyVersion':version});self.assertEqual(status,200);version+=1
     status,after,_=self.put({**self.body,'mode':target,'expectedPolicyVersion':version,'maxActiveUsers':11});self.assertEqual(status,200);version+=1
     self.assertEqual(after['policyVersion'],version)
     self.assertEqual(before['queueGeneration']!=after['queueGeneration'],new_space!='NONE' and new_space!=old_space)
     committed=self.a.request(self.path)[1];self.assertEqual(committed,after)
     self.assertEqual(self.put({**self.body,'mode':'OBSERVE','expectedPolicyVersion':version-1})[0],409)
     self.assertEqual(self.a.request(self.path)[1],after)
  status,formal,_=self.put({**self.body,'mode':'ENFORCED','expectedPolicyVersion':version});self.assertEqual(status,200);version+=1
  self.assertEqual(self.put({**self.body,'mode':'OFF','expectedPolicyVersion':version})[0],200);version+=1
  status,reopened,_=self.put({**self.body,'mode':'ENFORCED','expectedPolicyVersion':version});self.assertEqual(status,200);version+=1
  self.assertNotEqual(formal['queueGeneration'],reopened['queueGeneration'])
  self.assertEqual(int(sql('SELECT count(*) FROM admission_policy_audit')),version)
 def test_transaction_and_audit_failures_rollback_generation(self):
  self.assertEqual(self.put({**self.body,'mode':'OBSERVE'})[0],200)
  before=self.a.request(self.path)[1]
  for table in ['event_admission_policies','admission_policy_audit']:
   with self.subTest(table=table):
    sql("CREATE FUNCTION phase18_reject_write() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'injected policy gate failure'; END $$; CREATE TRIGGER phase18_reject_write BEFORE INSERT OR UPDATE ON "+table+" FOR EACH ROW EXECUTE FUNCTION phase18_reject_write();")
    try:
     self.assertEqual(self.put({**self.body,'mode':'ENFORCED','expectedPolicyVersion':1})[0],500)
     self.assertEqual(self.a.request(self.path)[1],before)
     self.assertEqual(sql('SELECT count(*) FROM admission_policy_audit'),'1')
    finally:sql('DROP TRIGGER phase18_reject_write ON '+table+'; DROP FUNCTION phase18_reject_write();')
  status,after,_=self.put({**self.body,'mode':'ENFORCED','expectedPolicyVersion':1});self.assertEqual(status,200)
  self.assertNotEqual(before['queueGeneration'],after['queueGeneration']);self.assertEqual(after['policyVersion'],2)
  self.assertEqual(sql('SELECT count(*) FROM admission_policy_audit'),'2')
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
