"""Real HTTP/PG lock tests: final admission and idempotency across closing time."""
import json,subprocess,unittest,uuid
from concurrent.futures import ThreadPoolExecutor
from phase15_test_support import sql,client,until,SESSION,EVENT,AuthenticatedClient,username_for_user
class DatabaseLock:
    def __init__(self,statement):
        self.p=subprocess.Popen(['docker','exec','-i','phase15-api-postgres','psql','-U','postgres','-qAt','-v','ON_ERROR_STOP=1'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8')
        self.p.stdin.write("BEGIN;"+statement+";SELECT 'LOCK_READY';\n");self.p.stdin.flush()
        while True:
            line=self.p.stdout.readline().strip()
            if line=='LOCK_READY':break
            if self.p.poll() is not None:raise AssertionError(self.p.stderr.read())
    def close(self):
        if self.p.poll() is None:
            self.p.stdin.write('ROLLBACK;\n\q\n');self.p.stdin.flush();self.p.communicate(timeout=10)
class ReservationSalesTest(unittest.TestCase):
    def setUp(self):
        self.user,self.c=client();self.seat=SESSION+'-A01';self.other=SESSION+'-A02'
        self.old=sql("SELECT sales_starts_at||'|'||sales_ends_at||'|'||status FROM events WHERE id='"+EVENT+"';").split('|')
        self.addCleanup(self.restore)
        self.window('OPEN')
    def restore(self):
        rows=sql("SELECT id FROM orders WHERE user_id='"+self.user+"' AND status='PENDING_PAYMENT';").splitlines()
        for order in rows:
            status,body,_=self.c.request('/orders/'+order+'/cancel',method='POST');self.assertEqual(status,200,body)
        sql("UPDATE events SET sales_starts_at='"+self.old[0]+"',sales_ends_at='"+self.old[1]+"',status='"+self.old[2]+"' WHERE id='"+EVENT+"';")
    def window(self,state):
        start,end={'OPEN':(-100,500),'NOT_STARTED':(100,500),'ENDED':(-500,-1)}[state]
        sql("UPDATE events SET sales_starts_at=clock_timestamp()+make_interval(secs=>"+str(start)+"),sales_ends_at=clock_timestamp()+make_interval(secs=>"+str(end)+"),status='ON_SALE' WHERE id='"+EVENT+"';")
    def reserve(self,key,seats=None,c=None):return (c or self.c).request('/reservations',method='POST',body={'sessionId':SESSION,'seatIds':seats or [self.seat]},headers={'Idempotency-Key':key})
    def assert_no_writes(self):
        for table in ['reservations','orders','user_notifications']:
            self.assertEqual(sql("SELECT count(*) FROM "+table+" WHERE user_id='"+self.user+"';"),'0')
    def test_new_request_rejected_and_idempotent_replay_survives_end(self):
        key='p15-'+uuid.uuid4().hex
        status,original,_=self.reserve(key);self.assertEqual(status,201,original)
        self.window('ENDED')
        status,replay,_=self.reserve(key);self.assertEqual(status,200,replay);self.assertEqual(original,replay)
        status,body,_=self.reserve(key,[self.other]);self.assertEqual((status,body['code']),(409,'IDEMPOTENCY_CONFLICT'))
        status,body,_=self.reserve(key+'new');self.assertEqual((status,body['code']),(409,'SALES_ENDED'))
    def test_not_started_and_static_unavailable_roll_back_new_insert(self):
        self.window('NOT_STARTED');status,body,_=self.reserve('not-started');self.assertEqual((status,body['code']),(409,'SALES_NOT_STARTED'));self.assert_no_writes()
        sql("UPDATE events SET status='COMING_SOON' WHERE id='"+EVENT+"';")
        status,body,_=self.reserve('static');self.assertEqual((status,body['code']),(409,'SESSION_NOT_AVAILABLE'));self.assert_no_writes()
    def test_seat_lock_wait_crosses_end_without_inventory_or_outbox_writes(self):
        before=sql("SELECT status||'|'||formal_version FROM session_seats WHERE id='"+self.seat+"';")
        lock=DatabaseLock("SELECT id FROM session_seats WHERE id='"+self.seat+"' FOR UPDATE")
        pool=ThreadPoolExecutor(1)
        try:
            pending=pool.submit(self.reserve,'blocked-'+uuid.uuid4().hex)
            until(lambda:int(sql("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock' AND query LIKE '%ORDER BY id ASC FOR UPDATE%';"))>0)
            self.window('ENDED');lock.close();status,body,_=pending.result(timeout=10)
            self.assertEqual((status,body['code']),(409,'SALES_ENDED'))
        finally:lock.close();pool.shutdown()
        self.assert_no_writes()
        self.assertEqual(sql("SELECT status||'|'||formal_version FROM session_seats WHERE id='"+self.seat+"';"),before)
        self.assertEqual(sql("SELECT count(*) FROM reservation_session_seats i JOIN reservations r ON r.id=i.reservation_id WHERE r.user_id='"+self.user+"';"),'0')
        self.assertEqual(sql("SELECT count(*) FROM seat_availability_outbox WHERE session_seat_id='"+self.seat+"';"),'0')
    def test_concurrent_same_key_arbitrates_before_ended_preliminary_rejection(self):
        suffix=uuid.uuid4().hex;function='p15_barrier_'+suffix;trigger=function
        sql("CREATE FUNCTION "+function+"() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN IF NEW.user_id='"+self.user+"' THEN PERFORM pg_advisory_xact_lock(150015);END IF;RETURN NEW;END$$;CREATE TRIGGER "+trigger+" BEFORE INSERT ON orders FOR EACH ROW EXECUTE FUNCTION "+function+"();")
        lock=DatabaseLock('SELECT pg_advisory_xact_lock(150015)');pool=ThreadPoolExecutor(2)
        second=AuthenticatedClient(username_for_user(self.user));second.login()
        try:
            key='concurrent-'+suffix;one=pool.submit(self.reserve,key)
            until(lambda:int(sql("SELECT count(*) FROM pg_stat_activity WHERE wait_event='advisory' AND query LIKE '%INSERT INTO orders%';"))>0)
            self.window('ENDED')
            two=pool.submit(self.reserve,key,None,second)
            until(lambda:int(sql("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type='Lock' AND query LIKE '%INSERT INTO reservations%';"))>0)
            lock.close();a=one.result(timeout=10);b=two.result(timeout=10)
            self.assertEqual(a[0],201,a[1]);self.assertEqual(b[0],200,b[1]);self.assertEqual(a[1],b[1])
            self.assertEqual(sql("SELECT count(*) FROM reservations WHERE user_id='"+self.user+"';"),'1')
        finally:
            lock.close();pool.shutdown();sql('DROP TRIGGER '+trigger+' ON orders;DROP FUNCTION '+function+'();')
if __name__=='__main__':unittest.main(verbosity=2)
