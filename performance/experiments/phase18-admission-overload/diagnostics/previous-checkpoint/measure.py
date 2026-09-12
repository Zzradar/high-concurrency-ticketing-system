"""Fixed Phase18 A/B protocol. Run against fresh isolated data on each side."""
import argparse,concurrent.futures,gzip,hashlib,json,math,os,subprocess,sys,threading,time,urllib.request
from pathlib import Path
from urllib.error import HTTPError
P=argparse.ArgumentParser();P.add_argument('--root',type=Path,required=True);P.add_argument('--output',type=Path,required=True);P.add_argument('--seed-only',action='store_true');A=P.parse_args()
A.output.mkdir(parents=True,exist_ok=True)
BASE='http://127.0.0.1:18180'
def command(*args,stdin=None):
 p=subprocess.run(args,input=stdin,capture_output=True,text=True,encoding='utf-8',timeout=120)
 if p.returncode:raise RuntimeError(p.stderr)
 return p.stdout.strip()
def sql(q):return command('docker','exec','-i','phase18-postgres','psql','-U','postgres','-d','ticketing','-qAt','-v','ON_ERROR_STOP=1',stdin=q)
def save(name,value): (A.output/name).write_text(json.dumps(value,indent=2,ensure_ascii=False),encoding='utf-8')
def seed():
 for n in (5000,10000):
  v=f'p18-v-{n}';e=f'p18-e-{n}';s=f'p18-s-{n}'
  sql(f"""BEGIN;
INSERT INTO venues(id,name,city) VALUES('{v}','Phase18 {n}','Test');
INSERT INTO venue_zones(id,venue_id,code,name,sort_order) SELECT '{v}-z-'||i,'{v}','Z'||i,'Zone '||i,i FROM generate_series(0,4) i;
INSERT INTO seats(id,venue_id,zone_id,row_no,seat_no,seat_label)
SELECT '{s}-seat-'||lpad(i::text,5,'0'),'{v}','{v}-z-'||((i-1)/{n//5}),lpad(((i-1)/100)::text,3,'0'),(i-1)%100+1,'P'||lpad(i::text,5,'0') FROM generate_series(1,{n}) i;
INSERT INTO events(id,primary_venue_id,name,description,status,category,cover_url,date_range,sales_starts_at,sales_ends_at,published_at,published_by)
VALUES('{e}','{v}','Phase18 {n}','Fixed seed 18','ON_SALE','Concert','/images/concert-cover.png','2030.01.03','2026-01-01Z','2030-01-02Z','2026-01-01Z','U-ADMIN-DEMO');
INSERT INTO sessions(id,event_id,venue_id,hall_name,start_time,gate_time,status) VALUES('{s}','{e}','{v}','Hall','2030-01-03T12:00:00Z','2030-01-03T11:00:00Z','ON_SALE');
INSERT INTO session_zone_prices(session_id,zone_id,venue_id,price) SELECT '{s}',id,'{v}',10000 FROM venue_zones WHERE venue_id='{v}';
INSERT INTO session_seats(id,session_id,seat_id,venue_id,status,price) SELECT '{s}-ss-'||lpad(i::text,5,'0'),'{s}','{s}-seat-'||lpad(i::text,5,'0'),'{v}','AVAILABLE',10000 FROM generate_series(1,{n}) i;
COMMIT;""")
 sql("INSERT INTO app_users(id,display_name,username,password_hash,status,role) SELECT 'p18-user-'||i,'Stage0 user '||i,'p18-user-'||i,password_hash,'ACTIVE','CUSTOMER' FROM app_users CROSS JOIN generate_series(0,7) i WHERE username='demo';")
 records=[]
 for n in (5000,10000):
  raw=sql(f"SELECT s.id,s.zone_id,s.row_no,s.seat_no,s.seat_label,i.id,i.price FROM seats s JOIN session_seats i ON i.seat_id=s.id WHERE i.session_id='p18-s-{n}' ORDER BY s.id;")
  records.append(dict(seats=n,zones=5,sha256=hashlib.sha256(raw.encode()).hexdigest()))
 save('data-fingerprint.json',dict(seed=18,fixtures=records))
