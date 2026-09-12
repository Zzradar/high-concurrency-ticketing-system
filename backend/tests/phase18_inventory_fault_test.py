"""Real bounded PostgreSQL delay, inventory isolation and event cooldown; capability only."""
import concurrent.futures,hashlib,json,os,subprocess,time,unittest
from pathlib import Path
import phase18_admission_http_test as f
from phase18_traffic_http_test import metric
from auth_test_support import anonymous_request
class InventoryFault(unittest.TestCase):
 setUp=f.AdmissionHTTP.setUp
 policy=f.AdmissionHTTP.policy
 def test_inventory_timeout_rolls_back_and_cools_scheduler(self):
  config=Path(os.environ['PHASE18_FAULT_CONFIG']); original=config.read_bytes()
  self.assertEqual(os.environ['PHASE18_FAULT_API'],'phase18-policy-api')
  def restart():
   subprocess.run(['docker','restart',os.environ['PHASE18_FAULT_API']],capture_output=True,check=True)
   def healthy():
    try:return anonymous_request('/health')[0]==200
    except Exception:return False
   f.until(healthy,seconds=25)
  def restore():
   f.sql('DROP TRIGGER IF EXISTS phase18_inventory_delay ON checkout_sessions; DROP FUNCTION IF EXISTS phase18_inventory_delay();')
   config.write_bytes(original);restart()
  self.addCleanup(restore)
  values=json.loads(original);values['custom_config']['traffic_control']['bulkheads']['INVENTORY_WRITE']=1
  config.write_text(json.dumps(values),encoding='utf-8');restart()
  policy=self.policy('ENFORCED');self.u.request(self.path,method='POST')
  f.until(lambda:self.u.request(self.path)[1].get('state')=='ADMITTED')
  root='ticketing:admission:{evt:'+hashlib.sha256(self.e.encode()).hexdigest()+'}:'+policy['queueGeneration']+':'
  f.sql("CREATE FUNCTION phase18_inventory_delay() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.session_id='"+self.s+"' THEN PERFORM pg_sleep(7); END IF; RETURN NEW; END $$; CREATE TRIGGER phase18_inventory_delay BEFORE INSERT ON checkout_sessions FOR EACH ROW EXECUTE FUNCTION phase18_inventory_delay();")
  with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
   first=pool.submit(self.u.request,'/checkout-sessions',method='POST',body={'sessionId':self.s,'seatIds':[self.seats[0]['id']]})
   f.until(lambda:metric('ticketing_traffic_inflight','INVENTORY_WRITE')==1)
   started=time.monotonic();code,body,headers=self.u.request('/checkout-sessions',method='POST',body={'sessionId':self.s,'seatIds':[self.seats[1]['id']]})
   self.assertEqual(code,503,body);self.assertEqual(body['code'],'SYSTEM_OVERLOADED');self.assertEqual(body['resource'],'INVENTORY_WRITE');self.assertLess(time.monotonic()-started,2)
   self.assertEqual(self.u.request('/orders')[0],200)
   self.assertEqual(self.u.request('/checkout-sessions?recoverable=true&sessionId='+self.s)[0],200)
   f.until(lambda:f.redis('PTTL',root+'pause')>0)
   self.assertEqual(self.u.request(self.path,method='DELETE')[0],200)
   self.assertEqual(self.u.request(self.path,method='POST')[0],200)
   begin=time.monotonic()
   while time.monotonic()-begin<1:
    self.assertNotEqual(self.u.request(self.path)[1].get('state'),'ADMITTED');time.sleep(.15)
   code,body,_=first.result(timeout=15)
   self.assertEqual(code,500,body)
  f.until(lambda:metric('ticketing_traffic_inflight','INVENTORY_WRITE')==0)
  self.assertEqual(metric('ticketing_traffic_peak_inflight','INVENTORY_WRITE'),1)
  # Wait for server-side canceled transaction cleanup, not only the HTTP timeout.
  f.until(lambda:f.sql("SELECT count(*) FROM checkout_sessions WHERE session_id='"+self.s+"'")=='0')
  self.assertEqual(f.sql("SELECT count(*) FROM session_seats WHERE session_id='"+self.s+"' AND status='AVAILABLE'"),'2')
  f.until(lambda:self.u.request(self.path)[1].get('state')=='ADMITTED',seconds=20)
  print('inventory limit=1 peak=1 drained=0; second request=503; first database timeout=500; rollback=0 checkouts/2 available; cooldown blocks release then resumes; financial/recovery=200')
if __name__=='__main__':unittest.main(verbosity=2)
