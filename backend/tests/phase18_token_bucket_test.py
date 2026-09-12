"""Real Redis atomic dual-bucket tests with server-clock bounds."""
import concurrent.futures,os,subprocess,time,unittest,uuid
from pathlib import Path
from phase18_waiting_room_test import command,REDIS
def setUpModule():subprocess.run(['docker','cp',str(Path(__file__).resolve().parents[1]/'src/admission/token_bucket.lua'),REDIS+':/tmp/phase18-token.lua'],check=True,capture_output=True)
class TokenBucket(unittest.TestCase):
 def setUp(self):self.prefix='p18:bucket:{'+uuid.uuid4().hex+'}:'
 def call(self,user='u',ac=10,ar=1,ec=5,er=1,cost=1):return command('--eval','/tmp/phase18-token.lua',self.prefix+user,self.prefix+'event',',',ac,ar,ec,er,cost)
 def test_boundaries_retry_and_no_partial_charge(self):
  self.assertEqual(self.call(ac=1,ec=1)[0],'ALLOWED')
  result=self.call(ac=1,ec=1);self.assertEqual(result[0],'RATE_LIMITED');self.assertEqual(result[1],'BOTH');self.assertGreater(int(result[2]),0);self.assertLessEqual(int(result[2]),1000)
  before=command('HGET',self.prefix+'u','tokens');self.assertEqual(self.call(cost=0),['INVALID']);self.assertEqual(command('HGET',self.prefix+'u','tokens'),before)
  # Establish an empty event bucket explicitly; Docker command latency may legitimately refill it.
  clock=command('TIME');now=int(clock[0])*1000+int(clock[1])//1000
  command('HSET',self.prefix+'event','tokens',0,'time',now+10000)
  self.assertEqual(self.call(user='other',ac=10,ec=1)[0],'RATE_LIMITED')
  self.assertEqual(int(command('HGET',self.prefix+'other','tokens')),10000)
  time.sleep(1.05);self.assertEqual(self.call(ac=1,ec=1)[0],'ALLOWED')
 def test_concurrent_event_budget_is_atomic(self):
  with concurrent.futures.ThreadPoolExecutor(8) as pool:results=list(pool.map(lambda i:self.call(str(i)),range(16)))
  count=sum(r[0]=='ALLOWED' for r in results);elapsed=max(int(r[3]) for r in results)-min(int(r[3]) for r in results)
  self.assertLessEqual(count,5+elapsed//1000);self.assertGreaterEqual(count,5)
  self.assertGreater(command('PTTL',self.prefix+'event'),0);self.assertLessEqual(command('PTTL',self.prefix+'event'),86400000)
 def test_backward_clock_normalization_and_forward_refill_cap(self):
  now=int(command('TIME')[0])*1000
  for key in [self.prefix+'u',self.prefix+'event']:command('HSET',key,'tokens',0,'time',now+3600000)
  self.assertEqual(self.call()[0],'RATE_LIMITED')
  self.assertLessEqual(int(command('HGET',self.prefix+'u','time')),now+2000)
  for key in [self.prefix+'u',self.prefix+'event']:command('HSET',key,'tokens',0,'time',now-86400000)
  self.assertEqual(self.call()[0],'ALLOWED');self.assertLessEqual(int(command('HGET',self.prefix+'event','tokens')),4000)
if __name__=='__main__':unittest.main(verbosity=2)
