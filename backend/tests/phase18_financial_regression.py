"""Original Phase11/12 tests on an exclusively owned Phase18 Compose stack.
Only temporary fixture configuration and container topology are added. No real provider credentials.
"""
import json,os,secrets,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(os.environ['PHASE18_FINANCIAL_OUT']).resolve();OUT.mkdir(parents=True,exist_ok=True)
BINARY=Path(os.environ['PHASE18_BINARY']).resolve();assert BINARY.is_file()
config=json.loads((ROOT/'backend/config/config.phase14.json').read_text())
db=config['db_clients'][0];db.update(dbname='ticketing',user='ticketing',passwd='')
config['app']['number_of_threads']=4
# Capability fault suite only: bounded threads, same four PG connections; not formal A/B.
(OUT/'config.json').write_text(json.dumps(config),encoding='utf-8')
env=dict(os.environ,COMPOSE_PROJECT_NAME=os.environ.get('PHASE18_FINANCIAL_PROJECT','phase18-financial'),COMPOSE_FILE=str(OUT/'phase18-phase12-regression.json'),TICKETING_BASE_URL='http://127.0.0.1:18186',FAKE_STRIPE_URL='http://127.0.0.1:18187',TICKETING_PAYMENT_PROVIDER='stripe',STRIPE_SECRET_KEY='sk_test_'+secrets.token_hex(24),STRIPE_WEBHOOK_SECRET='whsec_'+secrets.token_hex(24),TICKETING_ADMISSION_HMAC_SECRET=secrets.token_hex(32),STRIPE_PROCESSING_GRACE_SECONDS='600',PYTHONUTF8='1')
mounts=[str(p)+':/docker-entrypoint-initdb.d/'+p.name+':ro' for p in sorted((ROOT/'backend/db/migrations').glob('*.sql'))]+[str(ROOT/'backend/db/seeds/001_demo_seed.sql')+':/docker-entrypoint-initdb.d/100_demo_seed.sql:ro']
compose={'services':{
 'postgres':{'image':'postgres:16-alpine','environment':{'POSTGRES_DB':'ticketing','POSTGRES_USER':'ticketing','POSTGRES_HOST_AUTH_METHOD':'trust'},'volumes':mounts,'cpus':1,'mem_limit':'512m','healthcheck':{'test':['CMD-SHELL','pg_isready -U ticketing -d ticketing'],'interval':'2s','timeout':'2s','retries':30}},
 'redis':{'image':'redis:7.4-alpine','cpus':1,'mem_limit':'512m'},
 'fake-stripe':{'image':'python:3.12-alpine','command':['python','/tests/fake_stripe_server.py','--port','18081'],'ports':['127.0.0.1:18187:18081'],'volumes':[str(ROOT/'backend/tests/fake_stripe_server.py')+':/tests/fake_stripe_server.py:ro'],'cpus':1,'mem_limit':'256m'},
 'backend':{'image':'phase14-engineering-build:20260910-v3','entrypoint':['stdbuf','-oL', '/sut/ticketing_backend'],'command':['/sut/config.json'],'working_dir':'/tmp','ports':['127.0.0.1:18186:8080'],'volumes':[str(BINARY)+':/sut/ticketing_backend:ro',str(OUT/'config.json')+':/sut/config.json:ro'],'cpus':2,'mem_limit':'1g','pids_limit':256,'depends_on':{'postgres':{'condition':'service_healthy'},'redis':{'condition':'service_started'},'fake-stripe':{'condition':'service_started'}},'environment':{k:'${'+k+'}' for k in ['TICKETING_PAYMENT_PROVIDER','STRIPE_SECRET_KEY','STRIPE_WEBHOOK_SECRET','TICKETING_ADMISSION_HMAC_SECRET','STRIPE_PROCESSING_GRACE_SECONDS']}}
}}
compose['services']['backend']['environment'].update(STRIPE_API_BASE_URL='http://fake-stripe:18081',STRIPE_HTTP_TIMEOUT_SECONDS='15',STRIPE_CURRENCY='cny')
network=os.environ.get('PHASE18_FINANCIAL_NETWORK')
if network:
 assert network.startswith('phase18')
 compose['networks']={'default':{'external':True,'name':network}}
Path(env['COMPOSE_FILE']).write_text(json.dumps(compose),encoding='utf-8')
def run(args,log):
 with (OUT/log).open('w',encoding='utf-8') as stream:
  result=subprocess.run(args,cwd=ROOT/'backend',env=env,stdout=stream,stderr=subprocess.STDOUT)
 if result.returncode:raise RuntimeError(log+' failed; inspect sanitized local diagnostic')
try:
 run(['docker','compose','up','-d'],'setup.log')
 import urllib.request
 for i in range(150):
  try:
   if urllib.request.urlopen(env['TICKETING_BASE_URL']+'/health',timeout=1).status==200:break
  except Exception:time.sleep(.2)
 else:raise RuntimeError('Financial fixture did not become healthy')
 for module in sys.argv[1:] or ['phase11_stripe_integration_test','phase11_crash_window_integration_test','phase12_buyer_refund_integration_test']:
  run([sys.executable,str(ROOT/'backend/tests'/ (module+'.py'))],module+'.log')
  print(module+' PASS',flush=True)
finally:
 # Retain containers, database and logs for diagnostics; stop only this named Compose project.
 run(['docker','compose','logs','--no-color','backend'],'backend.log')
 run(['docker','compose','stop'],'stop.log')
