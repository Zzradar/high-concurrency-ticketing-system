"""Real purchase/payment/buyer refund, then unchanged positive and rollback-negative verifier assertions."""
import os,subprocess,unittest,time,uuid
os.environ['PHASE16_BASE_URL']=os.environ['TICKETING_BASE_URL']
from auth_test_support import AuthenticatedClient,test_user_values,username_for_user
from phase11_stripe_integration_test import fake,wait_until

def sql(statement):
 r=subprocess.run(['docker','compose','exec','-T','postgres','psql','-U','ticketing','-d','ticketing','-qAt','-v','ON_ERROR_STOP=1'],input=statement,text=True,encoding='utf-8',capture_output=True)
 if r.returncode:raise AssertionError(r.stderr)
 return r.stdout.strip()
user='perf-user-160001'
sql('INSERT INTO app_users(id,display_name,username,password_hash,status) VALUES '+test_user_values([user])+' ON CONFLICT(id) DO NOTHING')
client=AuthenticatedClient(username_for_user(user));client.login()
fake('/__admin__/reset',{});fake('/__admin__/configure',{'paymentMode':'succeeded','refundMode':'succeeded'})
# Restore the dedicated demo session's refund window after legacy negative eligibility fixtures.
sql("UPDATE sessions SET gate_time=start_time-interval '1 hour' WHERE id='ses-concert-1001'")
status,body,_=client.request('/reservations',method='POST',body={'sessionId':'ses-concert-1001','seatIds':['ses-concert-1001-A01']},headers={'Idempotency-Key':'p18-verifier-'+uuid.uuid4().hex});assert status==201,(status,body)
order=body['order']['id'];status,body,_=client.request('/orders/'+order+'/pay',method='POST');assert status==202,(status,body)
wait_until(lambda:sql("SELECT status FROM orders WHERE id='"+order+"'")=='PAID')
status,body,_=client.request('/orders/'+order+'/refunds',method='POST');assert status==202,(status,body)
refund=body['refund']['id'];wait_until(lambda:sql("SELECT status FROM refunds WHERE id='"+refund+"'")=='SUCCEEDED')
import phase16_api_test
phase16_api_test.sql=sql
import phase16_refund_verifier_test as original
result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(original))
print('Real reservation -> payment -> BUYER refund SUCCEEDED; original positive/missing/wrong-amount verifier assertions')
raise SystemExit(not result.wasSuccessful())
