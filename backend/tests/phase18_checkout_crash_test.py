"""Actual process exit after formal commit on the Phase18 candidate; original Phase15 assertions."""
import os,sys,json,secrets,subprocess,unittest,uuid
from pathlib import Path
import phase18_off_regression
import auth_test_support as auth
from phase15_test_support import sql,until
class CheckoutCrash(unittest.TestCase):
 def test_committed_order_recovers_after_crash_and_sales_end(self):
  from phase15_checkout_test import CheckoutSalesTest
  fixture=CheckoutSalesTest();fixture.setUp();self.addCleanup(fixture.doCleanups)
  folder=Path(os.environ['PHASE18_CRASH_DIR']);folder.mkdir(parents=True,exist_ok=True)
  values=json.loads(Path(os.environ['PHASE18_FAULT_CONFIG']).read_text());values['app']['number_of_threads']=4
  (folder/'config.json').write_text(json.dumps(values),encoding='utf-8')
  name='phase18-checkout-crash-'+uuid.uuid4().hex[:8]
  def docker(*args):
   p=subprocess.run(['docker',*args],capture_output=True,text=True,encoding='utf-8')
   if p.returncode:raise AssertionError(p.stderr)
   return p.stdout.strip()
  status,checkout,_=fixture.create();self.assertEqual(status,201,checkout)
  def restore():
   auth.BASE_URL=os.environ['PHASE18_BASE_URL']
   docker('stop',name)
   docker('start','phase18-policy-api','phase18-policy-no-secret-api')
   def healthy():
    try:return fixture.c.request('/health')[0]==200
    except Exception:return False
   until(healthy,seconds=20)
  self.addCleanup(restore)
  docker('create','--name',name,'--network','phase18-policy-data','-p','127.0.0.1:18189:8080','--cpus','2','--memory','1g','--pids-limit','256','-e','PHASE15_FAULT_AFTER_FORMAL_COMMIT=1','-e','TICKETING_ADMISSION_HMAC_SECRET='+secrets.token_hex(32),'--mount','type=bind,source='+str(Path(os.environ['PHASE18_BINARY']))+',target=/sut/ticketing_backend,readonly','--mount','type=bind,source='+str(folder/'config.json')+',target=/sut/config.json,readonly','--workdir','/tmp','--entrypoint','/sut/ticketing_backend','phase14-engineering-build:20260910-v3','/sut/config.json')
  docker('network','connect','phase18-policy-ingress',name)
  docker('stop','phase18-policy-api','phase18-policy-no-secret-api');docker('start',name)
  auth.BASE_URL='http://127.0.0.1:18189'
  def healthy():
   try:return fixture.c.request('/health')[0]==200
   except Exception:return False
  until(healthy,seconds=20)
  try:fixture.confirm(checkout)
  except Exception:pass
  until(lambda:docker('inspect','-f','{{.State.Running}}',name)=='false')
  self.assertEqual(docker('inspect','-f','{{.State.ExitCode}}',name),'88')
  self.assertEqual(sql("SELECT status FROM checkout_sessions WHERE id='"+checkout['id']+"'"),'SUBMITTING')
  order=sql("SELECT id FROM orders WHERE user_id='"+fixture.user+"'");self.assertTrue(order)
  fixture.window('ENDED');auth.BASE_URL=os.environ['PHASE18_BASE_URL'];docker('start','phase18-policy-api');until(healthy,seconds=20)
  status,body,_=fixture.confirm(checkout);self.assertEqual(status,200,body);self.assertEqual(body['checkoutSession']['order']['id'],order)
  self.assertEqual(sql("SELECT count(*) FROM orders WHERE user_id='"+fixture.user+"'"),'1')
  print('actual exit=88 after formal commit; SUBMITTING persisted; after sales end confirm=200, same order, exactly one order')
if __name__=='__main__':unittest.main(verbosity=2)
