from pathlib import Path
import os,json,subprocess,sys
out=Path(os.environ['TEMP'])/'phase19-avfix-full-regression';root=Path.cwd();env=dict(os.environ,**json.loads((out/'phase18-env-private.json').read_text()))
def execute(label,args):
 with (out/(label+'.log')).open('w',encoding='utf8') as f:p=subprocess.run(args,env=env,cwd=root,stdout=f,stderr=subprocess.STDOUT)
 print(label+' exit='+str(p.returncode),flush=True)
 q="SELECT mode,count(*) FROM event_admission_policies GROUP BY mode; SELECT count(*) FROM seat_availability_outbox;"
 x=subprocess.run(['docker','exec',env['PHASE18_POSTGRES_CONTAINER'],'psql','-U','postgres','-qAt','-c',q],capture_output=True,text=True)
 (out/(label+'-state.txt')).write_text(x.stdout)
 return p.returncode
if execute('ordered-off',[sys.executable,'backend/tests/phase18_off_regression.py']):sys.exit(1)
modules=['phase18_schema_test','phase18_token_bucket_test','phase18_waiting_room_test','phase18_public_contract_test','phase18_policy_http_test','phase18_admission_http_test','phase18_traffic_http_test','phase18_metrics_http_test','phase18_layout_http_test','phase18_layout_revision_http_test','phase18_layout_resolution_http_test','phase18_inventory_fault_test','phase18_checkout_crash_test']
for name in modules:
 if execute('ordered-'+name,[sys.executable,'backend/tests/'+name+'.py']):sys.exit(1)
if execute('ordered-availability',[sys.executable,str(Path(os.environ['TEMP'])/'phase19-avfix-full-trace.py'),'ordered-availability']):sys.exit(1)

if execute('ordered-phase18_verifier_test',[sys.executable,'backend/tests/phase18_verifier_test.py']):sys.exit(1)
env.update(PHASE18_FINANCIAL_OUT=str(Path(os.environ['TEMP'])/'phase19-avfix-financial'),PHASE18_FINANCIAL_PROJECT='phase19-avfix-financial')
if execute('financial-64',[sys.executable,'backend/tests/phase18_financial_regression.py','phase11_stripe_integration_test','phase11_crash_window_integration_test','phase12_buyer_refund_integration_test','phase18_multi_instance_test','phase18_refund_verifier_fixture']):sys.exit(1)
env.update(PHASE18_FINANCIAL_OUT=str(Path(os.environ['TEMP'])/'phase19-avfix-overload'),PHASE18_FINANCIAL_PROJECT='phase19-avfix-overload')
if execute('overload-1',[sys.executable,'backend/tests/phase18_financial_regression.py','phase19_overload_recovery_test']):sys.exit(1)
print('FULL 166 GATES PASSED',flush=True)
