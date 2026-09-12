"""Checkout gates use real HTTP, PG and Redis on the dedicated Phase15 stack."""
import time, unittest, uuid
from phase15_reservation_test import ReservationSalesTest
from phase15_test_support import sql, redis, until, SESSION, EVENT
class CheckoutSalesTest(ReservationSalesTest):
    # Reuse fixture lifecycle, not inherited Reservation test cases.
    def create(self):
        return self.c.request('/checkout-sessions',method='POST',body={'sessionId':SESSION,'seatIds':[self.seat]})
    def replace(self,checkout,seats):
        return self.c.request('/checkout-sessions/'+checkout['id']+'/seats',method='PUT',body={'seatIds':seats,'expectedRevision':checkout['revision']})
    def confirm(self,checkout):
        return self.c.request('/checkout-sessions/'+checkout['id']+'/confirm',method='POST')
    def key(self):return 'ticketing:seat-hold:{'+SESSION+'}:'+self.seat
    def restore(self):
        for checkout in sql("SELECT id FROM checkout_sessions WHERE user_id='"+self.user+"' AND status='SELECTING';").splitlines():
            self.c.request('/checkout-sessions/'+checkout+'/abandon',method='POST')
        super().restore()
        value=redis('GET',self.key())
        if value and sql("SELECT count(*) FROM checkout_sessions WHERE user_id='"+self.user+"' AND id='"+value.split('|')[0]+"';")=='1':redis('DEL',self.key())
    def test_checkout_create_both_closed_states_no_hold(self):
        for state,code in [('NOT_STARTED','SALES_NOT_STARTED'),('ENDED','SALES_ENDED')]:
            self.window(state);status,body,_=self.create();self.assertEqual((status,body['code']),(409,code));self.assertIsNone(redis('GET',self.key()))
        self.assertEqual(sql("SELECT count(*) FROM checkout_sessions WHERE user_id='"+self.user+"';"),'0')
    def test_replace_rejection_preserves_revision_and_ttl_empty_release_allowed(self):
        status,checkout,_=self.create();self.assertEqual(status,201,checkout)
        before=redis('PTTL',self.key());self.window('ENDED')
        status,body,_=self.replace(checkout,[self.seat,self.other]);self.assertEqual((status,body['code']),(409,'SALES_ENDED'))
        self.assertLessEqual(redis('PTTL',self.key()),before)
        self.assertEqual(sql("SELECT revision FROM checkout_sessions WHERE id='"+checkout['id']+"';"),'0')
        status,body,_=self.replace(checkout,[]);self.assertEqual(status,200,body);self.assertEqual(body['seatIds'],[]);self.assertIsNone(redis('GET',self.key()))
    def test_selecting_confirm_closes_and_releases_hold(self):
        _,checkout,_=self.create();self.window('ENDED')
        status,body,_=self.confirm(checkout);self.assertEqual((status,body['code']),(409,'SALES_ENDED'))
        self.assertEqual(sql("SELECT status FROM checkout_sessions WHERE id='"+checkout['id']+"';"),'ABANDONED');self.assertIsNone(redis('GET',self.key()));self.assert_no_writes()
    def test_submitting_without_formal_result_closes_with_fenced_key(self):
        _,checkout,_=self.create()
        sql("UPDATE checkout_sessions SET status='SUBMITTING',active_confirm_idempotency_key='p15-frozen' WHERE id='"+checkout['id']+"';")
        self.window('ENDED');status,body,_=self.confirm(checkout);self.assertEqual((status,body['code']),(409,'SALES_ENDED'))
        self.assertEqual(sql("SELECT status||'|'||(active_confirm_idempotency_key IS NULL) FROM checkout_sessions WHERE id='"+checkout['id']+"';"),'ABANDONED|true');self.assertIsNone(redis('GET',self.key()));self.assert_no_writes()
    def test_submitting_formal_replay_and_reserved_confirm_after_end(self):
        _,checkout,_=self.create();key='p15-frozen-'+uuid.uuid4().hex
        sql("UPDATE checkout_sessions SET status='SUBMITTING',active_confirm_idempotency_key='"+key+"' WHERE id='"+checkout['id']+"';")
        status,formal,_=self.reserve(key);self.assertEqual(status,201,formal)
        self.window('ENDED');status,body,_=self.confirm(checkout);self.assertEqual(status,200,body)
        self.assertEqual(body['checkoutSession']['reservation']['id'],formal['reservation']['id'])
        status,replay,_=self.confirm(checkout);self.assertEqual(status,200,replay);self.assertEqual(replay['checkoutSession']['order']['id'],formal['order']['id'])
        self.assertEqual(sql("SELECT count(*) FROM reservations WHERE user_id='"+self.user+"';"),'1')
    def test_natural_expiry_converges_phase16_derived_model(self):
        status,layout,_=self.c.request('/sessions/'+SESSION+'/seat-layout');self.assertEqual(status,200,layout)
        zone=next(x['zone'] for x in layout['seats'] if x['id']==self.seat)
        path='/sessions/'+SESSION+'/seat-availability?zone='+__import__('urllib.parse',fromlist=['quote']).quote(zone)
        status,body,_=self.c.request(path);self.assertEqual(status,200,body)
        sql("UPDATE events SET sales_ends_at=clock_timestamp()+interval '5 seconds' WHERE id='"+EVENT+"';")
        status,checkout,_=self.create();self.assertEqual(status,201,checkout)
        prefix='ticketing:seat-availability:{'+SESSION+'}'
        # Read clock, PTTL and derived expiry atomically, excluding Docker CLI transport latency.
        inspect="local t=redis.call('TIME');local h=redis.call('HGET',KEYS[2],ARGV[1]) or '';local e=tonumber(string.match(h,'(%d+)$')) or 0;return {h,redis.call('PTTL',KEYS[1]),e-(tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000))}"
        derived,ttl,remaining=redis('EVAL',inspect,2,self.key(),prefix+':holds',self.seat)
        self.assertTrue(derived.startswith(checkout['id']+'|0|'),derived)
        self.assertGreater(ttl,0);self.assertLessEqual(ttl,5000);self.assertLessEqual(abs(remaining-ttl),2)
        until(lambda:redis('EXISTS',self.key())==0,seconds=8)
        self.assertIsNone(redis('GET',self.key()))
        status,body,_=self.c.request(path);self.assertEqual(status,200,body)
        self.assertIsNone(redis('HGET',prefix+':holds',self.seat))
        self.assertEqual(next(x['status'] for x in body['seats'] if x['id']==self.seat),'AVAILABLE')

    def test_millisecond_ttl_bounded_by_window_and_default(self):
        sql("UPDATE events SET sales_ends_at=clock_timestamp()+interval '120 seconds' WHERE id='"+EVENT+"';")
        status,checkout,_=self.create();self.assertEqual(status,201,checkout)
        ttl=redis('PTTL',self.key());self.assertGreater(ttl,110000);self.assertLessEqual(ttl,120000)
        self.window('OPEN');status,body,_=self.replace(checkout,[self.seat]);self.assertEqual(status,200,body)
        ttl=redis('PTTL',self.key());self.assertGreater(ttl,290000);self.assertLessEqual(ttl,300000)
# Avoid duplicating the independent Reservation suite in unittest discovery.
for name in list(vars(ReservationSalesTest)):
    if name.startswith('test_'):setattr(CheckoutSalesTest,name,None)
del ReservationSalesTest
if __name__=='__main__':unittest.main(verbosity=2)
