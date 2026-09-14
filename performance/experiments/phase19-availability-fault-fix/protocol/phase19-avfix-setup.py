from pathlib import Path
import json, subprocess, time, os, sys, secrets
root=Path(r'<PHASE19_WORKTREE>')
out=Path(os.environ['TEMP'])/'phase19-avfix-regression';out.mkdir(exist_ok=True)
prefix='phase18-phase19-avfix';network='phase19-avfix-regression-data'
def run(*args,stdin=None):
 p=subprocess.run(list(map(str,args)),input=stdin,capture_output=True,text=True,encoding='utf-8')
 if p.returncode: raise RuntimeError(str(args[:3])+' '+p.stderr[-1500:])
 return p.stdout.strip()
def sql(text):return run('docker','exec','-i',prefix+'-postgres','psql','-U','postgres','-qAt','-v','ON_ERROR_STOP=1',stdin=text)
run('docker','network','create','--internal',network)
run('docker','network','create','phase19-avfix-regression-ingress')
for role,tag in [('postgres','postgres:16-alpine'),('redis','redis:7.4-alpine')]:
 args=['docker','run','-d','--name',prefix+'-'+role,'--label','phase19.owner=stage0','--network',network,'--network-alias',role,'--cpus','1','--memory','512m','--pids-limit','128','--ulimit','nofile=4096:4096']
 if role=='postgres':args+=['-e','POSTGRES_HOST_AUTH_METHOD=trust']
 run(*args,tag,*(['-c','shared_preload_libraries=pg_stat_statements','-c','pg_stat_statements.track=all'] if role=='postgres' else []))
for i in range(50):
 try:sql('SELECT 1');break
 except RuntimeError:time.sleep(.2)
else:raise RuntimeError('PG not ready')
sql('CREATE EXTENSION IF NOT EXISTS pg_stat_statements')
for path in sorted((root/'backend/db/migrations').glob('*.sql')):sql(path.read_text(encoding='utf-8'))
sql((root/'backend/db/seeds/001_demo_seed.sql').read_text(encoding='utf-8'))
config=json.loads((root/'backend/config/config.phase14.json').read_text())
config['db_clients'][0].update(dbname='postgres',user='postgres',passwd='')
config['custom_config']['authentication']['allowed_origins']+=['http://127.0.0.1:18440']
(out/'config.json').write_text(json.dumps(config))
print('Fresh Phase19 regression database and Redis prepared.',flush=True)
(out/'ticketing_backend').write_bytes((Path(os.environ['TEMP'])/'phase19-stage0-private/ticketing_backend').read_bytes())
env=dict(os.environ,TICKETING_ADMISSION_HMAC_SECRET=secrets.token_hex(32))
args=['docker','run','-d','--name',prefix+'-api','--label','phase19.owner=stage0','--network',network,'--cpus','2','--memory','1g','--pids-limit','256','--ulimit','nofile=4096:4096','-p','127.0.0.1:18432:8080','--mount',f'type=bind,source={out},target=/stage0,readonly','-e','TICKETING_ADMISSION_HMAC_SECRET','--entrypoint','/stage0/ticketing_backend','phase14-engineering-build:20260910-v3','/stage0/config.json']
p=subprocess.run(args,env=env,capture_output=True,text=True)
if p.returncode:raise RuntimeError(p.stderr)
run('docker','network','connect','phase19-avfix-regression-ingress',prefix+'-api')
import urllib.request
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
for i in range(100):
 try:
  if opener.open('http://127.0.0.1:18432/health',timeout=2).status==200:break
 except OSError:time.sleep(.2)
else:raise RuntimeError('API not ready')
print('Regression topology ready',flush=True)
