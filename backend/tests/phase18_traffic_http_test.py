"""Real Redis rates and isolated API resource saturation; never formal OFF A/B data."""
import concurrent.futures,hashlib,os,re,subprocess,time,unittest,urllib.request
import phase18_admission_http_test as fixture
from auth_test_support import anonymous_request

def metric(name,resource):
 with urllib.request.urlopen(os.environ['PHASE18_BASE_URL']+'/metrics',timeout=5) as r:text=r.read().decode()
 m=re.search(r'^'+name+r'\{request_class="'+resource+r'"\} ([0-9.eE+-]+)',text,re.M)
 return float(m.group(1)) if m else 0
class TrafficHTTP(unittest.TestCase):
 setUp=fixture.AdmissionHTTP.setUp
 policy=fixture.AdmissionHTTP.policy
 def test_enforced_429_retry_and_observe_never_intercepts(self):
  for mode in ['ENFORCED','OBSERVE']:
   p=self.policy(mode)
   root='ticketing:admission:{evt:'+hashlib.sha256(self.e.encode()).hexdigest()+'}:'+p['queueGeneration']+':rate:ADMISSION_STATUS:'
   # Only this newly-created event's finite event bucket. Real TIME and real Lua still run.
   fixture.redis('HSET',root+'event','tokens',0,'time',int(time.time()*1000)+5000)
   status,body,headers=self.u.request(self.path)
   if mode=='ENFORCED':
    self.assertEqual(status,429,body);self.assertEqual(body['code'],'RATE_LIMITED')
    self.assertEqual(body['scope'],'EVENT');self.assertIs(type(body['retryAfterMs']),int)
    self.assertGreaterEqual(int(headers.get('Retry-After',headers.get('retry-after','0'))),1)
    self.assertIn('no-store',headers.get('Cache-Control',headers.get('cache-control','')))
   else:self.assertEqual(status,200,body);self.assertEqual(body['state'],'NOT_REQUIRED')
 def test_off_read_saturation_is_bounded_and_releases_permits(self):
  self.policy('OFF')
  # Hold only this fixture's relation for a short bounded interval. No other phase resources.
  blocker=subprocess.Popen(['docker','exec','-i',fixture.PG,'psql','-U','postgres','-qAt','-v','ON_ERROR_STOP=1'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  self.addCleanup(lambda: (blocker.wait(timeout=10),blocker.stdout.close(),blocker.stderr.close()))
  blocker.stdin.write("BEGIN; LOCK TABLE session_seats IN ACCESS EXCLUSIVE MODE; SELECT pg_sleep(3); ROLLBACK;\n");blocker.stdin.close()
  fixture.until(lambda:fixture.sql("SELECT count(*) FROM pg_stat_activity WHERE query LIKE 'SELECT pg_sleep(3)%' AND state='active'")=='1')
  samples=[]
  with concurrent.futures.ThreadPoolExecutor(max_workers=40) as pool:
   reads=[pool.submit(anonymous_request,'/sessions/'+self.s+'/seats') for _ in range(32)]
   fixture.until(lambda:metric('ticketing_traffic_inflight','AVAILABILITY')==16,seconds=2)
   samples.append(metric('ticketing_traffic_inflight','AVAILABILITY'))
   financial=pool.submit(self.u.request,'/orders')
   recovery=pool.submit(self.u.request,'/checkout-sessions?recoverable=true&sessionId='+self.s)
   results=[f.result(timeout=15) for f in reads]
   self.assertEqual(financial.result(timeout=15)[0],200)
   self.assertEqual(recovery.result(timeout=15)[0],200)
  blocker.wait(timeout=10);self.assertEqual(blocker.returncode,0)
  rejected=[r for r in results if r[0]==503]
  self.assertGreater(len(rejected),0)
  for _,body,headers in rejected:
   self.assertEqual(body['code'],'SYSTEM_OVERLOADED',body);self.assertEqual(body['resource'],'AVAILABILITY')
   self.assertGreater(body['retryAfterMs'],0)
  self.assertTrue(all(status in [200,503] for status,_,_ in results),[x[0] for x in results])
  fixture.until(lambda:metric('ticketing_traffic_inflight','AVAILABILITY')==0)
  self.assertEqual(metric('ticketing_traffic_peak_inflight','AVAILABILITY'),16)
  for _ in range(20):self.assertEqual(anonymous_request('/sessions/'+self.s+'/seats')[0],200)
  observed=subprocess.run(['docker','exec','phase18-policy-api','cat','/proc/1/status'],capture_output=True,text=True,check=True).stdout
  values={k:int(re.search(r'^'+k+r':\s+(\d+)',observed,re.M).group(1)) for k in ['VmHWM','VmRSS','Threads']}
  self.assertLess(values['VmHWM'],1024*1024);self.assertLess(values['Threads'],256)
  print('Isolated API process sample (KiB, threads): '+str(values))
  print('OFF saturation: requests=32, rejected='+str(len(rejected))+', availability peak=16, drained=0; financial/recovery=200')
if __name__=='__main__':unittest.main(verbosity=2)
