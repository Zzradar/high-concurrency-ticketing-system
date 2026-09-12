"""Phase18 fixed A/B protocol. Fresh named containers only; never resets or deletes existing state."""
import argparse,concurrent.futures,datetime,gzip,hashlib,json,os,subprocess,sys,threading,time,urllib.request
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from seed import seed
from stats import summary,phase_at,redis_cli_json
HERE=Path(__file__).resolve().parent
P=argparse.ArgumentParser();P.add_argument('action',choices=['setup','start','measure','manifest','stop']);P.add_argument('--root',type=Path,required=True);P.add_argument('--out',type=Path,required=True);P.add_argument('--prefix',default='phase18v2');P.add_argument('--build-container',default='phase18v2-build');A=P.parse_args()
ROOT=A.root;OUT=A.out;OUT.mkdir(parents=True,exist_ok=True);PREFIX=A.prefix
BASE='http://127.0.0.1:18182';PG=PREFIX+'-postgres';REDIS=PREFIX+'-redis';API=PREFIX+'-api';FRONT=PREFIX+'-frontend'
def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(*args,stdin=None,timeout=120):
 p=subprocess.run([str(a) for a in args],input=stdin,capture_output=True,text=True,encoding='utf-8',timeout=timeout)
 if p.returncode:raise RuntimeError('Command failed: '+str(args[:3])+'\n'+p.stderr[-3000:])
 return p.stdout.strip()
def sql(q):return run('docker','exec','-i',PG,'psql','-U','postgres','-d','ticketing','-qAt','-v','ON_ERROR_STOP=1',stdin=q)
def redis(*args):return redis_cli_json(args[0],run('docker','exec',REDIS,'redis-cli','--json',*args))
def save(name,data): (OUT/name).write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
def inspect(name):return json.loads(run('docker','inspect',name))[0]
def images():return json.loads((OUT/'images.json').read_text(encoding='utf-8'))
def setup():
 assert run('git','-C',ROOT,'status','--porcelain')=='','SUT must be clean'
 save('source.json',{'sha':run('git','-C',ROOT,'rev-parse','HEAD'),'gitDirty':False,'commit':run('git','-C',ROOT,'show','-s','--format=%H %cI %P'),'startedUtc':utc(),'scripts':{p.name:sha(p) for p in HERE.iterdir() if p.is_file()}})
 refs={}
 for role,tag in {'toolchain':'phase14-engineering-build:20260910-v3','postgres':'postgres:16-alpine','redis':'redis:7.4-alpine','nginx':'nginx:1.28-alpine','k6':'grafana/k6:2.2.0'}.items():
  value=inspect(tag);refs[role]={'tag':tag,'id':value['Id'],'repoDigests':value['RepoDigests']}
 save('images.json',refs)
 save('host.json',{'docker':json.loads(run('docker','info','--format','{"cpus":{{.NCPU}},"memory":{{.MemTotal}}}')),'otherContainers':run('docker','ps','--format','{{.Names}}').splitlines(),'capturedUtc':utc()})
 run('docker','network','create','--internal',PREFIX+'-data');run('docker','network','create',PREFIX+'-ingress')
 for role,name,extra in [('postgres',PG,['-e','POSTGRES_HOST_AUTH_METHOD=trust','-e','POSTGRES_DB=ticketing']),('redis',REDIS,[])]:
  args=['docker','run','-d','--name',name,'--network',PREFIX+'-data','--network-alias',role,'--cpus','1','--memory','512m','--pids-limit','128','--ulimit','nofile=4096:4096',*extra,refs[role]['id']]
  if role=='postgres':args+=['-c','shared_preload_libraries=pg_stat_statements','-c','pg_stat_statements.track=all']
  run(*args)
 for _ in range(50):
  try:sql('SELECT 1;');break
  except RuntimeError:time.sleep(.2)
 else:raise RuntimeError('PostgreSQL readiness timeout')
 for p in sorted((ROOT/'backend/db/migrations').glob('*.sql')):sql(p.read_text(encoding='utf-8'))
 sql('CREATE EXTENSION pg_stat_statements;');sql((ROOT/'backend/db/seeds/001_demo_seed.sql').read_text(encoding='utf-8'))
 save('data-fingerprint.json',seed(sql))
 config=json.loads((ROOT/'backend/config/config.phase14.json').read_text(encoding='utf-8'))
 config['db_clients'][0].update(user='postgres',passwd='');config['db_clients'][0]['connect_options']['application_name']='phase18_fixed_protocol'
 config['custom_config']['authentication']['allowed_origins']+=['http://127.0.0.1:18183']
 save('config.json',config)
 print('Fresh isolated data/config prepared.',flush=True)
