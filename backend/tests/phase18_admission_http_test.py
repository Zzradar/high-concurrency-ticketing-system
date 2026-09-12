"""Real queue/stock isolation gates against the explicit Phase18 fixture only."""
import hashlib,json,os,subprocess,time,unittest,uuid
from datetime import datetime,timedelta,timezone
os.environ['TICKETING_BASE_URL']=os.environ['PHASE18_BASE_URL']
from auth_test_support import AuthenticatedClient,anonymous_request
PG=os.environ['PHASE18_POSTGRES_CONTAINER'];REDIS=os.environ['PHASE18_REDIS_CONTAINER']
def sql(q):
 p=subprocess.run(['docker','exec','-i',PG,'psql','-U','postgres','-qAt','-v','ON_ERROR_STOP=1'],input=q,text=True,encoding='utf-8',capture_output=True)
 if p.returncode:raise AssertionError(p.stderr)
 return p.stdout.strip()
def redis(*args):
 p=subprocess.run(['docker','exec',REDIS,'redis-cli','--json',*map(str,args)],text=True,encoding='utf-8',capture_output=True)
 if p.returncode:raise AssertionError(p.stderr)
 return json.loads(p.stdout)
def instant(hours):return (datetime.now(timezone.utc)+timedelta(hours=hours)).isoformat().replace('+00:00','Z')
def until(fn,seconds=15):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  value=fn()
  if value:return value
  time.sleep(.1)
 raise AssertionError('Phase18 isolated convergence timeout')
