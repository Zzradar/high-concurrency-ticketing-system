"""Run unchanged simulation payment assertions on the dedicated Phase15 stack.
Only the psql transport is redirected; test methods and business assertions are reused.
"""
import os,sys,subprocess,unittest
os.environ['TICKETING_BASE_URL']='http://127.0.0.1:18095'
import payment_integration_test as payment

def sql(statement):
    result=subprocess.run(['docker','exec','-i','phase15-api-postgres','psql','-U','postgres','-qAt','-F','\t','-v','ON_ERROR_STOP=1'],input=statement,capture_output=True,text=True,encoding='utf-8')
    if result.returncode:raise AssertionError(result.stderr)
    return result.stdout.strip()
payment.psql=sql
if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(payment))
    raise SystemExit(not result.wasSuccessful())
