"""Real Redis Lua gates; uses only unique event-tagged keys in an explicit test container."""
import concurrent.futures,json,os,subprocess,time,unittest,uuid
from pathlib import Path
REDIS=os.environ['PHASE18_REDIS_CONTAINER']
SCRIPT=Path(__file__).resolve().parents[1]/'src/admission/waiting_room.lua'
def command(*args):
 if args[0]=='DUMP':
  p=subprocess.run(['docker','exec',REDIS,'redis-cli','--raw',*map(str,args)],capture_output=True)
  if p.returncode:raise AssertionError(p.stderr)
  return p.stdout
 p=subprocess.run(['docker','exec',REDIS,'redis-cli','--json',*map(str,args)],text=True,encoding='utf-8',capture_output=True)
 if p.returncode:raise AssertionError(p.stderr)
 return json.loads(p.stdout)
def setUpModule():
 subprocess.run(['docker','cp',str(SCRIPT),REDIS+':/tmp/phase18-waiting.lua'],check=True,capture_output=True)
class WaitingRoom(unittest.TestCase):
 def setUp(self):
  self.prefix='p18:{'+uuid.uuid4().hex+'}:';self.gen='g1';self.version=1;self.mode='ENFORCED'
  self.now=int(command('TIME')[0])*1000;self.starts=self.now+60000;self.ends=self.now+300000
  self.capacity=2;self.rate=2;self.batch=64
  self.assertEqual(self.call('sync')[0],'OK')
 def keys(self,gen=None):
  g=self.prefix+(gen or self.gen)+':'
  return [self.prefix+'runtime',g+'prequeue',g+'waiting',g+'presence',g+'active',g+'heartbeat',g+'sequence',g+'release',g+'pause']
 def call(self,op,member='u',score=10,bootstrap='1',gen=None):
  return command('--eval','/tmp/phase18-waiting.lua',*self.keys(gen),',',op,gen or self.gen,self.version,self.mode,self.now-1000,self.starts,self.ends,self.capacity,self.rate,10000,10000,1000,member,score,self.batch,bootstrap)
 def ready(self):
  self.starts=self.now-500
  command('HSET',self.keys()[7],'time',self.now-2000,'tokens',0)
 def test_repeated_join_multi_tab_and_read_only_status(self):
  first=self.call('join');self.assertEqual(first[0],'PREQUEUED')
  keys=self.keys();before=[command('DUMP',k) for k in keys];expiry=[command('PEXPIRETIME',k) for k in keys]
  with concurrent.futures.ThreadPoolExecutor(8) as pool:
   results=list(pool.map(lambda _:self.call('join'),range(16)))
  self.assertTrue(all(r[0]=='PREQUEUED' for r in results));self.assertEqual(command('ZCARD',keys[1]),1)
  for _ in range(3):self.call('status');self.call('heartbeat')
  # Early heartbeat is tested against a controlled future next-allowed time below.
  command('HSET',keys[5],'u',int(time.time()*1000)+60000)
  before=[command('DUMP',k) for k in keys];expiry=[command('PEXPIRETIME',k) for k in keys]
  self.call('status');self.call('heartbeat');self.call('status')
  self.assertEqual(before,[command('DUMP',k) for k in keys]);self.assertEqual(expiry,[command('PEXPIRETIME',k) for k in keys])
 def test_stable_prequeue_order_then_fifo(self):
  for member,score in [('c',30),('a',10),('b',20)]:self.call('join',member,score)
  self.ready();self.call('join','d');self.call('join','e')
  self.assertEqual(command('ZRANGE',self.keys()[1],0,-1),['a','b','c'])
  self.assertEqual(command('ZRANGE',self.keys()[2],0,-1),['d','e'])
  self.call('tick');self.assertEqual(command('ZRANGE',self.keys()[4],0,-1),['a','b'])
  self.call('leave','a');self.call('leave','b');self.ready();self.call('tick')
  self.assertEqual(set(command('ZRANGE',self.keys()[4],0,-1)),{'c','d'})
 def test_parallel_scheduler_capacity_and_rate(self):
  self.capacity=3;self.rate=2
  for i in range(8):self.call('join',str(i),i)
  self.ready()
  with concurrent.futures.ThreadPoolExecutor(8) as pool:list(pool.map(lambda _:self.call('tick'),range(8)))
  self.assertLessEqual(command('ZCARD',self.keys()[4]),3)
  self.assertEqual(command('ZCARD',self.keys()[1])+command('ZCARD',self.keys()[4]),8)
  self.capacity=1;old=command('ZRANGE',self.keys()[4],0,-1);self.call('tick');self.assertEqual(command('ZRANGE',self.keys()[4],0,-1),old)
 def test_expiry_cannot_be_revived_by_get_or_heartbeat(self):
  self.call('join');command('ZADD',self.keys()[3],self.now-1,'u')
  self.assertEqual(self.call('status')[0],'NOT_JOINED');self.assertEqual(self.call('heartbeat')[0],'NOT_JOINED')
  self.call('tick');self.assertEqual(command('ZCARD',self.keys()[1]),0)
  self.call('join');self.ready();self.call('tick');self.assertEqual(self.call('status')[0],'ADMITTED')
  command('ZADD',self.keys()[4],self.now-1,'u')
  self.assertEqual(self.call('heartbeat')[0],'NOT_JOINED');self.call('tick');self.assertEqual(command('ZCARD',self.keys()[4]),0)
 def test_shadow_stale_version_pause_and_missing_runtime(self):
  self.mode='OBSERVE';self.version=2;self.call('sync');self.call('join');self.ready();self.call('tick');self.assertEqual(self.call('status')[0],'ADMITTED')
  old=self.gen;self.gen='formal';self.mode='PAUSED';self.version=3;self.call('sync')
  self.assertEqual(self.call('status',gen=old)[0],'RESET_REQUIRED')
  self.call('join');self.assertEqual(self.call('tick')[0],'PAUSED');self.assertEqual(command('ZCARD',self.keys()[4]),0)
  self.mode='ENFORCED';self.version=4;self.call('sync');self.ready();self.call('tick');self.assertEqual(self.call('status')[0],'ADMITTED')
  self.version=3;self.assertEqual(self.call('sync')[0],'STALE');self.assertEqual(self.call('join')[0],'RESET_REQUIRED')
  self.version=4;command('DEL',self.keys()[0]);self.assertEqual(self.call('status')[0],'RESET_REQUIRED');self.assertEqual(self.call('sync',bootstrap='0')[0],'MISSING')
 def test_preopen_ended_leave_and_short_lua_failure(self):
  self.starts=self.now+100000;self.ends=self.now+200000
  self.assertEqual(self.call('leave')[0],'NOT_JOINED');self.assertEqual(self.call('leave')[0],'NOT_JOINED')
  self.batch=257;self.assertEqual(self.call('join')[0],'INVALID');self.assertEqual(command('ZCARD',self.keys()[1]),0)
  self.batch=64;self.ends=self.now-100;self.starts=self.now-200;self.now-=1000
  self.assertEqual(self.call('join')[0],'SALES_ENDED')
if __name__=='__main__':unittest.main(verbosity=2)
