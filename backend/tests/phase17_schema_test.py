"""Real migration011 upgrade/fresh gates; disposable schemas in a dedicated container."""
from pathlib import Path
import json, os, subprocess, time, unittest, uuid
ROOT=Path(__file__).resolve().parents[1]
CONTAINER=os.environ.get('PHASE17_POSTGRES_CONTAINER','phase17-postgres')
class SchemaTest(unittest.TestCase):
    def sql(self,statement,ok=True):
        result=subprocess.run(['docker','exec','-i',CONTAINER,'psql','-U','postgres','-qAt','-v','ON_ERROR_STOP=1'],input=self.prefix+statement,text=True,encoding='utf-8',capture_output=True)
        if ok: self.assertEqual(result.returncode,0,result.stderr)
        else: self.assertNotEqual(result.returncode,0,result.stdout)
        return result.stdout.strip()
    def setUp(self):
        self.prefix='';self.schema='p17_'+uuid.uuid4().hex
        self.sql('CREATE SCHEMA '+self.schema+';')
        self.prefix='SET search_path TO '+self.schema+';'
        self.addCleanup(lambda:self.sql('DROP SCHEMA '+self.schema+' CASCADE;'))
    def install(self,upgrade=False):
        paths=sorted((ROOT/'db/migrations').glob('*.sql'))
        if upgrade:
            paths=[p for p in paths if p.name<'012']
            seed=subprocess.check_output(['git','show','1d7194d0aac708592e52a1d59fb642c21ce7554e:backend/db/seeds/001_demo_seed.sql'],cwd=ROOT).decode('utf-8')
        else:seed=(ROOT/'db/seeds/001_demo_seed.sql').read_text(encoding='utf-8')
        self.sql(''.join(p.read_text(encoding='utf-8') for p in paths)+seed)
    def migration(self):self.sql((ROOT/'db/migrations/012_add_admin_event_publishing.sql').read_text())
    def test_upgrade_preserves_every_seat_and_deterministic_zone_identity(self):
        self.install(True)
        self.sql('CREATE TABLE old_seats AS SELECT * FROM seats;')
        self.migration()
        self.assertEqual(self.sql('SELECT count(*) FROM seats s JOIN old_seats o USING(id) JOIN venue_zones z ON z.id=s.zone_id WHERE s.venue_id<>o.venue_id OR s.row_no<>o.row_no OR s.seat_no<>o.seat_no OR s.seat_label<>o.seat_label OR z.name<>o.zone;'),'0')
        self.assertEqual(self.sql("SELECT count(*) FROM app_users WHERE role<>'CUSTOMER';"),'0')
        self.assertEqual(self.sql('SELECT count(*) FROM events WHERE published_at IS NOT NULL OR published_by IS NOT NULL;'),'0')
        self.assertEqual(self.sql("SELECT count(*) FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='seats' AND column_name='zone';"),'0')
        self.assertEqual(self.sql("SELECT count(*) FROM venue_zones WHERE id <> 'VZ-LEGACY-'||length(venue_id)::text||':'||venue_id||':'||name;"),'0')
        self.assertEqual(self.sql('SELECT count(*) FROM seats;'),'120')
        self.check_order()
    def check_order(self):
        self.assertEqual(self.sql("SELECT string_agg(name,',' ORDER BY sort_order) FROM venue_zones GROUP BY venue_id ORDER BY venue_id;"), '星光区,看台 A 区,看台 B 区\n星光区,看台 A 区,看台 B 区')
    def test_fresh_seed_all_verifiers_and_formal_fields(self):
        self.install()
        for p in sorted((ROOT/'db/tests').glob('*.sql')):self.sql(p.read_text(encoding='utf-8'))
        self.check_order()
        self.assertEqual(self.sql("SELECT role FROM app_users WHERE username='admin';"),'ADMIN')
        self.assertEqual(self.sql("SELECT role FROM app_users WHERE username='demo';"),'CUSTOMER')
        self.assertEqual(self.sql('SELECT count(*) FROM session_seats WHERE formal_version<>0;'),'0')
        self.assertEqual(self.sql('SELECT count(*) FROM seat_availability_outbox;'),'0')
        self.assertEqual(self.sql('SELECT count(*) FROM events WHERE sales_starts_at>=sales_ends_at;'),'0')
    def test_constraints_duplicate_labels_and_price_cascades(self):
        self.install()
        self.sql("INSERT INTO venues(id,name,city) VALUES('p17v','V','C'),('p17other','V','C'); INSERT INTO venue_zones(id,venue_id,code,name,sort_order) VALUES('p17z1','p17v','ONE','Zulu',0),('p17z2','p17v','TWO','Alpha',1),('p17zo','p17other','OTHER','Other',0); INSERT INTO seats(id,venue_id,zone_id,row_no,seat_no,seat_label) VALUES('p17a','p17v','p17z1','A',1,'A001'),('p17b','p17v','p17z2','A',1,'A001');")
        self.assertEqual(self.sql("SELECT count(*) FROM seats WHERE seat_label='A001';"),'2')
        invalid=["UPDATE app_users SET role='admin' WHERE username='admin';", "UPDATE app_users SET role=NULL WHERE username='admin';", "UPDATE seats SET zone_id=NULL WHERE id='p17a';", "UPDATE seats SET zone_id='p17zo' WHERE id='p17a';", "UPDATE seats SET zone_id='p17z1' WHERE id='p17b';", "INSERT INTO seats(id,venue_id,zone_id,row_no,seat_no,seat_label) VALUES('p17dup','p17v','p17z1','B',2,'A001');", "UPDATE venue_zones SET code='ONE' WHERE id='p17z2';", "UPDATE venue_zones SET name='Zulu' WHERE id='p17z2';", "UPDATE venue_zones SET sort_order=0 WHERE id='p17z2';", "UPDATE venue_zones SET sort_order=-1 WHERE id='p17z2';", "UPDATE venue_zones SET code=' ' WHERE id='p17z2';", "UPDATE venue_zones SET name=' ' WHERE id='p17z2';"]
        for statement in invalid:
            with self.subTest(sql=statement):self.sql(statement,False)
        self.sql("INSERT INTO events(id,primary_venue_id,name,description,status,category,cover_url,date_range,sales_starts_at,sales_ends_at) VALUES('p17e','p17v','E','','DRAFT','C','cover','',now(),now()+interval '1 day'); INSERT INTO sessions(id,event_id,venue_id,hall_name,start_time,gate_time,status) VALUES('p17s','p17e','p17v','Hall',now()+interval '1 day',now(),'DRAFT');")
        for values in ("'p17s','p17z1','p17v',0", "'p17s','p17z1','p17v',-1", "'p17s','p17zo','p17v',1", "'p17s','p17zo','p17other',1", "'missing','p17z1','p17v',1"):
            self.sql('INSERT INTO session_zone_prices(session_id,zone_id,venue_id,price) VALUES('+values+');',False)
        self.sql("INSERT INTO session_zone_prices(session_id,zone_id,venue_id,price) VALUES('p17s','p17z1','p17v',9223372036854775807);")
        self.sql("INSERT INTO session_zone_prices(session_id,zone_id,venue_id,price) VALUES('p17s','p17z1','p17v',100);",False)
        self.sql("UPDATE events SET published_by='missing' WHERE id='p17e';",False)
        self.sql("INSERT INTO session_zone_prices(session_id,zone_id,venue_id,price) VALUES('p17s','p17z2','p17v',100); DELETE FROM seats WHERE id='p17b'; DELETE FROM venue_zones WHERE id='p17z2';")
        self.assertEqual(self.sql('SELECT count(*) FROM session_zone_prices;'),'1')
        self.sql("DELETE FROM sessions WHERE id='p17s';")
        self.assertEqual(self.sql('SELECT count(*) FROM session_zone_prices;'),'0')
    def test_performance_generator_and_replacement_use_normalized_zones(self):
        self.install()
        import sys
        sys.path.insert(0,str(ROOT.parent/'performance/data'))
        import generate_dataset as generator
        profile,_=generator.load_profile('smoke')
        shape=generator.validate_profile(profile)
        credentials=generator.generate_session_credentials(shape.active_auth_sessions)
        generated=generator.build_generation_sql(profile,shape,credentials,86400,604800)
        for _ in range(2):
            self.sql(generated)
            self.assertEqual(self.sql("SELECT count(*) FROM seats WHERE venue_id='perf-venue-001';"),str(shape.seats))
            self.assertEqual(self.sql("SELECT count(*) FROM venue_zones WHERE venue_id='perf-venue-001';"),str(len(profile['priceZones'])))
            self.assertEqual(self.sql("SELECT count(*) FROM seats s JOIN venue_zones z ON z.id=s.zone_id WHERE s.venue_id<>z.venue_id;"),'0')
            self.assertEqual(self.sql("SELECT count(*) FROM app_users WHERE id LIKE 'perf-user-%' AND role<>'CUSTOMER';"),'0')
    def test_backfill_orders_by_real_first_pair_and_preserves_unusual_names(self):
        self.install(True)
        self.sql("INSERT INTO venues(id,name,city) VALUES('v:1','V','C'); INSERT INTO seats(id,venue_id,row_no,seat_no,seat_label,zone) VALUES('x1','v:1','A',9,'X1',' Z:区 '),('x2','v:1','B',1,'X2',' Z:区 '),('x3','v:1','A',5,'X3','B 区');")
        self.migration()
        self.assertEqual(json.loads(self.sql("SELECT json_agg(name ORDER BY sort_order) FROM venue_zones WHERE venue_id='v:1';")),['B 区',' Z:区 '])