def start():
 refs=images();run('docker','cp',A.build_container+':/phase18-build/ticketing_backend',OUT/'ticketing_backend')
 for name,role,cpus,memory,pids,port,mounts,extra in [
  (API,'toolchain','2','1g','256','18182',['--mount',f'type=bind,source={OUT},target=/evidence,readonly'],['--entrypoint','/evidence/ticketing_backend']),
  (FRONT,'nginx','0.5','128m','64','18183',['--mount',f'type=bind,source={ROOT / "frontend/dist"},target=/web,readonly','--mount',f'type=bind,source={HERE / "nginx.conf"},target=/etc/nginx/nginx.conf,readonly'],[])]:
  args=['docker','run','-d','--name',name,'--network',PREFIX+'-data','--network-alias','phase18v2-api' if name==API else 'phase18v2-frontend','--cpus',cpus,'--memory',memory,'--pids-limit',pids,'--ulimit','nofile=4096:4096','-p',f'127.0.0.1:{port}:8080',*mounts,*extra,refs[role]['id']]
  if name==API:args+=['/evidence/config.json']
  run(*args);run('docker','network','connect',PREFIX+'-ingress',name)
 for _ in range(50):
  try:
   if urllib.request.urlopen(BASE+'/health',timeout=2).status==200:break
  except OSError:time.sleep(.2)
 else:raise RuntimeError('API readiness timeout')
 print('Fresh isolated API/frontend ready.',flush=True)
def request(path,headers=None):
 started=time.perf_counter();start_epoch=time.time()
 try:r=urllib.request.urlopen(urllib.request.Request(BASE+path,headers=headers or {}),timeout=10)
 except HTTPError as e:r=e
 with r:raw=r.read();status=r.status;h=dict(r.headers)
 record={'startEpoch':start_epoch,'ms':(time.perf_counter()-started)*1000,'status':status,'bytes':len(raw),'gzipOfflineBytes':len(gzip.compress(raw,mtime=0)),'sha256':hashlib.sha256(raw).hexdigest(),'headers':{k:v for k,v in h.items() if k.lower() in ['etag','cache-control','content-encoding','vary']}}
 return record,raw
def snapshot(label):
 pg=json.loads(sql("SELECT coalesce(json_agg(x),'[]') FROM (SELECT queryid::text,query,calls,rows,total_exec_time FROM pg_stat_statements WHERE query NOT ILIKE '%pg_stat_statements%') x;"))
 save(label+'-database.json',{'at':utc(),'pg':pg,'redis':json.loads(redis('INFO','commandstats')),'pgDatabase':sql("SELECT xact_commit,xact_rollback,deadlocks,numbackends FROM pg_stat_database WHERE datname='ticketing';"),'connections':sql("SELECT application_name,state,wait_event_type,wait_event,count(*) FROM pg_stat_activity WHERE datname='ticketing' GROUP BY 1,2,3,4;")})
 (OUT/(label+'-metrics.txt')).write_bytes(urllib.request.urlopen(BASE+'/metrics',timeout=5).read())
def sample_resources(stop,rows,errors):
 while not stop.is_set():
  try:
   rows.append({'at':utc(),'containers':run('docker','stats','--no-stream','--format','{{json .}}',API,PG,REDIS,FRONT),
     'apiProcess':run('docker','exec',API,'sh','-c','cat /proc/1/status; cat /proc/1/stat; ls /proc/1/fd | wc -l; cat /sys/fs/cgroup/cpu.stat; cat /sys/fs/cgroup/memory.current; cat /sys/fs/cgroup/pids.current'),
     'pgWaits':sql("SELECT application_name,state,wait_event_type,wait_event,count(*) FROM pg_stat_activity WHERE datname='ticketing' GROUP BY 1,2,3,4;")})
  except Exception as e:errors.append(str(e))
  stop.wait(.5)