def pg():return json.loads(sql("SELECT coalesce(json_agg(x),'[]') FROM (SELECT queryid::text,query,calls,rows,total_exec_time FROM pg_stat_statements WHERE query NOT ILIKE '%pg_stat_statements%') x;"))
def redis():return command('docker','exec','phase18-redis','redis-cli','INFO','commandstats')
def resources():return command('docker','stats','--no-stream','--format','{{json .}}','phase18-api','phase18-postgres','phase18-redis')
def req(path,headers=None):
 t=time.perf_counter()
 try:r=urllib.request.urlopen(urllib.request.Request(BASE+path,headers=headers or {}),timeout=10)
 except HTTPError as error:r=error
 with r:body=r.read();h=dict(r.headers);status=r.status
 return dict(ms=(time.perf_counter()-t)*1000,status=status,bytes=len(body),gzipBytes=len(gzip.compress(body,mtime=0)),sha256=hashlib.sha256(body).hexdigest(),headers={k:v for k,v in h.items() if k.lower() in ('etag','cache-control','content-encoding','vary')}),body
def layout():
 records=[]
 for n in (5000,10000):
  path=f'/sessions/p18-s-{n}/seat-layout';before=pg();first,body=req(path)
  assert first['status']==200 and len(json.loads(body)['seats'])==n
  etag=next((v for k,v in first['headers'].items() if k.lower()=='etag'),'W/"phase18-baseline-no-tag"')
  rows=[dict(kind='first',**first)]
  for kind,headers in [('ordinary',{}),('conditional',{'If-None-Match':etag})]:
   for _ in range(20):r,_=req(path,headers);rows.append(dict(kind=kind,**r))
  records.append(dict(seats=n,pgBefore=before,pgAfter=pg(),samples=rows))
 save('layout.json',records)
def burst():
 os.environ['TICKETING_BASE_URL']=BASE;os.environ['TICKETING_TEST_ORIGIN']='http://127.0.0.1:18181'
 sys.path.insert(0,str(A.root/'backend/tests'))
 from auth_test_support import AuthenticatedClient
 clients=[AuthenticatedClient(f'p18-user-{i}') for i in range(8)]
 for c in clients:c.login()
 barrier=threading.Barrier(8);lock=threading.Lock();current=0;maximum=0
 def work(i):
  nonlocal current,maximum
  barrier.wait(timeout=15)
  with lock:current+=1;maximum=max(maximum,current)
  t=time.perf_counter()
  try:
   status,body,_=clients[i].request('/reservations',method='POST',body={'sessionId':'p18-s-5000','seatIds':['p18-s-5000-ss-00001']},headers={'Idempotency-Key':f'p18-burst-{i}'},timeout=15)
   return dict(status=status,code=body.get('code'),ms=(time.perf_counter()-t)*1000)
  finally:
   with lock:current-=1
 before=pg();rb=redis();samples=[];stop=threading.Event()
 def sample():
  while not stop.is_set():
   samples.append(dict(at=time.time(),resources=resources(),pg=sql("SELECT state,wait_event_type,wait_event,count(*) FROM pg_stat_activity WHERE datname='ticketing' GROUP BY 1,2,3;")));stop.wait(.2)
 thread=threading.Thread(target=sample);thread.start()
 try:
  with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(work,range(8)))
 finally:stop.set();thread.join()
 save('burst.json',dict(offered=8,trials=1,clientMaxInflight=maximum,results=results,pgBefore=before,pgAfter=pg(),redisBefore=rb,redisAfter=redis(),samples=samples))
def verify():
 sys.path.insert(0,str(A.root/'performance/verification'));sys.path.insert(0,str(A.root/'backend/tests'))
 from phase17_verify import QUERIES
 checks={k:int(sql(q)) for k,q in QUERIES.items()}
 for row in sql((A.root/'performance/verification/verify.sql').read_text(encoding='utf-8')).splitlines():
  k,v=row.rsplit('|',1);checks[k]=int(v)
 save('verifier.json',checks);assert not any(checks.values()),checks
if A.seed_only:seed()
else:
 layout();burst();verify()
