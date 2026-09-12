"""Actual process exit after formal commit, before Checkout finalization."""
import json, subprocess, unittest
from pathlib import Path
from phase15_checkout_test import CheckoutSalesTest
from phase15_test_support import sql, until
ROOT=Path(__file__).resolve().parents[2]
def docker(*args):
    result=subprocess.run(['docker',*args],capture_output=True,text=True,encoding='utf-8')
    if result.returncode:raise AssertionError(result.stderr)
    return result.stdout.strip()
class CrashRecoveryTest(unittest.TestCase):
    def test_committed_order_recovers_after_actual_crash_and_sales_end(self):
        collision=subprocess.run(['docker','inspect','phase15-fault-backend'],capture_output=True).returncode==0
        self.assertFalse(collision,'Refusing to reuse or remove an existing fault container')
        from phase15_checkout_test import CheckoutSalesTest
        fixture=CheckoutSalesTest();fixture.setUp()
        try:
            status,checkout,_=fixture.create();self.assertEqual(status,201,checkout)
            docker('stop','phase15-api-backend')
            docker('run','-d','--name','phase15-fault-backend','--network','phase15-test','-p','127.0.0.1:18095:8080','-e','PHASE15_FAULT_AFTER_FORMAL_COMMIT=1','--mount','type=bind,src='+str(ROOT/'backend/build/phase15')+',dst=/phase15,readonly','-w','/tmp','--entrypoint','/phase15/ticketing_backend','phase14-engineering-build:20260910-v3','/phase15/config.json')
            def healthy():
                try:return fixture.c.request('/health')[0]==200
                except Exception:return False
            until(healthy)
            try:fixture.confirm(checkout)
            except Exception:pass  # The response is lost by the deliberate process exit.
            until(lambda:docker('inspect','-f','{{.State.Running}}','phase15-fault-backend')=='false')
            self.assertEqual(docker('inspect','-f','{{.State.ExitCode}}','phase15-fault-backend'),'88')
            self.assertEqual(sql("SELECT status FROM checkout_sessions WHERE id='"+checkout['id']+"';"),'SUBMITTING')
            formal=sql("SELECT id FROM orders WHERE user_id='"+fixture.user+"';");self.assertTrue(formal)
            fixture.window('ENDED');docker('start','phase15-api-backend');until(healthy)
            status,body,_=fixture.confirm(checkout);self.assertEqual(status,200,body)
            self.assertEqual(body['checkoutSession']['order']['id'],formal)
            self.assertEqual(sql("SELECT count(*) FROM orders WHERE user_id='"+fixture.user+"';"),'1')
        finally:
            subprocess.run(['docker','rm','-f','phase15-fault-backend'],capture_output=True)
            docker('start','phase15-api-backend');fixture.doCleanups()
del CheckoutSalesTest
if __name__=='__main__':unittest.main(verbosity=2)
