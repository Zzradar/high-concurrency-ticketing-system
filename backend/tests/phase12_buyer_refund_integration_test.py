"""Run against compose.phase12.yml only; real backend and PostgreSQL, Fake Stripe."""
import os
import subprocess
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from auth_test_support import client_for
from payment_integration_test import cleanup, create_order, psql, request_json, SEATS, USER_ID, OTHER_USER_ID, BACKEND_ROOT
from phase11_stripe_integration_test import fake, wait_until

def compose(*args):
 return subprocess.run(['docker','compose',*args],cwd=BACKEND_ROOT,check=True,capture_output=True,text=True,encoding='utf-8').stdout

class BuyerRefundTest(unittest.TestCase):
 def setUp(self):
  self.assertIn('phase12',os.environ.get('COMPOSE_FILE',''),'isolated compose required')
  fake('/__admin__/reset',{});cleanup(create_users=True)
  self.original_start=psql("SELECT start_time::text FROM sessions WHERE id='ses-concert-1001';")
 def tearDown(self):
  psql("DROP TRIGGER IF EXISTS phase12_fault ON refunds; DROP TRIGGER IF EXISTS phase12_fault ON orders; DROP TRIGGER IF EXISTS phase12_fault ON reservations; DROP TRIGGER IF EXISTS phase12_fault ON session_seats; DROP TRIGGER IF EXISTS phase12_fault ON user_notifications; DROP FUNCTION IF EXISTS phase12_fault(); DROP SEQUENCE IF EXISTS phase12_hits;")
  psql(f"UPDATE sessions SET start_time='{self.original_start}' WHERE id='ses-concert-1001';")
  cleanup()
 def paid(self,key='buyer',seat=None):
  fake('/__admin__/configure',{'paymentMode':'succeeded','refundMode':'pending'})
  order,_=create_order(key,seat or SEATS[0]);status,body=request_json(f"/orders/{order['id']}/pay",method='POST');self.assertEqual(status,202,body)
  wait_until(lambda:psql(f"SELECT status FROM orders WHERE id='{order['id']}';")=='PAID')
  return order
 def request(self,order):
  status,body=request_json(f"/orders/{order['id']}/refunds",method='POST');self.assertEqual(status,202,body);return body['refund']
 def provider(self,r):
  return wait_until(lambda:next((f for f in fake('/__admin__/state')['refunds'] if f['metadata']['local_refund_id']==r['id']),None))
 def wake(self,r):psql(f"UPDATE refunds SET next_reconcile_at=clock_timestamp() WHERE id='{r['id']}';")
 def terminal(self,r,status='succeeded'):
  pr=self.provider(r);fake('/__admin__/configure',{'refundId':pr['id'],'refundStatus':status});self.wake(r)
 def states(self,o,r):
  return psql(f"SELECT f.status,o.status,r.status,s.status,s.current_reservation_id IS NULL FROM refunds f JOIN orders o ON o.id=f.order_id JOIN reservations r ON r.id=o.reservation_id JOIN reservation_session_seats x ON x.reservation_id=r.id JOIN session_seats s ON s.id=x.session_seat_id WHERE f.id='{r['id']}';").split('\t')
 def assert_done(self,o,r):
  wait_until(lambda:self.states(o,r)==['SUCCEEDED','CANCELLED','CANCELLED','AVAILABLE','t'])
  self.assertEqual(psql(f"SELECT f.refunded_at=o.refunded_at AND f.refunded_at=f.provider_terminal_at FROM refunds f JOIN orders o ON o.id=f.order_id WHERE f.id='{r['id']}';"),'t')
 def test_null_sold_pointer_full_atomic_refund_and_reuse(self):
  o=self.paid();r=self.request(o);self.provider(r)
  self.assertEqual(self.states(o,r),['PROCESSING','PAID','CONFIRMED','SOLD','t'])
  self.terminal(r);self.assert_done(o,r)
  status,body=request_json(f"/orders/{o['id']}/refunds",method='POST');self.assertEqual(status,200);self.assertEqual(body['refund']['id'],r['id']);self.assertEqual(body['disposition'],'REUSED_TERMINAL')
  self.assertEqual(psql(f"SELECT count(*) FROM user_notifications WHERE order_id='{o['id']}' AND type='REFUND_COMPLETED';"),'1')
 def test_concurrent_requests_create_one_obligation_and_provider_object(self):
  o=self.paid();client_for(USER_ID) # authenticate before concurrent calls
  with ThreadPoolExecutor(max_workers=8) as pool:
   results=list(pool.map(lambda _:request_json(f"/orders/{o['id']}/refunds",method='POST'),range(16)))
  self.assertTrue(all(s==202 for s,b in results),results);ids={b['refund']['id'] for s,b in results};self.assertEqual(len(ids),1)
  r=results[0][1]['refund'];self.provider(r);self.assertEqual(fake('/__admin__/state')['createRefundCalls'].count(r['id']),1)
 def test_owner_body_and_missing_accepted_attempt(self):
  o=self.paid()
  for body in ({'amount':1},{'currency':'usd'},{'userId':OTHER_USER_ID},{'paymentAttemptId':'x'},{'unknown':1}):
   status,payload=request_json(f"/orders/{o['id']}/refunds",method='POST',body=body);self.assertEqual((status,payload['code']),(400,'INVALID_REQUEST_BODY'))
  self.assertEqual(request_json(f"/orders/{o['id']}/refunds",method='POST',user_id=OTHER_USER_ID)[0],404)
  psql(f"UPDATE payment_attempts SET accepted_at=NULL WHERE order_id='{o['id']}';")
  self.assertEqual(request_json(f"/orders/{o['id']}/refunds",method='POST')[0],500)
 def test_eligibility_and_existing_first_after_deadline(self):
  o=self.paid();self.assertTrue(request_json(f"/orders/{o['id']}")[1]['refundEligibility']['eligible']);r=self.request(o)
  psql("UPDATE sessions SET gate_time=clock_timestamp()-interval '2 hours', start_time=clock_timestamp()-interval '1 hour' WHERE id='ses-concert-1001';")
  status,b=request_json(f"/orders/{o['id']}/refunds",method='POST');self.assertEqual(status,202);self.assertEqual(b['refund']['id'],r['id'])
  self.assertEqual(request_json(f"/orders/{o['id']}")[1]['refundEligibility']['reason'],'ALREADY_REQUESTED')
  self.assertEqual(request_json('/refunds/'+r['id'],user_id=OTHER_USER_ID)[0],404)
 def test_pending_failed_and_requires_action_keep_rights(self):
  o=self.paid();r=self.request(o);pr=self.provider(r)
  fake('/__admin__/configure',{'refundId':pr['id'],'refundStatus':'requires_action'});self.wake(r)
  wait_until(lambda:psql(f"SELECT provider_status FROM refunds WHERE id='{r['id']}';")=='requires_action')
  self.assertEqual(self.states(o,r),['PROCESSING','PAID','CONFIRMED','SOLD','t'])
  self.terminal(r,'failed');wait_until(lambda:self.states(o,r)[0]=='FAILED');self.assertEqual(self.states(o,r),['FAILED','PAID','CONFIRMED','SOLD','t'])
  self.assertEqual(request_json(f"/orders/{o['id']}/refunds",method='POST')[0],200)
 def invariant_log(self,r,stage):
  return 'REFUND_INVARIANT stage='+stage+' refund='+r['id'] in compose('logs','--no-color','backend')
 def test_wrong_seat_state_rolls_back(self):
  o=self.paid();r=self.request(o);self.provider(r)
  psql(f"UPDATE session_seats SET status='AVAILABLE' WHERE id='{SEATS[0]}';");self.terminal(r)
  wait_until(lambda:self.invariant_log(r,'seat_shape'));self.assertEqual(self.states(o,r)[:3],['PROCESSING','PAID','CONFIRMED'])
  self.assertEqual(psql(f"SELECT count(*) FROM user_notifications WHERE order_id='{o['id']}' AND type='REFUND_COMPLETED';"),'0')
 def test_duplicate_effective_owner_rolls_back(self):
  o=self.paid();r=self.request(o);self.provider(r)
  psql(f"""INSERT INTO reservations(id,user_id,session_id,status,expires_at) SELECT 'p12-conflict-r',user_id,session_id,status,expires_at FROM reservations WHERE id='{o['reservationId']}';
  INSERT INTO orders(id,user_id,reservation_id,status,total_amount,expires_at,paid_at) SELECT 'p12-conflict-o',user_id,'p12-conflict-r',status,total_amount,expires_at,paid_at FROM orders WHERE id='{o['id']}';
  INSERT INTO reservation_session_seats SELECT 'p12-conflict-r',session_id,session_seat_id,reserved_price,created_at FROM reservation_session_seats WHERE reservation_id='{o['reservationId']}';""")
  self.terminal(r);wait_until(lambda:self.invariant_log(r,'ownership_conflict'));self.assertEqual(self.states(o,r),['PROCESSING','PAID','CONFIRMED','SOLD','t'])
 def test_each_terminal_write_failure_rolls_back_whole_transaction(self):
  for i,table in enumerate(['refunds','orders','reservations','session_seats','user_notifications']):
   with self.subTest(table=table):
    o=self.paid('fault-'+table,SEATS[i]);r=self.request(o);self.provider(r)
    psql(f"""CREATE SEQUENCE phase12_hits; CREATE FUNCTION phase12_fault() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN PERFORM nextval('phase12_hits'); RAISE EXCEPTION 'phase12 injected rollback'; END $$;
    CREATE TRIGGER phase12_fault AFTER {'INSERT' if table=='user_notifications' else 'UPDATE'} ON {table} FOR EACH ROW {"WHEN (NEW.type='REFUND_COMPLETED')" if table=='user_notifications' else "WHEN (NEW.status='SUCCEEDED')" if table=='refunds' else "WHEN (NEW.status='AVAILABLE')" if table=='session_seats' else "WHEN (NEW.status='CANCELLED')"} EXECUTE FUNCTION phase12_fault();""")
    self.terminal(r);wait_until(lambda:psql('SELECT is_called FROM phase12_hits;')=='t');self.assertEqual(self.states(o,r),['PROCESSING','PAID','CONFIRMED','SOLD','t'])
    psql(f"DROP TRIGGER phase12_fault ON {table}; DROP FUNCTION phase12_fault(); DROP SEQUENCE phase12_hits;")
    psql(f"UPDATE refunds SET reconciliation_lease_token=NULL,reconciliation_lease_until=NULL,next_reconcile_at=clock_timestamp() WHERE id='{r['id']}';")
    self.assert_done(o,r)
 def test_response_loss_recovers_without_second_post(self):
  o=self.paid();fake('/__admin__/configure',{'refundMode':'response_lost_once'});r=self.request(o);self.assert_done(o,r)
  self.assertEqual(fake('/__admin__/state')['createRefundCalls'].count(r['id']),1)
 def test_expired_idempotency_key_recovers_existing_refund(self):
  o=self.paid();fake('/__admin__/configure',{'listMode':'network'});r=self.request(o)
  a=psql(f"SELECT provider_payment_id FROM payment_attempts WHERE order_id='{o['id']}';")
  existing={'id':'re_history','object':'refund','status':'succeeded','amount':r['amount'],'currency':r['currency'],'payment_intent':a,'metadata':{'local_refund_id':r['id'],'order_id':o['id']}}
  fake('/__admin__/configure',{'seedRefunds':[existing],'forgetRefundKeys':True,'listMode':'normal'});self.wake(r);self.assert_done(o,r)
  self.assertEqual(fake('/__admin__/state')['createRefundCalls'].count(r['id']),0)

 def test_old_worker_fenced_before_seats_after_resale(self):
  o=self.paid();r=self.request(o);pr=self.provider(r)
  wait_until(lambda:psql(f"SELECT provider_refund_id IS NOT NULL AND reconciliation_lease_token IS NULL FROM refunds WHERE id='{r['id']}';")=='t')
  fake('/__admin__/configure',{'refundId':pr['id'],'refundStatus':'succeeded','refundDelayOnce':10})
  self.wake(r);wait_until(lambda:fake('/__admin__/state')['refundDelayed']==1)
  old_token=psql(f"SELECT reconciliation_lease_token FROM refunds WHERE id='{r['id']}';")
  self.assertTrue(old_token)
  psql(f"UPDATE refunds SET reconciliation_lease_until=clock_timestamp()-interval '1 second',next_reconcile_at=clock_timestamp() WHERE id='{r['id']}';")
  peer=compose('run','-d','--no-deps','backend').strip()
  try:
   self.assert_done(o,r)
   new=self.paid('resale')
   self.assertEqual(psql(f"SELECT status FROM orders WHERE id='{new['id']}';"),'PAID')
   wait_until(lambda:'REFUND_FENCED_BEFORE_RIGHTS refund='+r['id'] in compose('logs','--no-color','backend'),timeout=20)
   self.assertEqual(psql(f"SELECT status||':'||(current_reservation_id IS NULL)::text FROM session_seats WHERE id='{SEATS[0]}';"),'SOLD:true')
  finally:
   subprocess.run(['docker','stop',peer],check=True,capture_output=True)
   subprocess.run(['docker','rm',peer],check=True,capture_output=True)

 def test_nonpaid_and_closed_window(self):
  o,_=create_order('unpaid',SEATS[0]);self.assertEqual(request_json(f"/orders/{o['id']}/refunds",method='POST')[1]['code'],'ORDER_NOT_REFUNDABLE')
  paid=self.paid('closed',SEATS[1]);psql("UPDATE sessions SET gate_time=clock_timestamp()-interval '2 hours',start_time=clock_timestamp()-interval '1 hour' WHERE id='ses-concert-1001';")
  self.assertEqual(request_json(f"/orders/{paid['id']}/refunds",method='POST')[1]['code'],'REFUND_WINDOW_CLOSED')
 def prepare_scan(self):
  o=self.paid();fake('/__admin__/configure',{'listMode':'network'});r=self.request(o)
  # Wait until the first failed scan released its lease, then park it while arranging evidence.
  wait_until(lambda:len(fake('/__admin__/state')['refundLists'])>0)
  wait_until(lambda:psql(f"SELECT reconciliation_lease_token IS NULL FROM refunds WHERE id='{r['id']}';")=='t')
  psql(f"UPDATE refunds SET next_reconcile_at=clock_timestamp()+interval '1 day' WHERE id='{r['id']}';")
  a=psql(f"SELECT provider_payment_id FROM payment_attempts WHERE order_id='{o['id']}';")
  candidate={'id':'re_page_0','object':'refund','status':'succeeded','amount':r['amount'],'currency':r['currency'],'payment_intent':a,'metadata':{'local_refund_id':r['id'],'order_id':o['id']}}
  return o,r,candidate
 def test_match_on_later_page(self):
  o,r,c=self.prepare_scan();other=dict(c,id='re_page_0',metadata={});c['id']='re_page_1'
  fake('/__admin__/configure',{'listMode':'normal','listPages':[{'data':[other],'has_more':True},{'data':[c],'has_more':False}]});self.wake(r);self.assert_done(o,r)
  self.assertEqual(fake('/__admin__/state')['createRefundCalls'],[])
 def test_retrieve_mismatch_never_completes(self):
  o=self.paid();r=self.request(o);c=self.provider(r)
  wait_until(lambda:psql(f"SELECT provider_refund_id IS NOT NULL FROM refunds WHERE id='{r['id']}';")=='t')
  fake('/__admin__/configure',{'refundId':c['id'],'refundPatch':{'currency':'usd','status':'succeeded'}});self.wake(r)
  wait_until(lambda:'STRIPE_REFUND_MISMATCH refund='+r['id'] in compose('logs','--no-color','backend'))
  self.assertEqual(self.states(o,r),['PROCESSING','PAID','CONFIRMED','SOLD','t'])

 def test_buyer_provider_success_then_process_crash_recovers(self):
  from phase11_crash_window_integration_test import CrashWindowIntegrationTest
  o=self.paid();r=self.request(o);provider_refund=self.provider(r)
  helper=CrashWindowIntegrationTest();helper.locker=None
  try:
   helper.install_fault('refunds',f"NEW.id='{r['id']}' AND NEW.status='SUCCEEDED'")
   fake('/__admin__/configure',{'refundId':provider_refund['id'],'refundStatus':'succeeded'})
   helper.crash_and_restart('refunds',r['id']);self.assert_done(o,r)
   self.assertEqual(fake('/__admin__/state')['createRefundCalls'].count(r['id']),1)
  finally:helper.remove_fault();compose('start','backend')
 def test_refund_webhook_only_wakes_no_identity_binding(self):
  from phase11_stripe_integration_test import signed_webhook
  o,r,c=self.prepare_scan()
  c['id']='re_unverified'
  self.assertEqual(signed_webhook('evt-buyer-forged','refund.updated',c)[0],200)
  wait_until(lambda:psql("SELECT status FROM payment_provider_events WHERE provider_event_id='evt-buyer-forged';")=='PROCESSED')
  self.assertEqual(psql(f"SELECT provider_refund_id IS NULL FROM refunds WHERE id='{r['id']}';"),'t')
  psql("DELETE FROM payment_provider_events WHERE provider_event_id='evt-buyer-forged';")
 def test_should_retry_header_wins_over_auth_status(self):
  o,r,c=self.prepare_scan();fake('/__admin__/configure',{'listMode':'normal','refundError':{'status':401,'type':'authentication_error','retry':True}});self.wake(r)
  wait_until(lambda:r['id'] in fake('/__admin__/state')['createRefundCalls'])
  wait_until(lambda:psql(f"SELECT reconciliation_lease_token IS NULL FROM refunds WHERE id='{r['id']}';")=='t')
  self.assertEqual(psql(f"SELECT next_reconcile_at < clock_timestamp()+interval '65 seconds' FROM refunds WHERE id='{r['id']}';"),'t')
  self.assertEqual(self.states(o,r),['PROCESSING','PAID','CONFIRMED','SOLD','t'])
 def test_immediate_failed_and_canceled(self):
  for i,status in enumerate(['failed','canceled']):
   o=self.paid('immediate-'+status,SEATS[i]);fake('/__admin__/configure',{'refundMode':status});r=self.request(o)
   wait_until(lambda:self.states(o,r)[0]=='FAILED');self.assertEqual(self.states(o,r),['FAILED','PAID','CONFIRMED','SOLD','t'])

 def test_currency_comes_from_historical_attempt(self):
  o=self.paid();a=psql(f"SELECT provider_payment_id FROM payment_attempts WHERE order_id='{o['id']}';")
  # Trusted historical fixture: deployment config remains cny, original payment was usd.
  psql(f"UPDATE payment_attempts SET currency='usd' WHERE order_id='{o['id']}';")
  fake('/__admin__/configure',{'paymentId':a,'paymentPatch':{'currency':'usd'}})
  r=self.request(o);self.assertEqual(r['currency'],'usd');self.terminal(r);self.assert_done(o,r)

