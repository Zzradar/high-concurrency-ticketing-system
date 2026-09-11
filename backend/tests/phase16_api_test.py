"""HTTP gate for the isolated Phase16 API stack on localhost:18096."""
import os
os.environ['TICKETING_BASE_URL']=os.environ.get('PHASE16_BASE_URL','http://127.0.0.1:18096')
import json
import subprocess
import time
import unittest
import uuid
from urllib.parse import urlencode
from auth_test_support import AuthenticatedClient, anonymous_request, test_user_values, username_for_user

SESSION='ses-concert-1001'

def sql(statement):
    r=subprocess.run(['docker','exec','-i','phase16-api-postgres','psql','-U','postgres','-qAt','-v','ON_ERROR_STOP=1'],input=statement,text=True,encoding='utf-8',capture_output=True)
    if r.returncode:raise AssertionError(r.stderr)
    return r.stdout.strip()

class AvailabilityApiTest(unittest.TestCase):
    def setUp(self):
        status,layout,_=anonymous_request('/sessions/'+SESSION+'/seat-layout')
        self.assertEqual(status,200)
        self.layout=layout['seats'];self.zone=self.layout[0]['zone']

    def get(self,session=SESSION,client=None,**params):
        path='/sessions/'+session+'/seat-availability'+('?' + urlencode(params) if params else '')
        status,body,_=(client.request(path) if client else anonymous_request(path))
        return status,body

    def test_legacy_snapshot_delta_zone_isolation(self):
        status,legacy=self.get();self.assertEqual(status,200)
        self.assertEqual(set(legacy),{'sessionId','seats'})
        status,snap=self.get(zone=self.zone);self.assertEqual(status,200)
        self.assertEqual(snap['mode'],'snapshot');self.assertFalse(snap['degraded'])
        ids={s['id'] for s in self.layout if s['zone']==self.zone}
        self.assertEqual({s['id'] for s in snap['seats']},ids)
        status,delta=self.get(zone=self.zone,generation=snap['generation'],since=snap['cursor'])
        self.assertEqual(status,200);self.assertEqual(delta['mode'],'delta')
        self.assertEqual(delta['changes'],[]);self.assertEqual(delta['cursor'],snap['cursor'])
        self.assertEqual(sum(z['total'] for z in snap['zones']),len(self.layout))

    def test_argument_errors(self):
        for params in ({'generation':'x'},{'since':'1-0'},{'generation':'x','since':'abc'},
                       {'generation':'x','since':'-1-0'},{'generation':'x','since':'18446744073709551616-0'}):
            status,body=self.get(zone=self.zone,**params)
            self.assertEqual((status,body['code']),(400,'INVALID_ARGUMENT'))
        self.assertEqual(self.get(zone='not-a-zone')[1]['code'],'ZONE_NOT_FOUND')
        self.assertEqual(self.get(session='missing',zone=self.zone)[1]['code'],'SESSION_NOT_FOUND')

    def test_generation_reset(self):
        status,body=self.get(zone=self.zone,generation='old',since='1-0')
        self.assertEqual(status,200);self.assertEqual(body['mode'],'snapshot');self.assertTrue(body['reset'])

    def test_ownership_and_hold_delta(self):
        users=['P16-'+uuid.uuid4().hex[:10] for _ in range(2)]
        sql('INSERT INTO app_users(id,display_name,username,password_hash,status) VALUES '+test_user_values(users)+';')
        a,b=[AuthenticatedClient(username_for_user(u)) for u in users]
        a.login();b.login()
        _,snap=self.get(zone=self.zone)
        seat=next(s['id'] for s in snap['seats'] if s['status']=='AVAILABLE')
        status,checkout,_=a.request('/checkout-sessions',method='POST',body={'sessionId':SESSION,'seatIds':[seat]})
        self.assertEqual(status,201,checkout)
        try:
            status,delta=self.get(zone=self.zone,generation=snap['generation'],since=snap['cursor'])
            self.assertEqual(status,200);self.assertIn({'id':seat,'status':'HELD'},delta['changes'])
            for client,expected in [(a,'AVAILABLE'),(b,'HELD'),(None,'HELD')]:
                _,body=self.get(zone=self.zone,client=client,checkoutSessionId=checkout['id'])
                self.assertEqual(next(s['status'] for s in body['seats'] if s['id']==seat),expected)
                self.assertNotIn('userId',json.dumps(body));self.assertNotIn(checkout['id'],json.dumps(body))
            # A valid cached relationship for another session/user must not grant ownership.
            def cache(*args):
                result=subprocess.run(['docker','exec','phase16-api-redis','redis-cli','--json',*map(str,args)],capture_output=True,text=True,encoding='utf-8')
                self.assertEqual(result.returncode,0,result.stderr)
                return json.loads(result.stdout)
            key='ticketing:checkout-owner:{'+checkout['id']+'}'
            for mapping in ({'userId':users[0],'sessionId':'other-session'},{'userId':users[1],'sessionId':SESSION}):
                cache('SET',key,json.dumps(mapping),'EX',600)
                _,response=self.get(zone=self.zone,client=a,checkoutSessionId=checkout['id'])
                self.assertEqual(next(s['status'] for s in response['seats'] if s['id']==seat),'HELD')
            # GET wrong-type is a real Redis cache-command failure: fall back to PG and refill.
            cache('DEL',key);cache('HSET',key,'wrong','type')
            _,response=self.get(zone=self.zone,client=a,checkoutSessionId=checkout['id'])
            self.assertEqual(next(s['status'] for s in response['seats'] if s['id']==seat),'AVAILABLE')
            self.assertEqual(json.loads(cache('GET',key)),{'userId':users[0],'sessionId':SESSION})
            # Current owner requesting a different actual session never gets own context.
            _,otherLayout,_=anonymous_request('/sessions/perf-session-phase16/seat-layout')
            status,cross=self.get(session='perf-session-phase16',zone=otherLayout['seats'][0]['zone'],client=a,checkoutSessionId=checkout['id'])
            self.assertEqual(status,200);self.assertNotIn(checkout['id'],json.dumps(cross))
            # A repeated owned request must use the cache, without another ownership lookup.
            before=int(sql("SELECT COALESCE(sum(calls),0) FROM pg_stat_statements WHERE query ILIKE '%FROM checkout_sessions%' AND query ILIKE '%user_id%';"))
            for _ in range(3):self.get(zone=self.zone,client=a,checkoutSessionId=checkout['id'])
            after=int(sql("SELECT COALESCE(sum(calls),0) FROM pg_stat_statements WHERE query ILIKE '%FROM checkout_sessions%' AND query ILIKE '%user_id%';"))
            self.assertEqual(before,after)
        finally:
            status,_,_=a.request('/checkout-sessions/'+checkout['id']+'/abandon',method='POST')
            self.assertEqual(status,200)
        _,released=self.get(zone=self.zone,generation=delta['generation'],since=delta['cursor'])
        self.assertIn({'id':seat,'status':'AVAILABLE'},released['changes'])

    def test_initialization_wait_timeout_and_corruption_rebuild(self):
        def redis(*args):
            result=subprocess.run(['docker','exec','phase16-api-redis','redis-cli','--json',*map(str,args)],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(result.returncode,0,result.stderr)
            return json.loads(result.stdout)
        prefix='ticketing:seat-availability:{'+SESSION+'}'
        redis('DEL',prefix+':meta')
        redis('SET',prefix+':init-lock','test-other-initializer','PX',5000)
        try:
            started=time.monotonic();status,body=self.get(zone=self.zone)
            self.assertEqual((status,body['code']),(503,'SEAT_AVAILABILITY_INITIALIZING'))
            self.assertLess(time.monotonic()-started,3)
        finally:redis('DEL',prefix+':init-lock')
        _,before=self.get(zone=self.zone)
        summary=prefix+':zone:'+self.zone+':summary'
        redis('DEL',summary);redis('SET',summary,'invalid')
        status,after=self.get(zone=self.zone,generation=before['generation'],since=before['cursor'])
        self.assertEqual(status,200);self.assertTrue(after['reset']);self.assertFalse(after['degraded'])
        self.assertNotEqual(before['generation'],after['generation'])

    def test_delta_dedup_pagination_and_bounded_trim(self):
        def redis(*args):
            result=subprocess.run(['docker','exec','phase16-api-redis','redis-cli','--json',*map(str,args)],capture_output=True,text=True,encoding='utf-8')
            self.assertEqual(result.returncode,0,result.stderr)
            return json.loads(result.stdout)
        _,snap=self.get(zone=self.zone)
        stream='ticketing:seat-availability:{'+SESSION+'}:zone:'+self.zone+':changes'
        seat=snap['seats'][0]
        append="for i=1,tonumber(ARGV[1]) do redis.call('XADD',KEYS[1],'MAXLEN','~',10000,'*','kind','change','seatId',ARGV[2]) end return redis.call('XLEN',KEYS[1])"
        redis('EVAL',append,1,stream,1002,seat['id'])
        _,first=self.get(zone=self.zone,generation=snap['generation'],since=snap['cursor'])
        self.assertTrue(first['hasMore']);self.assertEqual(first['changes'],[seat])
        _,second=self.get(zone=self.zone,generation=first['generation'],since=first['cursor'])
        self.assertFalse(second['hasMore']);self.assertEqual(second['changes'],[seat])
        length=redis('EVAL',append,1,stream,12000,seat['id'])
        self.assertLessEqual(length,10100)
        _,reset=self.get(zone=self.zone,generation=snap['generation'],since=snap['cursor'])
        self.assertTrue(reset['reset']);self.assertEqual(reset['seats'],snap['seats'])

    def test_warm_delta_does_not_fetch_inventory(self):
        _,snap=self.get(zone=self.zone)
        query="SELECT COALESCE(sum(calls),0) FROM pg_stat_statements WHERE query ILIKE '%SELECT id, status%FROM session_seats%';"
        before=int(sql(query))
        for _ in range(20):
            status,body=self.get(zone=self.zone,generation=snap['generation'],since=snap['cursor'])
            self.assertEqual(status,200);self.assertEqual(body['mode'],'delta')
        self.assertEqual(int(sql(query)),before)

if __name__=='__main__':unittest.main(verbosity=2)
