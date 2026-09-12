"""Real role/cache/Zone boundary checks against the isolated batch1 test backend."""
import os
os.environ['TICKETING_BASE_URL']=os.environ.get('PHASE17_BASE_URL','http://127.0.0.1:18117')
import hashlib,json,subprocess,time,unittest,uuid
from urllib.parse import urlencode
from auth_test_support import AuthenticatedClient,anonymous_request
PG=os.environ.get('PHASE17_POSTGRES_CONTAINER','phase17-postgres')
REDIS=os.environ.get('PHASE17_REDIS_CONTAINER','phase17-redis')
def command(args,stdin=None):
    r=subprocess.run(args,input=stdin,text=True,encoding='utf-8',capture_output=True)
    if r.returncode:raise AssertionError(r.stderr)
    return r.stdout.strip()
def sql(s):return command(['docker','exec','-i',PG,'psql','-U','postgres','-qAt','-v','ON_ERROR_STOP=1'],s)
def redis(*args):return command(['docker','exec',REDIS,'redis-cli','--raw',*args])
def cache_put(key,value):return command(['docker','exec','-i',REDIS,'redis-cli','-x','SET',key],json.dumps(value))
def setUpModule():
    # The listener can accept before async database connections are ready.
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        try:
            if anonymous_request('/events',timeout=2)[0]==200:return
        except (OSError, ConnectionError):pass
        time.sleep(.1)
    raise AssertionError('Phase17 API did not become ready')

class AuthRoleTest(unittest.TestCase):
    def setUp(self):
        sql("UPDATE app_users SET role='ADMIN' WHERE username='admin';")
        self.addCleanup(lambda:sql("UPDATE app_users SET role='ADMIN' WHERE username='admin';"))
    def admin(self):
        a=AuthenticatedClient('admin');a.login();return a
    def cache(self,a):
        key='ticketing:auth-session:'+hashlib.sha256(a.cookie('ticketing_session').encode()).hexdigest()
        a.request('/auth/me')
        for _ in range(40):
            raw=redis('GET',key)
            if raw:return key,json.loads(raw)
            time.sleep(.05)
        self.fail('auth cache not populated')
    def test_login_me_rbac_and_csrf(self):
        self.assertEqual(anonymous_request('/admin/phase17-auth-probe')[0],401)
        self.assertEqual(anonymous_request('/admin/phase17-auth-probe',method='POST')[0],401)
        c=AuthenticatedClient();self.assertEqual(c.request('/auth/me')[1]['role'],'CUSTOMER')
        for method in ('GET','POST'):
            status,body,_=c.request('/admin/phase17-auth-probe',method=method)
            self.assertEqual((status,body['code']),(403,'ADMIN_REQUIRED'))
        a=AuthenticatedClient('admin')
        status,body,_=a._send('/auth/login',method='POST',body={'username':'admin','password':'Ticketing123!'},headers={'Origin':'http://localhost:5173'})
        self.assertEqual((status,body['role']),(200,'ADMIN'));a._logged_in=True
        self.assertEqual(a.request('/auth/me')[1]['role'],'ADMIN')
        self.assertEqual(a.request('/admin/phase17-auth-probe')[0],200)
        self.assertEqual(a.request('/admin/phase17-auth-probe',method='POST')[0],200)
        status,body,_=a.request('/admin/phase17-auth-probe',method='POST',csrf=False)
        self.assertEqual((status,body['code']),(403,'CSRF_INVALID'))
        status,body,_=a.request('/admin/phase17-auth-probe',method='POST',headers={'Origin':'https://invalid.example'})
        self.assertEqual((status,body['code']),(403,'CSRF_INVALID'))
    def test_missing_and_invalid_cached_role_reload_from_database(self):
        a=self.admin();key,value=self.cache(a)
        for invalid in (None,'admin','ROOT',42,{},True):
            with self.subTest(role=invalid):
                bad=dict(value);bad['role']=invalid
                if invalid is None:del bad['role']
                # Marker demonstrates a cache miss and database reload, not a defaulted role.
                bad['displayName']='stale-cache-marker';cache_put(key,bad)
                status,body,_=a.request('/auth/me')
                self.assertEqual(status,200);self.assertEqual(body['role'],'ADMIN')
                self.assertEqual(body['displayName'],'Demo 管理员')
    def test_cached_admin_is_downgraded_on_next_request_without_extra_query(self):
        a=self.admin();key,value=self.cache(a);self.assertEqual(value['role'],'ADMIN')
        sql("UPDATE app_users SET role='CUSTOMER' WHERE username='admin';")
        before=int(sql("SELECT coalesce(sum(calls),0) FROM pg_stat_statements WHERE query LIKE '%SELECT app_user.role%FROM user_sessions%';"))
        reload_before=int(sql("SELECT coalesce(sum(calls),0) FROM pg_stat_statements WHERE query LIKE '%app_user.display_name, app_user.role%FROM user_sessions%';"))
        status,body,_=a.request('/admin/phase17-auth-probe')
        self.assertEqual((status,body['code']),(403,'ADMIN_REQUIRED'))
        after=int(sql("SELECT coalesce(sum(calls),0) FROM pg_stat_statements WHERE query LIKE '%SELECT app_user.role%FROM user_sessions%';"))
        reload_after=int(sql("SELECT coalesce(sum(calls),0) FROM pg_stat_statements WHERE query LIKE '%app_user.display_name, app_user.role%FROM user_sessions%';"))
        self.assertEqual(after-before,1);self.assertEqual(reload_before,reload_after)
        self.assertEqual(a.request('/auth/me')[1]['role'],'CUSTOMER')
        sql("UPDATE app_users SET role='ADMIN' WHERE username='admin';")
        self.assertEqual(a.request('/admin/phase17-auth-probe')[0],200)
        # Exercise the periodic touch path as well as the no-touch cache hit.
        sql("UPDATE user_sessions SET created_at=now()-interval '20 minutes',last_seen_at=now()-interval '10 minutes' WHERE id='"+value['sessionId']+"';")
        value['lastSeenAt']-=600;cache_put(key,value)
        self.assertEqual(a.request('/auth/me')[1]['role'],'ADMIN')
