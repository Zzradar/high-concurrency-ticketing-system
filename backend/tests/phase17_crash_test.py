"""Actual Phase15 formal-commit crash under the Phase17 binary and schema."""
import os,sys,unittest,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
os.environ.update(PHASE15_BASE_URL='http://127.0.0.1:18117',PHASE15_POSTGRES_CONTAINER='phase17-postgres',PHASE15_REDIS_CONTAINER='phase17-redis')
sys.path.insert(0,str(ROOT/'performance/scripts'))
from run_phase17_phase16_faults import original as docker,backend
import auth_test_support as auth
from phase15_test_support import sql,until
class CrashTest(unittest.TestCase):
 def test_formal_commit_survives_process_crash_and_sales_end(self):
  from phase15_checkout_test import CheckoutSalesTest
  fixture=CheckoutSalesTest();fixture.setUp();name='phase17-checkout-fault-'+uuid.uuid4().hex[:8]
  try:
   status,checkout,_=fixture.create();self.assertEqual(status,201)
   backend('stop')
   docker('run','-d','--name',name,'--network','phase17-batch1','-p','127.0.0.1:18119:8080','-e','PHASE15_FAULT_AFTER_FORMAL_COMMIT=1','--mount','type=bind,source='+str(ROOT/'backend/build/phase17')+',target=/phase17,readonly','--workdir','/tmp','--entrypoint','/phase17/ticketing_backend','phase14-engineering-build:20260910-v3','/phase17/config.json')
   auth.BASE_URL='http://127.0.0.1:18119'
   def healthy():
    try:return fixture.c.request('/health',timeout=1)[0]==200
    except Exception:return False
   until(healthy)
   try:fixture.confirm(checkout)
   except Exception:pass
   until(lambda:docker('inspect','-f','{{.State.Running}}',name)=='false')
   self.assertEqual(docker('inspect','-f','{{.State.ExitCode}}',name),'88')
   self.assertEqual(sql("SELECT status FROM checkout_sessions WHERE id='"+checkout['id']+"';"),'SUBMITTING')
   order=sql("SELECT id FROM orders WHERE user_id='"+fixture.user+"';");self.assertTrue(order)
   fixture.window('ENDED');auth.BASE_URL='http://127.0.0.1:18117';backend('start');until(healthy)
   status,body,_=fixture.confirm(checkout);self.assertEqual(status,200,body);self.assertEqual(body['checkoutSession']['order']['id'],order)
   self.assertEqual(sql("SELECT count(*) FROM orders WHERE user_id='"+fixture.user+"';"),'1')
  finally:
   auth.BASE_URL='http://127.0.0.1:18117'
   if not docker('exec','phase17-build','sh','-c','kill -0 $(cat /tmp/p17-api.pid) 2>/dev/null && echo yes || true'):backend('start')
   fixture.doCleanups()
if __name__=='__main__':unittest.main(verbosity=2)
