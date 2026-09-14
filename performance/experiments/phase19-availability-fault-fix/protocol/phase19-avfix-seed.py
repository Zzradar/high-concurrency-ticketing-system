import os,sys,subprocess,json,importlib.util
from pathlib import Path
root=Path(r'<PHASE19_WORKTREE>');out=Path(os.environ['TEMP'])/'phase19-avfix-regression'
prefix='phase18-phase19-avfix'
def run(*args,stdin=None):
 p=subprocess.run(list(map(str,args)),input=stdin,capture_output=True,text=True,encoding='utf-8')
 if p.returncode:raise RuntimeError(p.stderr[-1500:])
 return p.stdout.strip()
def sql(q):return run('docker','exec','-i',prefix+'-postgres','psql','-U','postgres','-qAt','-v','ON_ERROR_STOP=1',stdin=q)
spec=importlib.util.spec_from_file_location('phase18_seed',root/'performance/experiments/phase18-admission-overload/protocol/seed.py');seed=importlib.util.module_from_spec(spec);spec.loader.exec_module(seed)
seed.seed(sql)
run('docker','run','-d','--name',prefix+'-no-secret-api','--label','phase19.owner=stage0','--network','phase19-avfix-regression-data','--cpus','2','--memory','1g','--pids-limit','256','--ulimit','nofile=4096:4096','-p','127.0.0.1:18434:8080','--mount',f'type=bind,source={out},target=/stage0,readonly','--entrypoint','/stage0/ticketing_backend','phase14-engineering-build:20260910-v3','/stage0/config.json')
run('docker','network','connect','phase19-avfix-regression-ingress',prefix+'-no-secret-api')
env=dict(os.environ,PHASE18_BASE_URL='http://127.0.0.1:18432',PHASE18_NO_SECRET_BASE_URL='http://127.0.0.1:18434',PHASE18_POSTGRES_CONTAINER=prefix+'-postgres',PHASE18_REDIS_CONTAINER=prefix+'-redis',PHASE18_FAULT_API=prefix+'-api',PHASE18_FAULT_CONFIG=str(out/'config.json'),PHASE18_FIXTURE_PREFIX=prefix,PHASE18_FIXTURE_DATA_NETWORK='phase19-avfix-regression-data',PHASE18_FIXTURE_INGRESS_NETWORK='phase19-avfix-regression-ingress',PHASE18_BINARY=str(out/'ticketing_backend'),PHASE18_CRASH_DIR=str(out/'checkout-crash'),PHASE18_AVAILABILITY_FAULT_DIR=str(out/'availability-fault'),PYTHONUTF8='1')
(out/'phase18-env-private.json').write_text(json.dumps({k:v for k,v in env.items() if k.startswith('PHASE18_') or k=='PYTHONUTF8'}))
