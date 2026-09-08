from pathlib import Path
import subprocess, unittest, uuid
ROOT=Path(__file__).resolve().parents[1]
class MigrationTest(unittest.TestCase):
 def sql(self, sql, ok=True):
  r=subprocess.run(['docker','exec','-i','phase12-db','psql','-U','ticketing','-d','ticketing','-v','ON_ERROR_STOP=1','-At'],input=sql,text=True,encoding='utf-8',capture_output=True)
  if ok: self.assertEqual(r.returncode,0,r.stderr)
  else: self.assertNotEqual(r.returncode,0)
  return r.stdout
 def setup_schema(self):
  self.schema='p12_'+uuid.uuid4().hex
  self.prefix='SET search_path TO '+self.schema+';\n'
  self.sql('CREATE SCHEMA '+self.schema+';'+self.prefix+'\n'.join(p.read_text(encoding='utf-8') for p in sorted((ROOT/'db/migrations').glob('00[1-8]*.sql')))+(ROOT/'db/seeds/001_demo_seed.sql').read_text(encoding='utf-8'))
  self.addCleanup(lambda:self.sql('DROP SCHEMA '+self.schema+' CASCADE;'))
 def test_empty_and_verifiers(self):
  self.setup_schema();self.sql(self.prefix+(ROOT/'db/migrations/009_add_buyer_full_refund.sql').read_text(encoding='utf-8'))
  for p in sorted((ROOT/'db/tests').glob('*.sql')): self.sql(self.prefix+p.read_text(encoding='utf-8'))
 def test_history_requires_explicit_currency_and_rolls_back(self):
  self.setup_schema()
  self.sql(self.prefix+"INSERT INTO payment_attempts(id,order_id,status,started_at,processing_deadline) VALUES('hist','TKT-SEED-HELD-ses-concert-1001','PROCESSING',now(),now()+interval '10 seconds');")
  migration=(ROOT/'db/migrations/009_add_buyer_full_refund.sql').read_text(encoding='utf-8')
  for setting in ['',"SET ticketing.legacy_payment_currency='USD';"]:
   self.sql(self.prefix+setting+migration,False)
   self.assertEqual(self.sql("SELECT count(*) FROM information_schema.columns WHERE table_schema='"+self.schema+"' AND column_name='currency';").strip(),'0')
  self.sql(self.prefix+"SET ticketing.legacy_payment_currency='cny';"+migration)
  self.assertEqual(self.sql(self.prefix+"SELECT currency FROM payment_attempts WHERE id='hist';").splitlines()[-1],'cny')
 def test_shapes_uniqueness_currency_and_notifications(self):
  self.setup_schema();self.sql(self.prefix+(ROOT/'db/migrations/009_add_buyer_full_refund.sql').read_text(encoding='utf-8'))
  order='TKT-SEED-HELD-ses-concert-1001'
  for status in ['PENDING_PAYMENT','PAID','EXPIRED','CANCELLED']:
   for paid in [False,True]:
    for refunded in [False,True]:
     valid=(status in ['PENDING_PAYMENT','EXPIRED'] and not paid and not refunded) or (status=='PAID' and paid and not refunded) or (status=='CANCELLED' and paid==refunded)
     sql=f"UPDATE orders SET status='{status}',paid_at={'now()' if paid else 'NULL'},refunded_at={'now()' if refunded else 'NULL'} WHERE id='{order}';"
     self.sql(self.prefix+'BEGIN;'+sql+'ROLLBACK;',valid)
  self.sql(self.prefix+f"BEGIN;UPDATE orders SET status='CANCELLED',paid_at=now(),refunded_at=now()-interval '1 second' WHERE id='{order}';ROLLBACK;",False)
  for currency in ['USD','cn','cnyy','123']:
   self.sql(self.prefix+f"INSERT INTO payment_attempts(id,order_id,status,started_at,processing_deadline,currency) VALUES('bad','{order}','PROCESSING',now(),now()+interval '1 second','{currency}');",False)
  for n in ['a','b']:
   self.sql(self.prefix+f"INSERT INTO payment_attempts(id,order_id,status,started_at,processing_deadline,completed_at,currency) VALUES('{n}','{order}','SUCCEEDED',now(),now()+interval '1 second',now(),'cny');")
  def insert(id,attempt,source,reason,currency='cny'):
   return f"INSERT INTO refunds(id,order_id,payment_attempt_id,amount,source,reason,status,next_reconcile_at,currency) VALUES('{id}','{order}','{attempt}',12800,'{source}','{reason}','PROCESSING',now(),'{currency}');"
  for source,reason in [('BUYER','PAYMENT_NOT_ACCEPTED'),('SYSTEM','BUYER_REQUESTED')]:self.sql(self.prefix+insert('bad','a',source,reason),False)
  self.sql(self.prefix+insert('r','a','BUYER','BUYER_REQUESTED'))
  self.sql(self.prefix+insert('r2','b','BUYER','BUYER_REQUESTED'),False)
  self.sql(self.prefix+insert('r2','a','SYSTEM','PAYMENT_NOT_ACCEPTED'),False)
  self.sql(self.prefix+insert('r2','b','SYSTEM','PAYMENT_NOT_ACCEPTED'))
  self.sql(self.prefix+"UPDATE refunds SET currency='CNY' WHERE id='r';",False)
  for t in ['REFUND_COMPLETED','REFUND_FAILED','AUTO_REFUND_COMPLETED','AUTO_REFUND_FAILED']:
   self.sql(self.prefix+f"INSERT INTO user_notifications(id,user_id,order_id,type,title,message,dedupe_key) VALUES('{t}','U-SEED-HOLDER','{order}','{t}','test','test','{t}');")
 def test_unchanged_performance_verifier_checks_paid_null_pointer(self):
  self.setup_schema();self.sql(self.prefix+(ROOT/'db/migrations/009_add_buyer_full_refund.sql').read_text(encoding='utf-8'))
  self.sql(self.prefix+"""
   INSERT INTO app_users(id,display_name,username,password_hash,status) VALUES('perf-user-p12','test','perf-p12','!disabled','DISABLED');
   INSERT INTO sessions(id,event_id,venue_id,hall_name,start_time,gate_time,status) SELECT 'perf-session-p12',event_id,venue_id,hall_name,start_time,gate_time,status FROM sessions WHERE id='ses-concert-1001';
   INSERT INTO session_seats(id,session_id,seat_id,venue_id,status,price) SELECT 'perf-ss-p12','perf-session-p12',seat_id,venue_id,'SOLD',price FROM session_seats WHERE id='ses-concert-1001-A01';
   INSERT INTO reservations(id,user_id,session_id,status,expires_at) VALUES('perf-r-p12','perf-user-p12','perf-session-p12','CONFIRMED',now()+interval '1 day');
   INSERT INTO reservation_session_seats(reservation_id,session_id,session_seat_id,reserved_price) SELECT 'perf-r-p12','perf-session-p12',id,price FROM session_seats WHERE id='perf-ss-p12';
   INSERT INTO orders(id,user_id,reservation_id,status,total_amount,expires_at,paid_at) SELECT 'perf-o-p12','perf-user-p12','perf-r-p12','PAID',price,now()+interval '1 day',now() FROM session_seats WHERE id='perf-ss-p12';
   INSERT INTO payment_attempts(id,order_id,status,started_at,processing_deadline,completed_at,accepted_at,currency) VALUES('perf-a-p12','perf-o-p12','SUCCEEDED',now(),now()+interval '1 second',now(),now(),'cny');
  """)
  verifier=(ROOT/'../performance/verification/verify.sql').read_text(encoding='utf-8')
  rows=self.sql(self.prefix+verifier).splitlines()[1:]
  self.assertTrue(rows);self.assertTrue(all(row.endswith('|0') for row in rows),rows)
  self.sql(self.prefix+"UPDATE session_seats SET current_reservation_id='perf-r-p12' WHERE id='perf-ss-p12';")
  self.assertIn('confirmed_state_mismatch|1',self.sql(self.prefix+verifier))
if __name__=='__main__': unittest.main(verbosity=2)
