"""Actual Phase16 projector/initializer exits and recovery under Phase18, own namespace only."""
import concurrent.futures,json,os,secrets,subprocess,time,unittest,uuid,urllib.request
from pathlib import Path
import phase18_admission_http_test as f
SESSION='p18-s-5000';PREFIX='ticketing:seat-availability:{'+SESSION+'}';SEAT=SESSION+'-ss-00001'
class AvailabilityFault(unittest.TestCase):
 def test_cold_projector_initializer_redis_and_pg_rollback(self):
  base=os.environ['PHASE18_BASE_URL'];folder=Path(os.environ['PHASE18_AVAILABILITY_FAULT_DIR']);folder.mkdir(parents=True,exist_ok=True)
  config=json.loads(Path(os.environ['PHASE18_FAULT_CONFIG']).read_text());config['app']['number_of_threads']=4
  (folder/'config.json').write_text(json.dumps(config),encoding='utf-8');names=[];evidence={}
  def docker(*args):
   p=subprocess.run(['docker',*args],capture_output=True,text=True,encoding='utf-8')
   if p.returncode:raise AssertionError(p.stderr)
   return p.stdout.strip()
  def restore():
   docker('start',f.REDIS)
   f.sql("UPDATE session_seats SET status='AVAILABLE' WHERE id='"+SEAT+"'")
   for name in names:docker('stop',name)
   docker('start','phase18-policy-api','phase18-policy-no-secret-api')
  self.addCleanup(restore)
  def request(at=base,query=''):
   return json.load(urllib.request.urlopen(at+'/sessions/'+SESSION+'/seat-availability?zone=Zone%200'+query,timeout=12))
  def healthy(at=base):
   def check():
    try:return urllib.request.urlopen(at+'/health',timeout=1).status==200
    except Exception:return False
   return f.until(check,seconds=25)
  def fault(flag):
   name='phase18-availability-fault-'+uuid.uuid4().hex[:8];names.append(name)
   docker('create','--name',name,'--network','phase18-policy-data','-p','127.0.0.1:18189:8080','--cpus','2','--memory','1g','--pids-limit','256','-e',flag+'=1','-e','TICKETING_ADMISSION_HMAC_SECRET='+secrets.token_hex(32),'--mount','type=bind,source='+str(Path(os.environ['PHASE18_BINARY']))+',target=/sut/ticketing_backend,readonly','--mount','type=bind,source='+str(folder/'config.json')+',target=/sut/config.json,readonly','--workdir','/tmp','--entrypoint','/sut/ticketing_backend','phase14-engineering-build:20260910-v3','/sut/config.json')
   docker('network','connect','phase18-policy-ingress',name);docker('start',name);return name
  # Forty-eight cold reads, concurrency eight: below the new deliberate local limit sixteen.
  # This capability is not the frozen A/B protocol and makes no 24-concurrency all-200 claim.
  healthy();f.until(lambda:f.sql('SELECT count(*) FROM seat_availability_outbox')=='0')
  f.redis('DEL',PREFIX+':meta')
  query="SELECT coalesce(sum(calls),0)::bigint FROM pg_stat_statements WHERE query ILIKE '%inventory.formal_version%' AND query ILIKE '%ORDER BY zone.sort_order,seat.row_no%'"
  before=int(f.sql(query))
  with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:responses=list(pool.map(lambda _:request(),range(48)))
  self.assertEqual(len({r['generation'] for r in responses}),1);self.assertEqual(int(f.sql(query))-before,1)
  evidence['cold']={'requests':48,'concurrency':8,'fullPgQueries':1,'totalSessionSeats':5000};print('cold singleflight PASS',flush=True)
  docker('stop','phase18-policy-no-secret-api');old=request();docker('stop','phase18-policy-api')
  length=f.redis('XLEN',PREFIX+':zone:Zone 0:changes');f.sql("UPDATE session_seats SET status='SOLD' WHERE id='"+SEAT+"'")
  name=fault('PHASE16_FAULT_AFTER_REDIS_APPLY');f.until(lambda:docker('inspect','-f','{{.State.Running}}',name)=='false')
  self.assertEqual(docker('inspect','-f','{{.State.ExitCode}}',name),'86');self.assertGreater(int(f.sql('SELECT count(*) FROM seat_availability_outbox')),0)
  self.assertEqual(f.redis('XLEN',PREFIX+':zone:Zone 0:changes'),length+1)
  docker('start','phase18-policy-api');healthy();f.until(lambda:f.sql('SELECT count(*) FROM seat_availability_outbox')=='0')
  self.assertEqual(f.redis('XLEN',PREFIX+':zone:Zone 0:changes'),length+1)
  delta=request(query='&generation='+old['generation']+'&since='+str(old['cursor']));self.assertIn({'id':SEAT,'status':'SOLD'},delta['changes'])
  f.sql("UPDATE session_seats SET status='AVAILABLE' WHERE id='"+SEAT+"'");f.until(lambda:f.sql('SELECT count(*) FROM seat_availability_outbox')=='0')
  evidence['projectorCrash']={'exitCode':86,'duplicateChanges':0,'outboxDrained':True};print('projector crash PASS',flush=True)
  old=request();docker('stop','phase18-policy-api');f.redis('DEL',PREFIX+':meta');name=fault('PHASE16_FAULT_AFTER_PG_SNAPSHOT');healthy('http://127.0.0.1:18189')
  try:request(at='http://127.0.0.1:18189')
  except Exception:pass
  f.until(lambda:docker('inspect','-f','{{.State.Running}}',name)=='false');self.assertEqual(docker('inspect','-f','{{.State.ExitCode}}',name),'87')
  self.assertEqual(f.redis('EXISTS',PREFIX+':meta'),0)
  f.until(lambda:f.redis('EXISTS',PREFIX+':init-lock')==0,seconds=20)
  docker('start','phase18-policy-api');healthy();self.assertNotEqual(request()['generation'],old['generation'])
  evidence['initializerCrash']={'exitCode':87,'newGeneration':True};print('initializer crash PASS',flush=True)
  old=request();docker('stop',f.REDIS)
  try:
   f.sql("UPDATE session_seats SET status='SOLD' WHERE id='"+SEAT+"'")
   degraded=request(query='&generation='+old['generation']+'&since='+str(old['cursor']));self.assertTrue(degraded['degraded'] and degraded['reset']);self.assertIsNone(degraded['generation']);self.assertIn({'id':SEAT,'status':'SOLD'},degraded['seats']);self.assertGreater(int(f.sql('SELECT count(*) FROM seat_availability_outbox')),0)
  finally:docker('start',f.REDIS)
  f.until(lambda:not request()['degraded']);f.until(lambda:f.sql('SELECT count(*) FROM seat_availability_outbox')=='0')
  f.sql("UPDATE session_seats SET status='AVAILABLE' WHERE id='"+SEAT+"'");f.until(lambda:f.sql('SELECT count(*) FROM seat_availability_outbox')=='0')
  old=request();f.redis('DEL',PREFIX+':meta');rebuilt=request(query='&generation='+old['generation']+'&since='+str(old['cursor']))
  self.assertTrue(rebuilt['reset']);self.assertEqual(rebuilt['mode'],'snapshot');self.assertNotEqual(rebuilt['generation'],old['generation']);self.assertTrue(all(s['status']=='AVAILABLE' for s in rebuilt['seats']))
  f.sql("BEGIN;UPDATE session_seats SET status='SOLD' WHERE id='"+SEAT+"';ROLLBACK;")
  self.assertEqual(f.sql("SELECT status FROM session_seats WHERE id='"+SEAT+"'"),'AVAILABLE');self.assertEqual(f.sql('SELECT count(*) FROM seat_availability_outbox'),'0')
  evidence.update(redisOutage={'authoritativeDegradedSnapshot':True,'outboxPreserved':True,'recovered':True},namespaceReset={'newGeneration':True},postgresRollback={'inventoryPreserved':True,'outboxRows':0})
  (folder/'result.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8');print('Redis outage, namespace reset, PostgreSQL rollback PASS',flush=True)
if __name__=='__main__':unittest.main(verbosity=2)
