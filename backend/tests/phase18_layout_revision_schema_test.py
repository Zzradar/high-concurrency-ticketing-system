"""Statement-level revision, migration atomicity and targeting on isolated schemas."""
import unittest
from pathlib import Path
import phase18_schema_test as fixture
ROOT=Path(__file__).resolve().parents[1]
MIGRATION=(ROOT/'db/migrations/015_add_layout_revision.sql').read_text()

class LayoutRevisionSchema(fixture.AdmissionSchema):
 def install14(self):
  for p in sorted((ROOT/'db/migrations').glob('*.sql')):
   if p.name < '015':self.sql(p.read_text(encoding='utf-8'))
  self.sql((ROOT/'db/seeds/001_demo_seed.sql').read_text(encoding='utf-8'))
 def test_upgrade_backfill_repeat_and_failure_rollback(self):
  self.install14()
  before=self.sql("SELECT md5(string_agg(row_to_json(s)::text,',' ORDER BY id)) FROM session_seats s")
  self.sql(MIGRATION.replace('COMMIT;','SELECT 1/0;COMMIT;'),False)
  self.assertEqual(self.sql("SELECT count(*) FROM information_schema.tables WHERE table_schema=current_schema() AND table_name='session_layout_revisions'"),'0')
  self.sql(MIGRATION)
  self.assertEqual(self.sql('SELECT count(*) FROM sessions s LEFT JOIN session_layout_revisions r ON r.session_id=s.id WHERE r.revision IS DISTINCT FROM 1'),'0')
  self.assertEqual(before,self.sql("SELECT md5(string_agg(row_to_json(s)::text,',' ORDER BY id)) FROM session_seats s"))
  self.sql(MIGRATION,False)
  self.assertEqual(self.sql('SELECT max(revision) FROM session_layout_revisions'),'1')
 def test_fresh_bulk_5000_10000_and_multi_session_once(self):
  self.install()
  sid=self.sql('SELECT id FROM sessions ORDER BY id LIMIT 1')
  venue=self.sql("SELECT venue_id FROM sessions WHERE id='"+sid+"'")
  zone=self.sql("SELECT id FROM venue_zones WHERE venue_id='"+venue+"' ORDER BY id LIMIT 1")
  self.sql("INSERT INTO sessions(id,event_id,venue_id,hall_name,start_time,gate_time,status) SELECT id||'-copy',event_id,venue_id,hall_name,start_time,gate_time,status FROM sessions WHERE id='"+sid+"'")
  copy=sid+'-copy'
  self.sql('CREATE TABLE revision_write_audit(session_id text);CREATE FUNCTION capture_revision_write() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN INSERT INTO revision_write_audit VALUES(NEW.session_id);RETURN NEW;END $$;CREATE TRIGGER capture_revision_write AFTER UPDATE ON session_layout_revisions FOR EACH ROW EXECUTE FUNCTION capture_revision_write()')
  for count in [5000,10000]:
   with self.subTest(seats=count):
    prefix='bulk'+str(count)
    self.sql("INSERT INTO seats(id,venue_id,zone_id,row_no,seat_no,seat_label) SELECT '"+prefix+"-'||n,'"+venue+"','"+zone+"','"+prefix+"',n,'"+prefix+"-'||n FROM generate_series(1,"+str(count)+") n")
    before=int(self.sql("SELECT revision FROM session_layout_revisions WHERE session_id='"+sid+"'"))
    self.sql("INSERT INTO session_seats(id,session_id,seat_id,venue_id,status,price) SELECT '"+prefix+"-inv-'||n,'"+sid+"','"+prefix+"-'||n,'"+venue+"','AVAILABLE',100 FROM generate_series(1,"+str(count)+") n")
    self.assertEqual(int(self.sql("SELECT revision FROM session_layout_revisions WHERE session_id='"+sid+"'")),before+1)
    self.assertEqual(self.sql('SELECT count(*) FROM revision_write_audit'),'1');self.sql('DELETE FROM revision_write_audit')
    self.sql("UPDATE session_seats SET price=101 WHERE session_id='"+sid+"' AND id LIKE '"+prefix+"-inv-%'")
    self.assertEqual(self.sql('SELECT count(*) FROM revision_write_audit'),'1');self.sql('DELETE FROM revision_write_audit')
  self.sql("INSERT INTO session_seats(id,session_id,seat_id,venue_id,status,price) SELECT id||'-copy','"+copy+"',seat_id,venue_id,'AVAILABLE',price FROM session_seats WHERE session_id='"+sid+"'")
  self.sql('DELETE FROM revision_write_audit')
  self.sql("UPDATE session_seats SET price=price+1 WHERE session_id IN ('"+sid+"','"+copy+"')")
  self.assertEqual(self.sql('SELECT count(*) FROM revision_write_audit'),'2')
  self.assertEqual(self.sql('SELECT max(n) FROM (SELECT count(*) n FROM revision_write_audit GROUP BY session_id) x'),'1')
  self.sql('DELETE FROM revision_write_audit')
  self.sql("UPDATE seats SET seat_label=seat_label||'-new' WHERE venue_id='"+venue+"' AND row_no LIKE 'bulk%'")
  self.assertEqual(self.sql('SELECT count(*) FROM revision_write_audit'),'2')
  print('Bulk 5000/10000: each INSERT/UPDATE causes one revision write per affected Session; shared-seat change targets two Sessions.')
 def test_targeting_and_noop(self):
  self.install()
  sid=self.sql('SELECT id FROM sessions ORDER BY id LIMIT 1');venue=self.sql("SELECT venue_id FROM sessions WHERE id='"+sid+"'")
  self.sql('CREATE TABLE revision_statements(n int);CREATE FUNCTION count_revision_statement() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN INSERT INTO revision_statements VALUES(1);RETURN NULL;END $$;CREATE TRIGGER count_revision_statement AFTER UPDATE ON session_layout_revisions FOR EACH STATEMENT EXECUTE FUNCTION count_revision_statement()')
  before=self.sql("SELECT json_object_agg(session_id,revision ORDER BY session_id) FROM session_layout_revisions")
  self.sql('UPDATE session_seats SET price=price;UPDATE seats SET seat_label=seat_label;UPDATE venue_zones SET name=name;UPDATE venues SET name=name;')
  self.assertEqual(before,self.sql("SELECT json_object_agg(session_id,revision ORDER BY session_id) FROM session_layout_revisions"))
  self.sql('UPDATE session_seats SET formal_version=formal_version+1;')
  self.assertEqual(self.sql('SELECT count(*) FROM revision_statements'),'0','No-op and dynamic changes must not execute even an empty revision UPDATE')
  self.sql("CREATE TABLE revision_before AS SELECT * FROM session_layout_revisions; UPDATE venue_zones SET name=name||'-fixed' WHERE venue_id='"+venue+"'")
  self.assertEqual(self.sql("SELECT count(*) FROM session_layout_revisions r JOIN revision_before b USING(session_id) WHERE r.revision<>b.revision+CASE WHEN EXISTS(SELECT 1 FROM session_seats i JOIN seats s ON s.id=i.seat_id WHERE i.session_id=r.session_id AND s.venue_id='"+venue+"') THEN 1 ELSE 0 END"),'0')
 def test_session_id_reuse_and_inventory_truncate(self):
  self.install()
  sid=self.sql('SELECT id FROM sessions ORDER BY id LIMIT 1')
  self.sql("CREATE TABLE saved_empty_session AS SELECT * FROM sessions WHERE id='"+sid+"';UPDATE saved_empty_session SET id=id||'-empty';INSERT INTO sessions SELECT * FROM saved_empty_session")
  empty=sid+'-empty'
  r=int(self.sql("SELECT revision FROM session_layout_revisions WHERE session_id='"+empty+"'"))
  self.sql("DELETE FROM sessions WHERE id='"+empty+"';INSERT INTO sessions SELECT * FROM saved_empty_session")
  self.assertGreater(int(self.sql("SELECT revision FROM session_layout_revisions WHERE session_id='"+empty+"'")),r)
  self.sql('CREATE TABLE revisions_before_truncate AS SELECT * FROM session_layout_revisions;CREATE TABLE occupied_sessions AS SELECT DISTINCT session_id FROM session_seats;TRUNCATE session_seats CASCADE;')
  self.assertEqual(self.sql('SELECT count(*) FROM session_layout_revisions r JOIN revisions_before_truncate b USING(session_id) WHERE r.revision<>b.revision+CASE WHEN r.session_id IN(SELECT session_id FROM occupied_sessions) THEN 1 ELSE 0 END'),'0')

if __name__=='__main__':unittest.main(verbosity=2)
