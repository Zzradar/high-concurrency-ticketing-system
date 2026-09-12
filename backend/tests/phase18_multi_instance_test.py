"""Two real API processes and schedulers; same configured HMAC, PostgreSQL and Redis."""
import os,subprocess,time,unittest,uuid,hashlib,concurrent.futures,urllib.request
os.environ['PHASE18_BASE_URL']=os.environ['TICKETING_BASE_URL']
project=os.environ.get('COMPOSE_PROJECT_NAME','phase18-financial')
assert project.startswith('phase18-')
os.environ['PHASE18_POSTGRES_CONTAINER']=project+'-postgres-1'
os.environ['PHASE18_REDIS_CONTAINER']=project+'-redis-1'
import phase18_admission_http_test as f
from auth_test_support import AuthenticatedClient,test_user_values,username_for_user
# Existing assertions use postgres superuser transport; this separate Compose fixture uses ticketing.
def sql(statement):
 r=subprocess.run(['docker','compose','exec','-T','postgres','psql','-U','ticketing','-d','ticketing','-qAt','-v','ON_ERROR_STOP=1'],input=statement,capture_output=True,text=True,encoding='utf-8')
 if r.returncode:raise AssertionError(r.stderr)
 return r.stdout.strip()
f.sql=sql
class PeerHandler(urllib.request.BaseHandler):
 handler_order=100
 def http_request(self,request):
  request.full_url=request.full_url.replace('127.0.0.1:18186','127.0.0.1:18188');return request
class MultiInstance(unittest.TestCase):
 def test_duplicate_join_and_release_are_atomic_across_two_apis(self):
  name='phase18-financial-admission-peer-'+uuid.uuid4().hex[:8]
  r=subprocess.run(['docker','compose','run','-d','--no-deps','--name',name,'-p','127.0.0.1:18188:8080','backend'],capture_output=True,text=True)
  self.assertEqual(r.returncode,0,r.stderr)
  self.addCleanup(lambda:subprocess.run(['docker','stop',name],check=True,capture_output=True))
  def healthy():
   try:return urllib.request.urlopen('http://127.0.0.1:18188/health',timeout=1).status==200
   except Exception:return False
  f.until(healthy,seconds=20)
  case=f.AdmissionHTTP();case.setUp();policy=case.policy('PAUSED')
  peer=AuthenticatedClient();peer.opener.add_handler(PeerHandler());peer.login()
  f.until(lambda:peer.request(case.path)[1].get('queueGeneration')==policy['queueGeneration'])
  with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
   responses=list(pool.map(lambda i:(case.u if i%2 else peer).request(case.path,method='POST'),range(16)))
  self.assertTrue(all(r[0]==200 for r in responses),[r[0] for r in responses])
  root='ticketing:admission:{evt:'+hashlib.sha256(case.e.encode()).hexdigest()+'}:'+policy['queueGeneration']+':'
  self.assertEqual(sum(f.redis('ZCARD',root+s) for s in ['prequeue','waiting','active']),1)
  ids=['p18-peer-'+uuid.uuid4().hex for _ in range(8)]
  sql('INSERT INTO app_users(id,display_name,username,password_hash,status) VALUES '+test_user_values(ids))
  clients=[]
  for i,user in enumerate(ids):
   c=AuthenticatedClient(username_for_user(user))
   if i%2:c.opener.add_handler(PeerHandler())
   c.login();clients.append(c)
  for c in clients:self.assertEqual(c.request(case.path,method='POST')[0],200)
  case.policy('ENFORCED');f.until(lambda:f.redis('ZCARD',root+'active')==1)
  peaks=[]
  for turn in range(5):
   peaks.append(f.redis('ZCARD',root+'active'));self.assertLessEqual(peaks[-1],1)
   # Redis release may precede the peer's policy refresh. Wait for an actual
   # ADMITTED identity; never silently count a loop without a successful leave.
   def admitted():
    return next((c for c in [case.u,*clients] if c.request(case.path)[1].get('state')=='ADMITTED'),None)
   leaving=f.until(admitted)
   self.assertEqual(leaving.request(case.path,method='DELETE')[0],200)
   f.until(lambda:f.redis('ZCARD',root+'active')==1)
  self.assertEqual(sum(f.redis('ZCARD',root+s) for s in ['prequeue','waiting','active']),4)
  print('two API instances, two schedulers, PG pool budget=8; duplicate joins=16 -> one position; nine unique positions minus five leaves=4; maxActiveUsers=1 observed peak='+str(max(peaks)))
if __name__=='__main__':unittest.main(verbosity=2)