class AdmissionHTTP(unittest.TestCase):
 def setUp(self):
  self.a=AuthenticatedClient('admin');self.a.login();self.u=AuthenticatedClient();self.u.login()
  def admin(path,body,status=200):
   code,data,_=self.a.request(path,method='POST',body=body);self.assertEqual(code,status,data);return data
  venue=admin('/admin/venues',{'name':'Admission '+uuid.uuid4().hex,'city':'Shanghai','zones':[{'code':'A','name':'A','rows':[{'label':'A','seatCount':2}]}]},201)
  e=admin('/admin/events',{'name':'Admission gate','description':'','category':'Test','coverUrl':'/images/concert-cover.png','venueId':venue['id'],'salesStartsAt':instant(-1),'salesEndsAt':instant(3)},201);self.e=e['id']
  e=admin('/admin/events/'+self.e+'/sessions',{'hallName':'Hall','startTime':instant(2),'gateTime':instant(1)},201);self.s=e['savedSessionId']
  self.assertEqual(self.a.request('/admin/events/'+self.e+'/sessions/'+self.s+'/prices',method='PUT',body={'prices':[{'zoneId':venue['zones'][0]['id'],'price':100}]})[0],200)
  admin('/admin/events/'+self.e+'/publish',None)
  self.seats=anonymous_request('/sessions/'+self.s+'/seat-layout')[1]['seats'];self.path='/events/'+self.e+'/admission';self.version=0
  until(lambda:self.u.request(self.path)[0]==200)
 def policy(self,mode):
  status,p,_=self.a.request('/admin/events/'+self.e+'/admission-policy',method='PUT',body={'mode':mode,'prequeueSeconds':0,'maxActiveUsers':1,'admissionRatePerSecond':10,'leaseSeconds':30,'expectedPolicyVersion':self.version})
  self.assertEqual(status,200,p);self.version=p['policyVersion']
  until(lambda:anonymous_request('/health')[0]==200)
  return p
 def current(self):return self.u.request(self.path)[1]
 def test_shadow_cannot_access_formal_status_availability_or_new_stock(self):
  shadow=self.policy('OBSERVE')
  self.assertEqual(self.u.request(self.path,method='POST')[1]['state'],'NOT_REQUIRED')
  root='ticketing:admission:{evt:'+hashlib.sha256(self.e.encode()).hexdigest()+'}:'
  until(lambda:redis('ZCARD',root+shadow['queueGeneration']+':active')==1)
  formal=self.policy('PAUSED');self.assertNotEqual(shadow['queueGeneration'],formal['queueGeneration'])
  self.assertEqual(self.u.request(self.path+'?queueGeneration='+shadow['queueGeneration'])[1]['state'],'RESET_REQUIRED')
  self.assertEqual(self.u.request('/sessions/'+self.s+'/seat-availability?zone=A')[1]['code'],'ADMISSION_REQUIRED')
  self.assertEqual(self.u.request('/sessions/'+self.s+'/seats')[1]['code'],'ADMISSION_REQUIRED')
  seat=self.seats[0]['id']
  body={'sessionId':self.s,'seatIds':[seat]}
  self.assertEqual(self.u.request('/reservations',method='POST',body=body,headers={'Idempotency-Key':'shadow-'+uuid.uuid4().hex})[1]['code'],'ADMISSION_REQUIRED')
  self.assertEqual(self.u.request('/checkout-sessions',method='POST',body=body)[1]['code'],'ADMISSION_REQUIRED')
  self.assertEqual(anonymous_request('/sessions/'+self.s+'/seat-layout')[0],200)
  self.assertEqual(self.u.request(self.path,method='POST',body={'userId':'another'})[0],400)
  self.assertEqual(self.u.request(self.path,method='POST',csrf=False)[0],403)
  joined=self.u.request(self.path,method='POST')[1];self.assertEqual(joined['state'],'PAUSED')
  resumed=self.policy('ENFORCED');self.assertEqual(resumed['queueGeneration'],formal['queueGeneration'])
  until(lambda:self.current().get('state')=='ADMITTED')
  self.assertEqual(self.u.request('/sessions/'+self.s+'/seat-availability?zone=A')[0],200)
  self.assertEqual(self.u.request('/reservations',method='POST',body=body,headers={'Idempotency-Key':'formal-'+uuid.uuid4().hex})[0],201)
  self.assertEqual(sql("SELECT count(*) FROM session_seats WHERE session_id='"+self.s+"' AND status='AVAILABLE'"),'1')
 def test_runtime_loss_rotates_generation_without_reusing_qualification(self):
  p=self.policy('ENFORCED');self.u.request(self.path,method='POST');until(lambda:self.current().get('state')=='ADMITTED')
  root='ticketing:admission:{evt:'+hashlib.sha256(self.e.encode()).hexdigest()+'}:'
  # Delete only this test event's admission data, never inventory/auth/other stages.
  redis('DEL',root+'runtime',*[root+p['queueGeneration']+':'+suffix for suffix in ['prequeue','waiting','presence','active','heartbeat','sequence','release','pause']])
  def changed():
   status,current,_=self.a.request('/admin/events/'+self.e+'/admission-policy')
   return current if status==200 and current['queueGeneration']!=p['queueGeneration'] else None
  current=until(changed);self.version=current['policyVersion'];self.assertEqual(self.version,p['policyVersion']+1)
  until(lambda:anonymous_request('/health')[0]==200)
  def reset_visible():
   status,body,_=self.u.request(self.path+'?queueGeneration='+p['queueGeneration'])
   self.assertNotEqual(body.get('state'),'ADMITTED',body)
   if status==503:self.assertEqual(body.get('code'),'ADMISSION_UNAVAILABLE',body);return False
   self.assertEqual(status,200,body)
   return body.get('state')=='RESET_REQUIRED'
  until(reset_visible)
  self.assertEqual(self.current()['state'],'NOT_JOINED')
  self.assertEqual(sql("SELECT count(*) FROM admission_policy_audit WHERE event_id='"+self.e+"' AND actor_kind='SYSTEM' AND action='RESET_GENERATION' AND administrator_id IS NULL"),'1')
 def test_redis_outage_preserves_replay_and_off_while_new_formal_work_fails_closed(self):
  p=self.policy('ENFORCED');self.u.request(self.path,method='POST');until(lambda:self.current().get('state')=='ADMITTED')
  body={'sessionId':self.s,'seatIds':[self.seats[0]['id']]};key='restore-'+uuid.uuid4().hex
  self.assertEqual(self.u.request('/reservations',method='POST',body=body,headers={'Idempotency-Key':key})[0],201)
  subprocess.run(['docker','stop',REDIS],check=True,capture_output=True)
  try:
   self.assertEqual(self.u.request('/reservations',method='POST',body=body,headers={'Idempotency-Key':key})[0],200)
   status,error,_=self.u.request('/reservations',method='POST',body={'sessionId':self.s,'seatIds':[self.seats[1]['id']]},headers={'Idempotency-Key':'new-'+uuid.uuid4().hex})
   self.assertEqual(status,503);self.assertEqual(error['code'],'ADMISSION_UNAVAILABLE')
   self.policy('OFF')
   self.assertEqual(self.u.request('/reservations',method='POST',body={'sessionId':self.s,'seatIds':[self.seats[1]['id']]},headers={'Idempotency-Key':'off-'+uuid.uuid4().hex})[0],201)
   self.assertEqual(anonymous_request('/sessions/'+self.s+'/seat-layout')[0],200)
  finally:
   subprocess.run(['docker','start',REDIS],check=True,capture_output=True)
   until(lambda:anonymous_request('/health')[0]==200)
 def test_stable_status_has_zero_auth_sql_and_logout_revokes_cache(self):
  self.policy('ENFORCED');self.u.request(self.path,method='POST');until(lambda:self.current().get('state')=='ADMITTED')
  for _ in range(3):self.current()
  query="SELECT coalesce(sum(calls),0)::bigint FROM pg_stat_statements WHERE query ILIKE '%user_sessions%' AND query NOT ILIKE '%pg_stat_statements%'"
  before=int(sql(query))
  for _ in range(20):
   time.sleep(.11)  # Respect the separate account status token refill.
   self.assertEqual(self.current()['state'],'ADMITTED')
  self.assertEqual(int(sql(query))-before,0,'Stable status must not read or touch user_sessions')
  token=self.u.cookie('ticketing_session');cache_key='ticketing:auth-session:'+hashlib.sha256(token.encode()).hexdigest()
  # Only inspect existence. Never print/cache fixture tokens in evidence.
  self.assertEqual(redis('EXISTS',cache_key),1)
  self.assertEqual(self.u.request('/auth/logout',method='POST')[0],200)
  until(lambda:redis('EXISTS',cache_key)==0)
  self.assertEqual(self.u.request(self.path)[0],401)
 def test_status_is_read_only_and_strict_auth_still_protects_inventory(self):
  self.policy('ENFORCED');self.assertEqual(self.current()['state'],'NOT_JOINED')
  self.assertEqual(self.current()['state'],'NOT_JOINED')
  self.u.request(self.path,method='POST');until(lambda:self.current().get('state')=='ADMITTED')
  p=self.a.request('/admin/events/'+self.e+'/admission-policy')[1]
  key='ticketing:admission:{evt:'+hashlib.sha256(self.e.encode()).hexdigest()+'}:'+p['queueGeneration']+':active'
  before=redis('ZRANGE',key,0,-1,'WITHSCORES');ttl=redis('PEXPIRETIME',key)
  for _ in range(5):self.assertEqual(self.current()['state'],'ADMITTED')
  self.assertEqual(redis('ZRANGE',key,0,-1,'WITHSCORES'),before)
  # The scheduler may refresh overall key TTL, but GET cannot extend the user's lease.
  self.assertGreater(ttl,0)
  sql("UPDATE app_users SET status='DISABLED' WHERE username='demo'")
  try:
   self.assertEqual(self.u.request('/reservations',method='POST',body={'sessionId':self.s,'seatIds':[self.seats[0]['id']]},headers={'Idempotency-Key':'disabled-'+uuid.uuid4().hex})[0],401)
  finally:sql("UPDATE app_users SET status='ACTIVE' WHERE username='demo'")
  self.assertEqual(self.u.request(self.path,method='DELETE')[0],200)
  self.assertEqual(self.current()['state'],'NOT_JOINED')
if __name__=='__main__':unittest.main(verbosity=2)
