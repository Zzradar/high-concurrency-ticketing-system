"""Real PostgreSQL migration and read/gate SQL boundaries in disposable schemas."""
from pathlib import Path
import subprocess,re,unittest,uuid
ROOT=Path(__file__).resolve().parents[1]
class SalesMigrationTest(unittest.TestCase):
    def sql(self,text,ok=True):
        r=subprocess.run(['docker','exec','-i','phase15-postgres','psql','-U','postgres','-qAt','-v','ON_ERROR_STOP=1'],input=self.prefix+text,capture_output=True,text=True,encoding='utf-8')
        if ok:self.assertEqual(r.returncode,0,r.stderr)
        else:self.assertNotEqual(r.returncode,0)
        return r.stdout.strip()
    def setUp(self):
        self.schema='p15_'+uuid.uuid4().hex;self.prefix=''
        self.sql('CREATE SCHEMA '+self.schema+';');self.prefix='SET search_path TO '+self.schema+';'
        self.addCleanup(lambda:self.sql('DROP SCHEMA '+self.schema+' CASCADE;'))
    def install(self,upgrade=False):
        migrations=sorted((ROOT/'db/migrations').glob('*.sql'))
        if upgrade:
            migrations=[p for p in migrations if p.name<'011']
            seed=subprocess.check_output(['git','show','d1d1fd7170553df86c73cfa2313f09d57fa718a6:backend/db/seeds/001_demo_seed.sql'],cwd=ROOT).decode()
        else:seed=(ROOT/'db/seeds/001_demo_seed.sql').read_text(encoding='utf-8')
        self.sql(''.join(p.read_text(encoding='utf-8') for p in migrations)+seed)
    def test_upgrade_backfill_and_constraints(self):
        self.install(True)
        self.sql("INSERT INTO events(id,primary_venue_id,name,description,status,category,cover_url,date_range) SELECT 'no-session',primary_venue_id,name,description,status,category,cover_url,date_range FROM events LIMIT 1;")
        self.sql((ROOT/'db/migrations/011_add_event_sales_window.sql').read_text())
        self.assertEqual(self.sql('SELECT count(*) FROM events WHERE sales_starts_at IS NULL OR sales_ends_at IS NULL OR sales_starts_at>=sales_ends_at;'),'0')
        self.assertEqual(self.sql("SELECT count(*) FROM events e WHERE EXISTS(SELECT 1 FROM sessions s WHERE s.event_id=e.id) AND e.sales_ends_at<>(SELECT MAX(start_time) FROM sessions s WHERE s.event_id=e.id);"),'0')
        self.assertEqual(self.sql("SELECT sales_ends_at=created_at+INTERVAL '1 second' AND sales_starts_at=created_at FROM events WHERE id='no-session';"),'t')
        self.assertEqual(self.sql('SELECT count(*) FROM sessions s JOIN events e ON e.id=s.event_id WHERE s.start_time<=e.sales_starts_at;'),'0')
        self.sql('UPDATE events SET sales_starts_at=sales_ends_at;',False)
        self.sql('UPDATE events SET sales_ends_at=NULL;',False)
        self.sql('UPDATE events SET sales_starts_at=NULL;',False)
    def test_fresh_seed_and_original_invariants(self):
        self.install()
        for p in sorted((ROOT/'db/tests').glob('*.sql')):self.sql(p.read_text(encoding='utf-8'))
        self.assertEqual(self.sql('SELECT count(*) FROM session_seats WHERE formal_version<0;'),'0')
        self.assertEqual(self.sql('SELECT count(*) FROM seat_availability_outbox;'),'0')
    def gate(self,now):
        source=(ROOT/'src/repositories/SalesWindowRepository.cpp').read_text()
        query=re.search(r'R"SQL\((.*?)\)SQL"',source,re.S).group(1)
        query=query.replace('clock_timestamp()',"TIMESTAMPTZ '"+now+"'").replace('$1',"'ses-concert-1001'")
        return self.sql(query+';').split('|')
    def test_half_open_microsecond_boundaries_and_empty_window(self):
        self.install()
        self.sql("UPDATE events SET sales_starts_at='2026-09-20 10:00:00Z',sales_ends_at='2026-09-20 10:01:00Z' WHERE id='evt-concert-2026';")
        for now,state in [('2026-09-20 09:59:59.999999Z','NOT_STARTED'),('2026-09-20 10:00:00Z','OPEN'),('2026-09-20 10:00:59.999999Z','OPEN'),('2026-09-20 10:01:00Z','ENDED'),('2026-09-20 10:01:00.000001Z','ENDED')]:
            with self.subTest(now=now):self.assertEqual(self.gate(now)[3],state)
        self.assertEqual(self.gate('2026-09-20 10:00:59.999999Z')[4],'0')
        self.sql("UPDATE sessions SET start_time='2026-09-20 09:00:00Z',gate_time='2026-09-20 08:00:00Z' WHERE id='ses-concert-1001';")
        self.assertEqual(self.gate('2026-09-20 08:00:00Z')[3],'ENDED')
    def test_actual_public_read_queries(self):
        self.install()
        event=(ROOT/'src/repositories/EventRepository.cpp').read_text(encoding='utf-8')
        select=re.search(r'kEventSelect = R"SQL\((.*?)\)SQL"',event,re.S).group(1)
        group=re.search(r'kEventGroupBy = R"SQL\((.*?)\)SQL"',event,re.S).group(1)
        self.assertTrue(self.sql(select+group+';'))
        session=(ROOT/'src/repositories/SessionRepository.cpp').read_text(encoding='utf-8')
        queries=re.findall(r'R"SQL\((.*?)\)SQL"',session,re.S)
        for query,value in zip(queries,['evt-concert-2026','ses-concert-1001']):
            result=self.sql(query.replace('$1',"'"+value+"'")+';')
            self.assertRegex(result,r'2026-.*Z')
if __name__=='__main__':unittest.main(verbosity=2)
