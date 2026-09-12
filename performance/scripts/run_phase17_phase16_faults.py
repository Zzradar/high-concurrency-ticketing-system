"""Run unchanged Phase16 assertions through an explicitly isolated Phase17 process adapter."""
import json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
os.environ.update(PHASE16_BASE_URL='http://127.0.0.1:18117',PHASE16_POSTGRES_CONTAINER='phase17-postgres',PHASE16_REDIS_CONTAINER='phase17-redis',PHASE16_OUTPUT=str(ROOT/'performance/experiments/phase17-admin-publishing/phase16'))
import phase16_system_test as gate
original=gate.docker

def backend(action):
 if action=='stop':return original('exec','phase17-build','sh','-c','kill $(cat /tmp/p17-api.pid)')
 return original('exec','-d','-w','/work/backend','phase17-build','sh','-c','echo $$ > /tmp/p17-api.pid; exec /phase17-build/ticketing_backend /tmp/phase17-config.json > /tmp/p17-api.log 2>&1')
def docker(*args):
 if len(args)>1 and args[1]=='phase16-api-backend':return backend(args[0])
 return original(*[{'phase16-api-redis':'phase17-redis','phase16-fault-projector':'phase17-fault-projector','phase16-fault-init':'phase17-fault-init'}.get(a,a) for a in args])
def fault(name,flag):
 name=name.replace('phase16','phase17')
 assert not original('ps','-a','--filter','name=^/'+name+'$','--format','{{.ID}}'),'Refuse existing fault container'
 return original('run','-d','--name',name,'--network','phase17-batch1','-p','127.0.0.1:18118:8080','-e',flag+'=1','--mount','type=bind,source='+str(ROOT/'backend/build/phase17')+',target=/phase17,readonly','--workdir','/tmp','--entrypoint','/phase17/ticketing_backend','phase14-engineering-build:20260910-v3','/phase17/config.json')
gate.docker=docker;gate.fault_backend=fault
oldrequest,oldhealthy=gate.request,gate.healthy
gate.request=lambda base=gate.BASE,**params:oldrequest(base.replace(':18097',':18118'),**params)
gate.healthy=lambda base=gate.BASE:oldhealthy(base.replace(':18097',':18118'))
if __name__=='__main__':
 try:gate.main()
 finally:
  running=original('exec','phase17-build','sh','-c','kill -0 $(cat /tmp/p17-api.pid) 2>/dev/null && echo yes || true')
  if not running:backend('start')
