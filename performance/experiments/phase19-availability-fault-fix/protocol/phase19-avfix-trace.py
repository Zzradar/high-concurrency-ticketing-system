import os,sys,json,runpy,subprocess,urllib.request,urllib.error,time
from pathlib import Path
root=Path.cwd();out=Path(os.environ['TEMP'])/'phase19-avfix-regression'
os.environ.update(json.loads((out/'phase18-env-private.json').read_text()))
sys.path.insert(0,str(root/'backend/tests'))
realrun=subprocess.run;realopen=urllib.request.urlopen
trace=[]
def snapshot():
 base=os.environ['PHASE18_BASE_URL'];pg=os.environ['PHASE18_POSTGRES_CONTAINER'];redis=os.environ['PHASE18_REDIS_CONTAINER']
 def cmd(args):
  p=realrun(args,capture_output=True,text=True);return {'exit':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
 record={'time':time.time(),'beforeRedisStop':True}
 try:record['metrics']=realopen(base+'/metrics',timeout=5).read().decode()
 except Exception as e:record['metricsError']=str(e)
 record['redis']=cmd(['docker','exec',redis,'redis-cli','EXISTS','ticketing:seat-availability:{p18-s-5000}:init-lock'])
 record['sql']=cmd(['docker','exec',pg,'psql','-U','postgres','-qAt','-c',"SELECT count(*) FROM seat_availability_outbox; SELECT mode,count(*) FROM event_admission_policies GROUP BY mode; SELECT state,wait_event_type,count(*) FROM pg_stat_activity WHERE datname=current_database() GROUP BY state,wait_event_type;"])
 trace.append(record)
def run(args,*a,**kw):
 if args[:3]==['docker','stop',os.environ['PHASE18_REDIS_CONTAINER']]:snapshot()
 return realrun(args,*a,**kw)
def urlopen(*a,**kw):
 try:return realopen(*a,**kw)
 except urllib.error.HTTPError as e:
  body=e.read();trace.append({'time':time.time(),'url':str(a[0]),'status':e.code,'body':body.decode()});print('HTTP FAILURE',e.code,body.decode(),flush=True);raise
subprocess.run=run;urllib.request.urlopen=urlopen
label=sys.argv[1];sys.argv=[str(root/'backend/tests/phase18_availability_fault_test.py')]
try:runpy.run_path(sys.argv[0],run_name='__main__')
finally:(out/(label+'-trace.json')).write_bytes(json.dumps(trace,indent=2).encode())