def reads():
 records=[]
 for n in (5000,10000):
  base=f'/sessions/p18-s-{n}';snapshot(f'layout-{n}-before');r,raw=request(base+'/seat-layout');assert r['status']==200 and len(json.loads(raw)['seats'])==n
  rows=[{'kind':'first',**r}];etag=next((v for k,v in r['headers'].items() if k.lower()=='etag'),'W/"baseline-no-tag"')
  for kind,headers in [('ordinary',{}),('conditional',{'If-None-Match':etag})]:
   for _ in range(20):item,_=request(base+'/seat-layout',headers);rows.append({'kind':kind,**item})
  gzip_wire,_=request(base+'/seat-layout',{'Accept-Encoding':'gzip'})
  records.append({'seatCount':n,'layout':rows,'gzipWire':gzip_wire,'summaries':{k:summary([r for r in rows if r['kind']==k]) for k in ['first','ordinary','conditional']}});snapshot(f'layout-{n}-after')
  path=base+'/seat-availability?zone=Zone%200';snapshot(f'availability-{n}-before');cold,body=request(path);data=json.loads(body);assert data['mode']=='snapshot'
  syncpath=path+'&'+urlencode({'generation':data['generation'],'since':data['cursor']})
  snaps=[request(path)[0] for _ in range(20)];deltas=[]
  for _ in range(20):item,body=request(syncpath);b=json.loads(body);assert b['mode']=='delta' and b['changes']==[];deltas.append(item)
  records[-1]['availability']={'coldSnapshot':cold,'snapshots':snaps,'emptyDeltas':deltas,'snapshotSummary':summary(snaps),'deltaSummary':summary(deltas)};snapshot(f'availability-{n}-after')
 save('reads.json',records)
def burst():
 os.environ['TICKETING_BASE_URL']=BASE;os.environ['TICKETING_TEST_ORIGIN']='http://127.0.0.1:18183';sys.path.insert(0,str(ROOT/'backend/tests'))
 from auth_test_support import AuthenticatedClient
 clients=[AuthenticatedClient(f'p18-user-{i}') for i in range(8)]
 for c in clients:c.login()
 barrier=threading.Barrier(8)
 def work(i):
  barrier.wait(timeout=10);started=time.perf_counter();begin=time.time()
  status,body,_=clients[i].request('/reservations',method='POST',body={'sessionId':'p18-s-5000','seatIds':['p18-s-5000-ss-00001']},headers={'Idempotency-Key':f'p18-burst-{i}'},timeout=15)
  return {'startEpoch':begin,'ms':(time.perf_counter()-started)*1000,'status':status,'code':body.get('code')}
 snapshot('burst-before')
 with concurrent.futures.ThreadPoolExecutor(max_workers=8)as pool:rows=list(pool.map(work,range(8)))
 save('burst.json',{'offered':8,'trials':1,'rows':rows,'summary':summary(rows)});snapshot('burst-after')
 assert sum(r['status']==201 for r in rows)==1 and sum(r['code']=='SEAT_CONFLICT' for r in rows)==7
def verifier():
 sys.path.insert(0,str(ROOT/'performance/verification'));sys.path.insert(0,str(ROOT/'backend/tests'))
 import phase17_verify,phase16_verify,phase15_verify
 checks={k:int(sql(v)) for k,v in phase17_verify.QUERIES.items()}
 def wait(fn):
  for _ in range(100):
   if fn():return
   time.sleep(.1)
  raise AssertionError('Verifier convergence timeout')
 phase15_verify.sql=sql;phase15_verify.redis=lambda *args:json.loads(redis(*args));phase15_verify.until=wait;phase15_verify.OUTPUT=OUT/'phase15-verifier';os.environ['PHASE15_BASE_URL']=BASE
 previous=phase15_verify.verify();save('verifier.json',{'passed':not any(checks.values()) and previous['passed'],'phase17':checks,'phase15And16':previous});assert not any(checks.values()) and previous['passed']
