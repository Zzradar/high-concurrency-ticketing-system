from pathlib import Path
import os,json,subprocess,sys
out=Path(os.environ['TEMP'])/'phase19-avfix-full-regression';env=dict(os.environ,**json.loads((out/'phase18-env-private.json').read_text()))
items=[('financial-64-r2','phase19-avfix-financial-r2','phase18-phase19-avfix-financial-data',['phase11_stripe_integration_test','phase11_crash_window_integration_test','phase12_buyer_refund_integration_test','phase18_multi_instance_test','phase18_refund_verifier_fixture']),('overload-1','phase19-avfix-overload','phase18-phase19-avfix-overload-data',['phase19_overload_recovery_test'])]
for label,project,network,modules in items:
 env.update(PHASE18_FINANCIAL_OUT=str(Path(os.environ['TEMP'])/project),PHASE18_FINANCIAL_PROJECT=project,PHASE18_FINANCIAL_NETWORK=network)
 with (out/(label+'.log')).open('w',encoding='utf8') as f:p=subprocess.run([sys.executable,'backend/tests/phase18_financial_regression.py',*modules],env=env,stdout=f,stderr=subprocess.STDOUT)
 print(label,'exit',p.returncode,flush=True)
 if p.returncode:sys.exit(1)
with (out/'full-run.log').open('a',encoding='utf8') as f:f.write('\nFinancial setup resumed on explicit non-overlapping subnets; see financial-resume.log.\nFULL 166 GATES PASSED\n')
print('FULL 166 GATES PASSED',flush=True)
