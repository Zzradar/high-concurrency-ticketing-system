"""Conditional public layout cache, real SQL-count and visibility gates."""
import hashlib,json,os,unittest,urllib.request,urllib.error,uuid
import phase18_admission_http_test as fixture

class LayoutHTTP(unittest.TestCase):
 setUp=fixture.AdmissionHTTP.setUp
 def get(self,session,tag=None):
  request=urllib.request.Request(os.environ['PHASE18_BASE_URL']+'/sessions/'+session+'/seat-layout',headers={} if tag is None else {'If-None-Match':tag})
  try:r=urllib.request.urlopen(request,timeout=10)
  except urllib.error.HTTPError as e:r=e
  with r:return r.status,r.read(),dict((k.lower(),v) for k,v in r.headers.items())
 def test_conditional_body_sql_and_distinct_identity(self):
  status,body,headers=self.get(self.s);self.assertEqual(status,200)
  tag=headers['etag'];self.assertRegex(tag,r'^W/"seat-layout-v2-[0-9a-f]{64}"$');self.assertNotIn(self.s,tag)
  self.assertIn('public, max-age=60',headers['cache-control']);self.assertIn('Accept-Encoding',headers['vary'])
  self.assertNotIn('immutable',headers['cache-control'])
  before=fixture.sql("SELECT coalesce(sum(calls),0)::bigint FROM pg_stat_statements WHERE query LIKE '%FROM session_seats AS inventory%' AND query LIKE '%seat.seat_label%' AND query NOT ILIKE '%pg_stat_statements%'")
  for match in [tag,tag[2:],'"wrong", '+tag,'*',' W/"comma,inside", '+tag]:
   status,empty,h=self.get(self.s,match);self.assertEqual(status,304);self.assertEqual(empty,b'');self.assertEqual(h['etag'],tag);self.assertEqual(h['cache-control'],headers['cache-control'])
  after=fixture.sql("SELECT coalesce(sum(calls),0)::bigint FROM pg_stat_statements WHERE query LIKE '%FROM session_seats AS inventory%' AND query LIKE '%seat.seat_label%' AND query NOT ILIKE '%pg_stat_statements%'")
  self.assertEqual(before,after,'304 must execute zero full-layout SQL calls')
  for mismatch in ['"wrong"',tag+',',tag+' garbage']:
   status,again,h=self.get(self.s,mismatch);self.assertEqual(status,200);self.assertEqual(hashlib.sha256(again).digest(),hashlib.sha256(body).digest())
  parsed=json.loads(body);self.assertEqual(parsed['sessionId'],self.s);self.assertEqual(parsed['seats'],self.seats)
  other=fixture.sql("SELECT s.id FROM sessions s JOIN events e ON e.id=s.event_id WHERE s.id<>'"+self.s+"' AND s.status<>'DRAFT' AND e.status<>'DRAFT' ORDER BY s.id LIMIT 1")
  self.assertNotEqual(self.get(other)[2]['etag'],tag)
  print('Conditional layout: five 304, empty bodies, full-layout SQL delta=0; unchanged 200 body hash='+hashlib.sha256(body).hexdigest())
 def test_snapshot_delta_poll_hints_and_dynamic_no_store(self):
  import subprocess
  from urllib.parse import urlencode
  path='/sessions/'+self.s+'/seat-availability?zone=A'
  status,snapshot,headers=self.u.request(path);self.assertEqual(status,200)
  self.assertIs(type(snapshot['pollAfterMs']),int);self.assertEqual(snapshot['pollAfterMs'],2000)
  cursor=urlencode({'generation':snapshot['generation'],'since':snapshot['cursor']})
  status,delta,headers=self.u.request(path+'&'+cursor);self.assertEqual(status,200);self.assertEqual(delta['mode'],'delta');self.assertEqual(delta['changes'],[]);self.assertEqual(delta['pollAfterMs'],5000)
  self.assertIn('no-store',headers.get('Cache-Control',headers.get('cache-control','')))
  for resource in ['/events/'+self.e,'/sessions/'+self.s]:
   _,_,dynamicHeaders=self.u.request(resource)
   self.assertIn('no-store',dynamicHeaders.get('Cache-Control',dynamicHeaders.get('cache-control','')))
  subprocess.run(['docker','stop',fixture.REDIS],capture_output=True,check=True)
  try:
   status,degraded,_=fixture.anonymous_request(path);self.assertEqual(status,200,degraded)
   self.assertTrue(degraded['degraded']);self.assertEqual(degraded['pollAfterMs'],10000);self.assertIs(type(degraded['pollAfterMs']),int)
  finally:subprocess.run(['docker','start',fixture.REDIS],capture_output=True,check=True)
 def test_draft_and_absent_never_validate_even_with_forged_redis(self):
  venue=self.a.request('/admin/venues',method='POST',body={'name':'Cache '+uuid.uuid4().hex,'city':'Shanghai','zones':[{'code':'A','name':'A','rows':[{'label':'A','seatCount':1}]}]})[1]
  event=self.a.request('/admin/events',method='POST',body={'name':'Draft cache','description':'','category':'Test','coverUrl':'/images/concert-cover.png','venueId':venue['id'],'salesStartsAt':fixture.instant(-1),'salesEndsAt':fixture.instant(3)})[1]
  session=self.a.request('/admin/events/'+event['id']+'/sessions',method='POST',body={'hallName':'H','startTime':fixture.instant(2),'gateTime':fixture.instant(1)})[1]['savedSessionId']
  fixture.redis('HSET','ticketing:seat-availability:{'+session+'}:meta','ready','1','generation','forged')
  fixture.redis('EXPIRE','ticketing:seat-availability:{'+session+'}:meta',60)
  tag=self.get(self.s)[2]['etag']
  for sid in [session,'P18-ABSENT-'+uuid.uuid4().hex]:
   for candidate in ['*',tag]:
    status,body,headers=self.get(sid,candidate);self.assertEqual(status,404);self.assertEqual(json.loads(body)['code'],'SESSION_NOT_FOUND');self.assertIn('no-store',headers['cache-control']);self.assertNotIn('etag',headers)
if __name__=='__main__':unittest.main(verbosity=2)