def measure():
 assert run('git','-C',ROOT,'status','--porcelain')==''
 source=json.loads((OUT/'source.json').read_text(encoding='utf-8'));assert source['scripts']=={p.name:sha(p) for p in HERE.iterdir() if p.is_file()},'Protocol changed after setup'
 rows=[];errors=[];stop=threading.Event();thread=threading.Thread(target=sample_resources,args=(stop,rows,errors));thread.start()
 save('measurement-start.json',{'utc':utc(),'requestOrder':['5000-layout','5000-snapshot-delta','10000-layout','10000-snapshot-delta','browser','k6','eight-user-burst','verifier']})
 try:
  reads();snapshot('browser-before')
  log=run('node',HERE/'browser.mjs',ROOT,OUT/'browser.json',OUT/'browser-profile',timeout=120);(OUT/'browser-run.log').write_text(log,encoding='utf-8');snapshot('browser-after')
  _,raw=request('/sessions/p18-s-5000/seat-availability?zone=Zone%200');body=json.loads(raw);snapshot('k6-before')
  k6=run('docker','run','--name',PREFIX+'-k6','--network',PREFIX+'-data','--cpus','1','--memory','256m','--pids-limit','128','--ulimit','nofile=4096:4096','--mount',f'type=bind,source={HERE},target=/protocol,readonly','--mount',f'type=bind,source={OUT},target=/evidence','-e','GENERATION='+body['generation'],'-e','CURSOR='+body['cursor'],images()['k6']['id'],'run','/protocol/k6.js',timeout=60)
  (OUT/'k6.log').write_text(k6,encoding='utf-8');snapshot('k6-after');burst();verifier();snapshot('final')
 finally:
  stop.set();thread.join();save('resource-samples.json',{'samples':rows,'errors':errors});save('measurement-end.json',{'utc':utc()})
  for name in [API,FRONT,PG,REDIS]:(OUT/(name+'.log')).write_text(run('docker','logs',name),encoding='utf-8')
 assert not errors,errors
 print('Complete protocol passed.',flush=True)
def manifest():
 configs={}
 for p in (ROOT/'backend/config').glob('*.json'):
  c=json.loads(p.read_text(encoding='utf-8'));configs[p.name]={'sha256':sha(p),'app':c['app'],'postgres':[{k:v for k,v in d.items() if k not in ['passwd','password']} for d in c['db_clients']],'redis':c['redis_clients'],'custom':c['custom_config']}
 containers={}
 for name in [A.build_container,API,FRONT,PG,REDIS,PREFIX+'-k6']:
  c=inspect(name);h=c['HostConfig'];containers[name]={'image':c['Image'],'state':c['State'],'limits':{k:h.get(k) for k in ['NanoCpus','Memory','MemorySwap','PidsLimit','Ulimits']},'ports':c['NetworkSettings']['Ports']}
 save('manifest.json',{'status':'STAGE0_VALID','source':json.loads((OUT/'source.json').read_text()),'images':images(),'configs':configs,'runtimeConfigSha256':sha(OUT/'config.json'),'binarySha256':sha(OUT/'ticketing_backend'),'containers':containers,'versions':{'node':run('node','--version'),'python':sys.version,'docker':run('docker','version','--format','{{json .}}'),'postgres':sql('SHOW server_version;'),'redis':json.loads(redis('INFO','server')),'k6':run('docker','run','--rm','--network','none',images()['k6']['id'],'version')},'protocol':{'seed':18,'warmup':0,'layoutOrdinary':20,'layoutConditional':20,'snapshot':20,'emptyDelta':20,'browserVisibleMs':60000,'browserHiddenMs':10000,'browserRestoreMs':10000,'k6Rate':8,'k6Seconds':15,'burstUsers':8,'trials':1,'quantile':'nearest rank'},'files':{str(p.relative_to(OUT)):{'sha256':sha(p),'bytes':p.stat().st_size} for p in OUT.rglob('*') if p.is_file() and 'browser-profile' not in p.parts and p.name not in ['manifest.json','ticketing_backend']},'limitations':['Shared host; isolated cgroups, not dedicated CPUs. No capacity/SLA claim.','Resource sampling approximately every 2-4 seconds; subinterval resource peaks may be missed. HTTP flow high-water from server metrics records request peaks.','gzipOfflineBytes is deterministic offline compression; gzipWire reports actual transport encoding.','Phase14 transaction acquisition histograms include only already-instrumented paths; SQL calls/rows are pg_stat_statements, not inferred.','All policies are absent/OFF at baseline; future enforced admission tests are additional scenarios.','Browser binary and Playwright version must match; external script hashes must equal committed copies before Stage0 commit.','Cold means first request to this fixture after fresh API start; no host page-cache flush.']})
def stop():run('docker','stop',API,FRONT,PG,REDIS)
globals()[A.action]()
