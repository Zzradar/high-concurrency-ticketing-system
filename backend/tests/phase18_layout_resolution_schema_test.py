"""Real PostgreSQL adversarial namespace and installed-015 upgrade gates."""
import unittest
from pathlib import Path
import phase18_schema_test as fixture
ROOT=Path(__file__).resolve().parents[1]
M16=(ROOT/'db/migrations/016_harden_layout_revision_resolution.sql').read_text(encoding='utf-8')

class LayoutResolution(fixture.AdmissionSchema):
 def snapshot(self):
  return self.sql('SELECT json_agg(r ORDER BY session_id) FROM session_layout_revisions r')
 def prepare(self,old=False):
  for p in sorted((ROOT/'db/migrations').glob('*.sql')):
   if old and p.name>='016':continue
   self.sql(p.read_text(encoding='utf-8'))
  self.sql((ROOT/'db/seeds/001_demo_seed.sql').read_text(encoding='utf-8'))
 def definitions(self):
  return self.sql("SELECT json_agg(json_build_array(p.oid,p.proname,p.prosecdef,p.proconfig,pg_get_functiondef(p.oid)) ORDER BY p.proname) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='"+self.schema+"' AND p.proname LIKE '%layout%'")
 def assert_safe(self):
  import json
  defs=json.loads(self.definitions());self.assertEqual(len(defs),6)
  for oid,name,definer,config,body in defs:
   self.assertFalse(definer,name);self.assertEqual(config,['search_path=pg_catalog'],name)
   self.assertNotIn('current_schema()',body)
  return [x[0] for x in defs]
 def test_installed015_upgrade_rollback_repeat_oid(self):
  self.prepare(True);before=self.definitions();data=self.snapshot()
  self.sql(M16.replace('COMMIT;','SELECT 1/0;COMMIT;'),False)
  self.assertEqual(before,self.definitions());self.assertEqual(data,self.snapshot())
  import json
  oldoids=[x[0] for x in json.loads(before)]
  self.sql(M16);self.assertEqual(oldoids,self.assert_safe())
  self.assertEqual(data,self.snapshot());self.sql(M16);self.assertEqual(oldoids,self.assert_safe())
  self.shadow_round()
 def shadow_round(self,incompatible=False):
  schema=self.schema;shadow=schema+'_shadow'
  self.sql('CREATE SCHEMA '+shadow)
  try:
   before=self.sql('SELECT sum(revision) FROM session_layout_revisions')
   count=self.sql('SELECT count(DISTINCT session_id) FROM session_seats')
   statements=['BEGIN','CREATE TEMP TABLE session_layout_revisions '+('(unexpected int)' if incompatible else 'AS SELECT * FROM '+schema+'.session_layout_revisions')]
   for table in ['session_seats','seats','venue_zones','sessions','new_rows','old_rows']:
    statements+=['CREATE TEMP TABLE '+table+'(unexpected int)','CREATE TABLE '+shadow+'.'+table+'(unexpected int)']
   statements+=['CREATE TABLE '+shadow+'.session_layout_revisions AS SELECT * FROM '+schema+'.session_layout_revisions',"CREATE FUNCTION "+shadow+".bump_session_layout_revisions(text[]) RETURNS void LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'shadow helper called';END $$",'SET search_path='+shadow+',public,'+schema,'UPDATE '+schema+'.session_seats SET price=price+1','SELECT sum(revision) FROM '+schema+'.session_layout_revisions','SELECT sum(revision) FROM '+shadow+'.session_layout_revisions']
   if not incompatible:statements+=['SELECT sum(revision) FROM pg_temp.session_layout_revisions']
   statements+=['ROLLBACK']
   result=self.sql(';'.join(statements)+';').splitlines()
   self.assertEqual(int(result[0]),int(before)+int(count));self.assertEqual(result[1],before)
   if not incompatible:self.assertEqual(result[2],before)
   self.assertEqual(self.sql('SELECT sum(revision) FROM session_layout_revisions'),before)
  finally:self.sql('DROP SCHEMA '+shadow+' CASCADE')
 def test_fresh_nonpublic_temp_and_ordinary_objects(self):
  self.prepare();self.assert_safe();self.shadow_round();self.shadow_round(True)
 def test_minimal_role_sources_helper_and_late_failure(self):
  self.prepare();s=self.schema;role=s+'_writer';evil=s+'_evil'
  self.sql('CREATE ROLE '+role+';CREATE SCHEMA '+evil)
  try:
   self.sql('GRANT USAGE ON SCHEMA '+s+' TO '+role+';GRANT SELECT ON ALL TABLES IN SCHEMA '+s+' TO '+role+';GRANT UPDATE(price) ON '+s+'.session_seats TO '+role+';GRANT UPDATE(revision) ON '+s+'.session_layout_revisions TO '+role)
   before=self.snapshot()
   q='BEGIN;SET ROLE '+role+';SET search_path=pg_temp,'+evil+',public;CREATE TEMP TABLE session_layout_revisions(unexpected int);UPDATE '+s+'.session_seats SET price=price+1;RESET ROLE;ROLLBACK;'
   self.sql(q);self.assertEqual(self.snapshot(),before)
   self.sql(q.replace('ROLLBACK;', 'COMMIT;'));self.assertNotEqual(self.snapshot(),before)
   before=self.snapshot()
   # No silent skip if the invoker lacks the required revision permission.
   self.sql('REVOKE UPDATE(revision) ON '+s+'.session_layout_revisions FROM '+role)
   self.sql(q,False);self.assertEqual(self.snapshot(),before)
   self.sql('CREATE FUNCTION '+s+".late_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'late failure';END $$;CREATE TRIGGER zz_late_failure AFTER UPDATE ON "+s+'.session_layout_revisions FOR EACH STATEMENT EXECUTE FUNCTION '+s+'.late_failure()')
   price=self.sql('SELECT sum(price) FROM session_seats')
   self.sql('UPDATE session_seats SET price=price+1',False)
   self.assertEqual(self.snapshot(),before);self.assertEqual(self.sql('SELECT sum(price) FROM session_seats'),price)
  finally:
   self.sql('DROP OWNED BY '+role+';DROP ROLE '+role+';DROP SCHEMA '+evil+' CASCADE')
 def test_source_tables_and_transition_relations_cannot_be_shadowed(self):
  self.prepare();s=self.schema
  before=self.sql('SELECT sum(revision) FROM session_layout_revisions')
  count=self.sql('SELECT count(DISTINCT session_id) FROM session_seats')
  shadow=s+'_source';self.sql('CREATE SCHEMA '+shadow)
  self.addCleanup(lambda:self.sql('DROP SCHEMA '+shadow+' CASCADE'))
  q='BEGIN;SET search_path='+shadow+',public;'
  for t in ['session_seats','seats','venue_zones','sessions']:
   q+='CREATE TABLE '+shadow+'.'+t+'(unexpected int);'
  q+='CREATE FUNCTION '+shadow+".bump_session_layout_revisions(text[]) RETURNS void LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'shadow helper';END $$;"
  for t in ['session_seats','seats','venue_zones','sessions','new_rows','old_rows']:q+='CREATE TEMP TABLE '+t+'(unexpected int);'
  q+='UPDATE '+s+'.seats SET seat_label=seat_label||\'-x\';UPDATE '+s+'.venue_zones SET name=name||\'-x\';SELECT sum(revision) FROM '+s+'.session_layout_revisions;ROLLBACK;'
  self.assertEqual(int(self.sql(q)),int(before)+2*int(count))

if __name__=='__main__':unittest.main(verbosity=2)