class ZoneCompatibilityTest(unittest.TestCase):
    def test_legacy_demo_names_and_order(self):
        status,layout,_=anonymous_request('/sessions/ses-concert-1001/seat-layout')
        self.assertEqual(status,200)
        self.assertEqual(list(dict.fromkeys(s['zone'] for s in layout['seats'])),['星光区','看台 A 区','看台 B 区'])
        self.assertEqual(len(layout['seats']),60)
    def test_duplicate_a001_cold_snapshot_delta_summary_and_fallback(self):
        suffix=uuid.uuid4().hex;v='v-'+suffix;ses='s-'+suffix;e='e-'+suffix
        z1='z1-'+suffix;z2='z2-'+suffix
        sql(f"INSERT INTO venues(id,name,city) VALUES('{v}','V','C'); INSERT INTO venue_zones(id,venue_id,code,name,sort_order) VALUES('{z1}','{v}','Z','Zulu',0),('{z2}','{v}','A','Alpha',1); INSERT INTO seats(id,venue_id,zone_id,row_no,seat_no,seat_label) VALUES('{z1}','{v}','{z1}','A',1,'A001'),('{z2}','{v}','{z2}','A',1,'A001'); INSERT INTO events(id,primary_venue_id,name,description,status,category,cover_url,date_range,sales_starts_at,sales_ends_at) VALUES('{e}','{v}','E','','ON_SALE','C','cover','',now()-interval '1 day',now()+interval '1 day'); INSERT INTO sessions(id,event_id,venue_id,hall_name,start_time,gate_time,status) VALUES('{ses}','{e}','{v}','Hall',now()+interval '1 day',now(),'ON_SALE'); INSERT INTO session_seats(id,session_id,seat_id,venue_id,status,price) VALUES('{z1}','{ses}','{z1}','{v}','AVAILABLE',100),('{z2}','{ses}','{z2}','{v}','AVAILABLE',200);")
        base='/sessions/'+ses
        status,layout,_=anonymous_request(base+'/seat-layout');self.assertEqual(status,200)
        self.assertEqual([(s['label'],s['zone']) for s in layout['seats']],[('A001','Zulu'),('A001','Alpha')])
        self.assertEqual(anonymous_request(base+'/seats')[0],200)
        self.assertEqual(anonymous_request(base+'/seat-availability')[0],200)
        def read(zone,**extra):return anonymous_request(base+'/seat-availability?'+urlencode(dict(zone=zone,**extra)))
        for zone,seat in [('Zulu',z1),('Alpha',z2)]:
            status,snap,_=read(zone);self.assertEqual(status,200);self.assertFalse(snap['degraded'])
            self.assertEqual(snap['seats'],[{'id':seat,'status':'AVAILABLE'}])
            self.assertEqual([z['zone'] for z in snap['zones']],['Zulu','Alpha'])
            self.assertEqual([z['total'] for z in snap['zones']],[1,1])
            _,delta,_=read(zone,generation=snap['generation'],since=snap['cursor'])
            self.assertEqual(delta['changes'],[]);self.assertEqual(delta['mode'],'delta')
        command(['docker','stop',REDIS])
        try:
            for zone,seat in [('Zulu',z1),('Alpha',z2)]:
                status,snap,_=read(zone);self.assertEqual(status,200);self.assertTrue(snap['degraded'])
                self.assertEqual(snap['seats'],[{'id':seat,'status':'AVAILABLE'}])
                self.assertEqual([z['zone'] for z in snap['zones']],['Zulu','Alpha'])
                self.assertEqual([z['available'] for z in snap['zones']],[1,1])
        finally:
            command(['docker','start',REDIS])
            for _ in range(60):
                try:
                    if redis('PING')=='PONG':break
                except AssertionError:pass
                time.sleep(.1)
        time.sleep(.5)
        self.assertFalse(read('Zulu')[1]['degraded'])
if __name__=='__main__':unittest.main(verbosity=2)