# Each matrix entry gets independent setup/cleanup; no shared test ordering.
def scan_conflict_case(kind):
 def run(self):
  o,r,c=self.prepare_scan();data=[c];pages=None;mode='normal'
  if kind=='multiple':data=[c,dict(c,id='re_other')]
  elif kind in ['amount','currency','payment_intent']:c[kind]=1 if kind=='amount' else 'wrong'
  elif kind=='order_id':c['metadata']['order_id']='wrong'
  elif kind=='page_cap':
   pages=[{'data':[dict(c,id='re_page_'+str(i),metadata={})],'has_more':True} for i in range(10)]
  elif kind=='repeat_cursor':pages=[{'data':[dict(c,metadata={})],'has_more':True}]*2
  elif kind=='empty_more':mode='empty_more'
  elif kind in ['invalid','invalid_json']:mode=kind
  elif kind=='missing_cursor':pages=[{'data':[dict(c,id=None,metadata={})],'has_more':True}]
  if pages is None:pages=[{'data':data,'has_more':False}]
  before=len(fake('/__admin__/state')['refundLists'])
  fake('/__admin__/configure',{'listMode':mode,'listPages':pages});self.wake(r)
  wait_until(lambda:len(fake('/__admin__/state')['refundLists'])>before)
  wait_until(lambda:psql(f"SELECT reconciliation_lease_token IS NULL FROM refunds WHERE id='{r['id']}';")=='t')
  self.assertEqual(self.states(o,r),['PROCESSING','PAID','CONFIRMED','SOLD','t']);self.assertEqual(fake('/__admin__/state')['createRefundCalls'],[])
  self.assertEqual(psql(f"SELECT provider_refund_id IS NULL FROM refunds WHERE id='{r['id']}';"),'t')
 return run
