"""Default/public namespace counterexample and public HTTP validator contract."""
import json,unittest,uuid
import phase18_admission_http_test as fixture
import phase18_layout_http_test as layout
class LayoutResolutionHTTP(unittest.TestCase):
 setUp=fixture.AdmissionHTTP.setUp
 get=layout.LayoutHTTP.get
 def test_shadowed_revision_still_invalidates_public_etag(self):
  seat=self.seats[0]['id'];sid=self.s;shadow='shadow_'+uuid.uuid4().hex
  fixture.sql('CREATE SCHEMA '+shadow)
  try:
   for kind in ['temp','ordinary','incompatible']:
    with self.subTest(kind=kind):
     _,before,headers=self.get(sid);tag=headers['etag']
     r=int(fixture.sql("SELECT revision FROM public.session_layout_revisions WHERE session_id='"+sid+"'"))
     q='BEGIN;SET search_path="$user",public;'
     if kind=='ordinary':
      q+='CREATE TABLE '+shadow+'.session_layout_revisions AS SELECT * FROM public.session_layout_revisions;CREATE FUNCTION '+shadow+".bump_session_layout_revisions(text[]) RETURNS void LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'shadow called';END $$;SET search_path="+shadow+',public;'
      target=shadow
     else:
      q+='CREATE TEMP TABLE session_layout_revisions '+('(unexpected int)' if kind=='incompatible' else 'AS SELECT * FROM public.session_layout_revisions')+';';target='pg_temp'
     q+="UPDATE public.session_seats SET price=101 WHERE id='"+seat+"';SELECT revision FROM public.session_layout_revisions WHERE session_id='"+sid+"';"
     if kind!='incompatible':q+="SELECT revision FROM "+target+".session_layout_revisions WHERE session_id='"+sid+"';"
     out=fixture.sql(q+'COMMIT;').splitlines();self.assertEqual(int(out[0]),r+1)
     if kind!='incompatible':self.assertEqual(int(out[1]),r)
     status,body,h=self.get(sid,tag);self.assertEqual(status,200);self.assertNotEqual(h['etag'],tag)
     self.assertEqual(json.loads(body)['seats'][0]['price'],101)
     self.assertEqual(self.get(sid,h['etag'])[:2],(304,b''))
     fixture.sql("UPDATE public.session_seats SET price=100 WHERE id='"+seat+"'")
     self.assertEqual(self.get(sid)[1],before);self.assertNotEqual(self.get(sid)[2]['etag'],tag)
  finally:
   fixture.sql("UPDATE public.session_seats SET price=100 WHERE id='"+seat+"';DROP SCHEMA "+shadow+' CASCADE')
if __name__=='__main__':unittest.main(verbosity=2)
