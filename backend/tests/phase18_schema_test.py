"""Real PostgreSQL fresh/upgrade constraints. Explicit isolated container required."""
import os,subprocess,unittest,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
PG=os.environ['PHASE18_POSTGRES_CONTAINER']
class AdmissionSchema(unittest.TestCase):
 def sql(self,q,ok=True):
  p=subprocess.run(['docker','exec','-i',PG,'psql','-U','postgres','-qAt','-v','ON_ERROR_STOP=1'],input=self.prefix+q,text=True,encoding='utf-8',capture_output=True)
  self.assertEqual(p.returncode==0,ok,p.stderr)
  return p.stdout.strip()
 def setUp(self):
  self.prefix='';self.schema='p18_'+uuid.uuid4().hex;self.sql('CREATE SCHEMA '+self.schema)
  self.prefix='SET search_path TO '+self.schema+';'
  self.addCleanup(lambda:self.sql('DROP SCHEMA '+self.schema+' CASCADE;'))
 def install(self,upgrade=False):
  for p in sorted((ROOT/'db/migrations').glob('*.sql')):
   if upgrade and p.name>='013':continue
   self.sql(p.read_text(encoding='utf-8'))
  self.sql((ROOT/'db/seeds/001_demo_seed.sql').read_text(encoding='utf-8'))
 def test_upgrade_preserves_business_and_absent_policy_is_off(self):
  self.install(True)
  before=self.sql("SELECT md5(string_agg(row_to_json(s)::text,',' ORDER BY id)) FROM session_seats s")
  self.sql((ROOT/'db/migrations/013_add_admission_control.sql').read_text())
  self.sql((ROOT/'db/migrations/014_add_admission_runtime_tracking.sql').read_text())
  self.assertEqual(before,self.sql("SELECT md5(string_agg(row_to_json(s)::text,',' ORDER BY id)) FROM session_seats s"))
  self.assertEqual(self.sql('SELECT count(*) FROM event_admission_policies'),'0')
  self.assertEqual(self.sql('SELECT count(*) FROM admission_policy_audit'),'0')
  self.assertEqual(self.sql('SELECT count(*) FROM admission_runtime_generations'),'0')
 def test_fresh_constraints_and_policy_occ(self):
  self.install()
  self.sql("INSERT INTO event_admission_policies(event_id,mode,prequeue_seconds,max_active_users,admission_rate_per_second,lease_seconds,policy_version,queue_generation,updated_by) SELECT (SELECT id FROM events LIMIT 1),'OFF',0,10,2,30,1,repeat('a',32),id FROM app_users WHERE role='ADMIN' LIMIT 1")
  for change in ["mode='off'","prequeue_seconds=-1","prequeue_seconds=86401","max_active_users=0","max_active_users=1000001","admission_rate_per_second=0","lease_seconds=9","lease_seconds=3601","policy_version=0","policy_version=9007199254740992","queue_generation='unsafe{}'","updated_by='missing'"]:
   with self.subTest(change=change):self.sql('UPDATE event_admission_policies SET '+change,False)
  self.sql('UPDATE event_admission_policies SET policy_version=policy_version+1 WHERE policy_version=1')
  self.assertEqual(self.sql('UPDATE event_admission_policies SET policy_version=policy_version+1 WHERE policy_version=1 RETURNING policy_version'),'')
  self.assertEqual(self.sql('SELECT policy_version FROM event_admission_policies'),'2')
if __name__=='__main__':unittest.main(verbosity=2)
