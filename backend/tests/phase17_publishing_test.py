import copy,time,unittest,uuid
from datetime import datetime,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor
from phase17_http_test import AuthenticatedClient,anonymous_request,sql,redis,command,setUpModule,REDIS
from phase17_venue_test import plan

def instant(hours):return (datetime.now(timezone.utc)+timedelta(hours=hours)).isoformat(timespec='milliseconds').replace('+00:00','Z')
class PublishingTest(unittest.TestCase):
    def setUp(self):self.a=AuthenticatedClient('admin');self.a.login()
    def call(self,path,method='GET',body=None,status=200):
        code,result,_=self.a.request(path,method=method,body=body);self.assertEqual(code,status,result);return result
    def draft(self,sessions=1,prices=True):
        v=self.call('/admin/venues','POST',plan(),201)
        b={'name':'P17 '+uuid.uuid4().hex,'description':'测试','category':'演唱会','coverUrl':'/images/concert-cover.png','venueId':v['id'],'salesStartsAt':instant(-1),'salesEndsAt':instant(24)}
        e=self.call('/admin/events','POST',b,201)
        for i in range(sessions):
            e=self.call('/admin/events/'+e['id']+'/sessions','POST',{'hallName':'主场馆','startTime':instant(12+i),'gateTime':instant(10+i)},201)
            sid=e['savedSessionId']
            if prices:e=self.call('/admin/events/'+e['id']+'/sessions/'+sid+'/prices','PUT',{'prices':[{'zoneId':z['id'],'price':10000*(n+1)} for n,z in enumerate(v['zones'])]})
        return v,e,b
    def test_draft_hidden_at_every_public_entry_and_checkout(self):
        v,e,b=self.draft();eid=e['id'];sid=e['sessions'][0]['id']
        self.assertNotIn(eid,[x['id'] for x in anonymous_request('/events')[1]])
        for path in ['/events/'+eid,'/events/'+eid+'/sessions','/sessions/'+sid,'/sessions/'+sid+'/seat-layout','/sessions/'+sid+'/seats','/sessions/'+sid+'/seat-availability','/sessions/'+sid+'/seat-availability?zone=内场']:
            from urllib.parse import quote
            self.assertEqual(anonymous_request(quote(path,safe='/?=&'))[0],404,path)
        self.assertEqual(AuthenticatedClient().request('/checkout-sessions',method='POST',body={'sessionId':sid,'seatIds':['missing']})[0],409)
        self.assertEqual(self.call('/admin/events/'+eid)['status'],'DRAFT')
    def test_preview_partial_prices_and_validation(self):
        v,e,b=self.draft(prices=False);root='/admin/events/'+e['id'];sid=e['sessions'][0]['id']
        p=self.call(root+'/publish-preview');self.assertFalse(p['publishable']);self.assertEqual({x['code'] for x in p['issues']},{'ZONE_PRICE_MISSING'})
        self.call(root+'/publish','POST',status=409)
        self.call(root+'/sessions/'+sid+'/prices','PUT',{'prices':[{'zoneId':v['zones'][0]['id'],'price':100}]})
        self.assertFalse(self.call(root+'/publish-preview')['publishable'])
        for price in [0,-1,True,1.5,1.0,9223372036854775808]:self.call(root+'/sessions/'+sid+'/prices','PUT',{'prices':[{'zoneId':v['zones'][0]['id'],'price':price}]},400)
        self.call(root+'/sessions/'+sid+'/prices','PUT',{'prices':[{'zoneId':'unknown','price':100}]},400)
        repeated={'zoneId':v['zones'][0]['id'],'price':100};self.call(root+'/sessions/'+sid+'/prices','PUT',{'prices':[repeated,repeated]},400)
        self.call(root+'/sessions','POST',{'hallName':'H','startTime':instant(3),'gateTime':instant(4)},400)
        self.call(root+'/sessions','POST',{'hallName':'H','startTime':instant(-2),'gateTime':instant(-3)},400)
        v2=self.call('/admin/venues','POST',plan(),201);b['venueId']=v2['id'];self.assertEqual(self.call(root,'PUT',b,409)['code'],'EVENT_VENUE_LOCKED')
        self.call(root+'/sessions/'+sid,'PUT',{'hallName':'新馆','startTime':instant(20),'gateTime':instant(18)})
        self.call(root+'/sessions/'+sid,'DELETE');self.assertEqual(self.call(root+'/publish-preview')['issues'][0]['code'],'NO_SESSIONS')
        self.call(root,'PUT',b)
    def test_multiple_sessions_publish_counts_prices_and_audit(self):
        v,e,b=self.draft(2);eid=e['id'];root='/admin/events/'+eid
        self.assertTrue(self.call(root+'/publish-preview')['publishable'])
        result=self.call(root+'/publish','POST');self.assertEqual(result['disposition'],'PUBLISHED_NOW');self.assertEqual(result['inventory']['sessionSeatCount'],14)
        self.assertEqual(result['event']['publishedBy'],'U-ADMIN-DEMO');self.assertIsNotNone(result['event']['publishedAt']);self.assertTrue(result['event']['dateRange'])
        self.assertEqual(sql(f"SELECT count(*) FROM session_seats i JOIN sessions s ON s.id=i.session_id WHERE s.event_id='{eid}' AND (i.status<>'AVAILABLE' OR i.formal_version<>0 OR i.current_reservation_id IS NOT NULL);"),'0')
        self.assertEqual(sql(f"SELECT count(*) FROM session_seats i JOIN sessions s ON s.id=i.session_id JOIN seats seat ON seat.id=i.seat_id JOIN session_zone_prices p ON p.session_id=s.id AND p.zone_id=seat.zone_id WHERE s.event_id='{eid}' AND i.price<>p.price;"),'0')
        self.assertEqual(sql(f"SELECT count(*) FROM seat_availability_outbox o JOIN sessions s ON s.id=o.session_id WHERE s.event_id='{eid}';"),'0')
        self.assertEqual(self.call(root+'/publish','POST')['disposition'],'ALREADY_PUBLISHED')
        self.assertEqual(anonymous_request('/events/'+eid)[0],200)
        self.call(root,'PUT',b,409);self.call('/admin/venues/'+v['id'],'PUT',plan(),409)
        sid=e['sessions'][0]['id'];self.call(root+'/sessions/'+sid,'DELETE',status=409);self.call(root+'/sessions/'+sid+'/prices','PUT',{'prices':[]},409)
        self.assertEqual(self.call(root+'/display','PATCH',{'name':'新标题'})['name'],'新标题');self.call(root+'/display','PATCH',{'salesEndsAt':instant(100)},400)
    def test_concurrent_publish_is_exactly_once(self):
        v,e,b=self.draft(2);path='/admin/events/'+e['id']+'/publish'
        clients=[AuthenticatedClient('admin'),AuthenticatedClient('admin')]
        for c in clients:c.login()
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda c:c.request(path,method='POST'),clients))
        self.assertEqual([x[0] for x in results],[200,200]);self.assertEqual(sorted(x[1]['disposition'] for x in results),['ALREADY_PUBLISHED','PUBLISHED_NOW'])
        self.assertEqual(sql("SELECT count(*) FROM session_seats i JOIN sessions s ON s.id=i.session_id WHERE s.event_id='"+e['id']+"';"),'14')
    def test_update_failure_rolls_back_inventory_and_audit(self):
        v,e,b=self.draft();eid=e['id']
        sql(f"CREATE FUNCTION p17_fail_publish() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.id='{eid}' AND NEW.status='ON_SALE' THEN RAISE EXCEPTION 'test rollback'; END IF; RETURN NEW; END $$; CREATE TRIGGER p17_fail_publish BEFORE UPDATE ON events FOR EACH ROW EXECUTE FUNCTION p17_fail_publish();")
        try:
            self.call('/admin/events/'+eid+'/publish','POST',status=500)
            self.assertEqual(sql(f"SELECT status||'|'||(published_at IS NULL)::text||'|'||(published_by IS NULL)::text FROM events WHERE id='{eid}';"),'DRAFT|true|true')
            self.assertEqual(sql(f"SELECT count(*) FROM session_seats i JOIN sessions s ON s.id=i.session_id WHERE s.event_id='{eid}';"),'0')
            self.assertEqual(self.call('/admin/events/'+eid)['sessions'][0]['status'],'DRAFT')
        finally:sql('DROP TRIGGER p17_fail_publish ON events; DROP FUNCTION p17_fail_publish();')
        self.call('/admin/events/'+eid+'/publish','POST')
    def test_future_window_published_but_checkout_blocked_and_ended_rejected(self):
        v,e,b=self.draft();root='/admin/events/'+e['id'];b['salesStartsAt']=instant(1);self.call(root,'PUT',b);result=self.call(root+'/publish','POST');sid=result['event']['sessions'][0]['id']
        self.assertEqual(anonymous_request('/events/'+e['id'])[1]['salesWindow']['state'],'NOT_STARTED')
        seat=anonymous_request('/sessions/'+sid+'/seat-layout')[1]['seats'][0]['id']
        self.assertEqual(AuthenticatedClient().request('/checkout-sessions',method='POST',body={'sessionId':sid,'seatIds':[seat]})[1]['code'],'SALES_NOT_STARTED')
        v,e,b=self.draft();b['salesStartsAt']=instant(-3);b['salesEndsAt']=instant(-2);root='/admin/events/'+e['id'];self.call(root,'PUT',b)
        self.assertIn('EVENT_WINDOW_ENDED',[x['code'] for x in self.call(root+'/publish-preview')['issues']]);self.call(root+'/publish','POST',status=409)
    def test_publish_does_not_depend_on_redis(self):
        v,e,b=self.draft();command(['docker','stop',REDIS])
        try:self.assertEqual(self.call('/admin/events/'+e['id']+'/publish','POST')['disposition'],'PUBLISHED_NOW')
        finally:command(['docker','start',REDIS]);time.sleep(.5)
if __name__=='__main__':unittest.main(verbosity=2)