class FreshComposeTest(unittest.TestCase):
    def test_actual_compose_initdb_mounts_and_verifiers(self):
        config=json.loads(subprocess.check_output(['docker','compose','-f',str(ROOT/'docker-compose.yml'),'config','--format','json'],text=True,encoding='utf-8'))
        name='phase17-fresh-'+uuid.uuid4().hex
        args=['docker','run','-d','--name',name,'--tmpfs','/var/lib/postgresql/data','-e','POSTGRES_USER=ticketing','-e','POSTGRES_DB=ticketing','-e','POSTGRES_PASSWORD=ticketing_dev']
        for volume in config['services']['postgres']['volumes']:
            if volume['target'].startswith('/docker-entrypoint-initdb.d/'):
                args+=['--mount','type=bind,source='+volume['source']+',target='+volume['target']+',readonly']
        subprocess.run(args+['postgres:16-alpine'],check=True,capture_output=True)
        self.addCleanup(lambda:subprocess.run(['docker','rm','-f',name],check=True,capture_output=True))
        deadline=time.monotonic()+30
        while time.monotonic()<deadline:
            logs=subprocess.check_output(['docker','logs',name],stderr=subprocess.STDOUT,text=True,encoding='utf-8')
            self.assertNotIn('ERROR:',logs)
            if 'PostgreSQL init process complete; ready for start up.' in logs:break
            time.sleep(.25)
        else:self.fail('fresh init deadline exceeded')
        result=subprocess.check_output(['docker','exec',name,'psql','-U','ticketing','-d','ticketing','-qAt','-c',"SELECT (SELECT count(*) FROM venue_zones),(SELECT count(*) FROM seats),(SELECT role FROM app_users WHERE username='admin');"],text=True)
        self.assertEqual(result.strip(),'6|120|ADMIN')

if __name__=='__main__':unittest.main(verbosity=2)
