"""Direct PostgreSQL changes must invalidate a public Layout validator."""
import json, unittest, hashlib, concurrent.futures, urllib.request, urllib.error, gzip
import phase18_admission_http_test as fixture
import phase18_layout_http_test as layout_fixture

class LayoutRevisionHTTP(unittest.TestCase):
 setUp=fixture.AdmissionHTTP.setUp
 get=layout_fixture.LayoutHTTP.get
 def revision(self):
  return int(fixture.sql("SELECT revision FROM session_layout_revisions WHERE session_id='"+self.s+"'"))
 def changed(self,q,body_changes=True):
  _,before,h=self.get(self.s);old=h['etag'];revision=self.revision()
  fixture.sql(q)
  status,body,h=self.get(self.s,old);self.assertEqual(status,200);self.assertNotEqual(h['etag'],old)
  if body_changes:self.assertNotEqual(json.loads(body),json.loads(before))
  self.assertEqual(self.revision(),revision+1)
  self.assertEqual(self.get(self.s,h['etag'])[0],304)
 def test_direct_price_changes_body_and_validator(self):
  status,body,headers=self.get(self.s);self.assertEqual(status,200)
  old=headers['etag'];seat=self.seats[0]['id']
  fixture.sql("UPDATE session_seats SET price=101 WHERE id='"+seat+"'")
  status,body,new=self.get(self.s);self.assertEqual(status,200)
  self.assertEqual(next(x['price'] for x in json.loads(body)['seats'] if x['id']==seat),101)
  self.assertNotEqual(new['etag'],old,'Direct PostgreSQL price correction must change ETag')
  status,body,h=self.get(self.s,old);self.assertEqual(status,200)
  self.assertEqual(h['etag'],new['etag'])
  self.assertEqual(next(x['price'] for x in json.loads(body)['seats'] if x['id']==seat),101)
  status,body,h=self.get(self.s,new['etag']);self.assertEqual(status,304);self.assertEqual(body,b'')

 def test_static_columns_and_inventory_membership(self):
  seat=self.seats[0]['id'];sid=fixture.sql("SELECT seat_id FROM session_seats WHERE id='"+seat+"'")
  zid=fixture.sql("SELECT zone_id FROM seats WHERE id='"+sid+"'")
  venue=fixture.sql("SELECT venue_id FROM seats WHERE id='"+sid+"'")
  for update in ["seat_label=seat_label||'-fixed'","row_no='ZZ'","seat_no=500"]:
   with self.subTest(update=update):self.changed("UPDATE seats SET "+update+" WHERE id='"+sid+"'")
  self.changed("UPDATE venue_zones SET name=name||' corrected' WHERE id='"+zid+"'")
  fixture.sql("INSERT INTO venue_zones(id,venue_id,code,name,sort_order) VALUES('"+zid+"-new','"+venue+"','B','B',1)")
  self.changed("UPDATE seats SET zone_id='"+zid+"-new' WHERE id='"+sid+"'")
  self.changed("UPDATE venue_zones SET sort_order=2 WHERE id='"+zid+"'")
  self.changed("UPDATE session_seats SET id=id||'-fixed' WHERE id='"+seat+"'")
  seat+='-fixed'
  fixture.sql("INSERT INTO seats(id,venue_id,zone_id,row_no,seat_no,seat_label) VALUES('"+sid+"-new','"+venue+"','"+zid+"','X',501,'X501')")
  self.changed("INSERT INTO session_seats(id,session_id,seat_id,venue_id,status,price) VALUES('"+seat+"-new','"+self.s+"','"+sid+"-new','"+venue+"','AVAILABLE',123)")
  self.changed("DELETE FROM session_seats WHERE id='"+seat+"-new'")
  self.changed("UPDATE session_seats SET seat_id='"+sid+"-new' WHERE id='"+seat+"'")
  self.changed("UPDATE session_seats SET seat_id='"+sid+"' WHERE id='"+seat+"'")
  # Deleting an unreferenced static Seat does not change any Layout representation.
  r=self.revision();fixture.sql("DELETE FROM seats WHERE id='"+sid+"-new'");self.assertEqual(self.revision(),r)

 def test_noop_dynamic_and_unrepresented_fields_do_not_bump(self):
  r=self.revision();tag=self.get(self.s)[2]['etag']
  fixture.sql("UPDATE session_seats SET price=price,status=status,formal_version=formal_version+1 WHERE session_id='"+self.s+"'; UPDATE sessions SET hall_name=hall_name||' changed' WHERE id='"+self.s+"'; UPDATE seats SET seat_label=seat_label WHERE id IN(SELECT seat_id FROM session_seats WHERE session_id='"+self.s+"')")
  self.assertEqual(self.revision(),r);self.assertEqual(self.get(self.s,tag)[0],304)
  fixture.sql("UPDATE session_seats SET status='SOLD' WHERE session_id='"+self.s+"'")
  self.assertEqual(self.revision(),r);self.assertEqual(self.get(self.s,tag)[0],304)
  fixture.sql("UPDATE session_seats SET status='AVAILABLE' WHERE session_id='"+self.s+"'")

 def test_batch_and_transaction_failures_are_atomic(self):
  r=self.revision();self.changed("UPDATE session_seats SET price=price+1 WHERE session_id='"+self.s+"'");self.assertEqual(self.revision(),r+1)
  _,before,headers=self.get(self.s);tag=headers['etag'];r=self.revision()
  fixture.sql("BEGIN;UPDATE session_seats SET price=price+1 WHERE session_id='"+self.s+"';ROLLBACK;")
  self.assertEqual(self.get(self.s)[1],before);self.assertEqual(self.get(self.s)[2]['etag'],tag);self.assertEqual(self.revision(),r)
  fixture.sql("CREATE FUNCTION p18_late_layout_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'late layout test failure'; END $$; CREATE TRIGGER zz_p18_late_layout_failure AFTER UPDATE ON session_layout_revisions FOR EACH STATEMENT EXECUTE FUNCTION p18_late_layout_failure()")
  try:
   with self.assertRaises(AssertionError):fixture.sql("UPDATE session_seats SET price=price+1 WHERE session_id='"+self.s+"'")
  finally:fixture.sql('DROP TRIGGER zz_p18_late_layout_failure ON session_layout_revisions;DROP FUNCTION p18_late_layout_failure()')
  self.assertEqual(self.get(self.s)[1],before);self.assertEqual(self.get(self.s)[2]['etag'],tag);self.assertEqual(self.revision(),r)

 def test_concurrent_body_tag_snapshot(self):
  seat=self.seats[0]['id']
  identity=json.loads(fixture.sql("SELECT json_build_array(s.id,s.venue_id,((extract(epoch FROM s.created_at)*1000000)::bigint)::text,coalesce((extract(epoch FROM e.published_at)*1000000)::bigint,0)::text) FROM sessions s JOIN events e ON e.id=s.event_id WHERE s.id='"+self.s+"'"))
  def expected(revision):
   text='seat-layout-v2'+''.join(str(len(v))+':'+v for v in identity+[str(revision)])
   return 'W/"seat-layout-v2-'+hashlib.sha256(text.encode()).hexdigest()+'"'
  versions={100:expected(self.revision())}
  def writer():
   for price in range(201,225):
    r=fixture.sql("BEGIN;UPDATE session_seats SET price="+str(price)+" WHERE id='"+seat+"';SELECT revision FROM session_layout_revisions WHERE session_id='"+self.s+"';COMMIT;")
    versions[price]=expected(int(r))
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
   future=pool.submit(writer);responses=[self.get(self.s) for _ in range(70)];future.result()
  for status,body,h in responses:
   self.assertEqual(status,200)
   price=next(x['price'] for x in json.loads(body)['seats'] if x['id']==seat)
   self.assertEqual(h['etag'],versions[price],(price,h['etag']))

 def test_v1_gzip_and_empty_layout(self):
  tag=self.get(self.s)[2]['etag'];self.assertEqual(self.get(self.s,tag.replace('v2','v1'))[0],200)
  request=urllib.request.Request(fixture.os.environ['PHASE18_BASE_URL']+'/sessions/'+self.s+'/seat-layout',headers={'Accept-Encoding':'gzip'})
  with urllib.request.urlopen(request) as r:
   raw=r.read();raw=gzip.decompress(raw) if r.headers.get('Content-Encoding')=='gzip' else raw
   self.assertEqual(json.loads(raw)['seats'],self.seats);self.assertEqual(r.headers['ETag'],tag)
  self.changed("DELETE FROM session_seats WHERE session_id='"+self.s+"'")
  status,body,h=self.get(self.s);self.assertEqual(json.loads(body)['seats'],[]);self.assertEqual(self.get(self.s,h['etag'])[0],304)
 def test_session_relationship_identity_and_cross_venue(self):
  self.changed("UPDATE sessions SET created_at=created_at+interval '1 second' WHERE id='"+self.s+"'",False)
  old=self.get(self.s)[2]['etag']
  fixture.sql("UPDATE events SET published_at=published_at+interval '1 second' WHERE id='"+self.e+"'")
  self.assertEqual(self.get(self.s,old)[0],200)
  other=self.s+'-copy'
  fixture.sql("INSERT INTO sessions(id,event_id,venue_id,hall_name,start_time,gate_time,status,created_at) SELECT '"+other+"',event_id,venue_id,hall_name,start_time,gate_time,status,created_at FROM sessions WHERE id='"+self.s+"'")
  r=self.revision();other_r=int(fixture.sql("SELECT revision FROM session_layout_revisions WHERE session_id='"+other+"'"))
  old=self.get(self.s)[2]['etag'];empty=self.get(other)[2]['etag'];seat=self.seats[0]['id']
  fixture.sql("UPDATE session_seats SET session_id='"+other+"' WHERE id='"+seat+"'")
  self.assertEqual(self.revision(),r+1)
  self.assertEqual(int(fixture.sql("SELECT revision FROM session_layout_revisions WHERE session_id='"+other+"'")),other_r+1)
  self.assertEqual(self.get(self.s,old)[0],200)
  status,body,h=self.get(other,empty);self.assertEqual(status,200);self.assertEqual(json.loads(body)['seats'][0]['id'],seat)
  foreign=fixture.sql("SELECT id FROM venues WHERE id<>(SELECT venue_id FROM sessions WHERE id='"+other+"') ORDER BY id LIMIT 1")
  with self.assertRaises(AssertionError):fixture.sql("UPDATE session_seats SET venue_id='"+foreign+"' WHERE id='"+seat+"'")
  self.assertEqual(self.get(other,h['etag'])[0],304)
  fixture.sql("UPDATE sessions SET status='DRAFT' WHERE id='"+other+"'")
  status,body,h=self.get(other,'*');self.assertEqual(status,404);self.assertNotIn('etag',h)

if __name__=='__main__':unittest.main(verbosity=2)
