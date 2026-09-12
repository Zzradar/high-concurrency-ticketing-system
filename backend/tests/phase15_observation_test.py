"""Real query counts and bounded rejection counter accounting."""
import json,re,unittest,urllib.request,uuid
from phase15_test_support import sql,SESSION,until
class ObservationTest(unittest.TestCase):
    def setUp(self):
        from phase15_checkout_test import CheckoutSalesTest
        self.fixture=CheckoutSalesTest();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
    def calls(self):return int(sql("SELECT COALESCE(sum(calls),0) FROM pg_stat_statements WHERE query LIKE '%WITH sales_clock AS MATERIALIZED%' AND query NOT LIKE '%pg_stat_statements%';"))
    def metric(self):
        text=urllib.request.urlopen('http://127.0.0.1:18095/metrics').read().decode()
        result={}
        for labels,value in re.findall(r'^ticketing_sales_window_rejections_total\{([^}]+)\} (\S+)',text,re.M):
            tags=dict(re.findall(r'(\w+)="([^"]*)"',labels));self.assertEqual(set(tags),{'entrypoint','reason'})
            self.assertIn(tags['entrypoint'],['checkout_create','checkout_replace','checkout_confirm','reservation_create']);self.assertIn(tags['reason'],['not_started','ended'])
            result[(tags['entrypoint'],tags['reason'])]=float(value)
        return result
    def test_fixed_gate_count_independent_of_seat_count_and_replay_has_zero(self):
        f=self.fixture
        for labels in [['A01'],['A01','A02','A04','A05','A06','A07']]:
            seats=[SESSION+'-'+x for x in labels];before=self.calls()
            status,checkout,_=f.c.request('/checkout-sessions',method='POST',body={'sessionId':SESSION,'seatIds':seats});self.assertEqual(status,201,checkout);self.assertEqual(self.calls()-before,1)
            before=self.calls();status,updated,_=f.replace(checkout,seats);self.assertEqual(status,200,updated);self.assertEqual(self.calls()-before,1)
            before=self.calls();status,result,_=f.confirm(updated);self.assertEqual(status,200,result);self.assertEqual(self.calls()-before,3)
            before=self.calls();status,replay,_=f.confirm(updated);self.assertEqual(status,200,replay);self.assertEqual(self.calls()-before,0)
            status,body,_=f.c.request('/orders/'+result['checkoutSession']['order']['id']+'/cancel',method='POST');self.assertEqual(status,200,body)
        key='p15-observation-'+uuid.uuid4().hex;before=self.calls();status,body,_=f.reserve(key);self.assertEqual(status,201,body);self.assertEqual(self.calls()-before,2)
        before=self.calls();status,body,_=f.reserve(key);self.assertEqual(status,200,body);self.assertEqual(self.calls()-before,0)
    def test_only_external_entrypoint_is_counted_once(self):
        f=self.fixture;_,checkout,_=f.create();f.window('ENDED');before=self.metric()
        for action in [f.create,lambda:f.replace(checkout,[f.seat]),lambda:f.confirm(checkout),lambda:f.reserve('p15-metrics')]:
            status,body,_=action();self.assertEqual((status,body['code']),(409,'SALES_ENDED'))
        # PromExporter caches its HTTP exposition briefly; wait for publication, then assert exact deltas.
        entries=['checkout_create','checkout_replace','checkout_confirm','reservation_create']
        def published():
            value=self.metric()
            return value if all(value.get((entry,'ended'),0)>before.get((entry,'ended'),0) for entry in entries) else None
        after=until(published)
        for entry in ['checkout_create','checkout_replace','checkout_confirm','reservation_create']:
            key=(entry,'ended');self.assertEqual(after.get(key,0)-before.get(key,0),1)
if __name__=='__main__':unittest.main(verbosity=2)