for kind in ['multiple','amount','currency','payment_intent','order_id','page_cap','repeat_cursor','empty_more','invalid','invalid_json','missing_cursor']:
 setattr(BuyerRefundTest,'test_scan_'+kind,scan_conflict_case(kind))
def http_error_case(status,code,kind='invalid_request_error'):
 def run(self):
  o,r,c=self.prepare_scan();fake('/__admin__/configure',{'listMode':'normal','refundError':{'status':status,'code':code,'type':kind}});self.wake(r)
  wait_until(lambda:r['id'] in fake('/__admin__/state')['createRefundCalls'])
  wait_until(lambda:psql(f"SELECT reconciliation_lease_token IS NULL FROM refunds WHERE id='{r['id']}';")=='t')
  self.assertEqual(self.states(o,r),['PROCESSING','PAID','CONFIRMED','SOLD','t'])
 return run
for status,code,kind in [(429,'rate_limit','rate_limit_error'),(500,'unknown','api_error'),(401,'invalid_api_key','authentication_error'),(403,'permission','permission_error'),(400,'unknown','idempotency_error'),(400,'charge_already_refunded','invalid_request_error'),(400,'amount_too_large','invalid_request_error'),(400,'unknown','invalid_request_error')]:
 setattr(BuyerRefundTest,'test_http_'+str(status)+'_'+code+'_'+kind,http_error_case(status,code,kind))

if __name__=='__main__':unittest.main(verbosity=2)
