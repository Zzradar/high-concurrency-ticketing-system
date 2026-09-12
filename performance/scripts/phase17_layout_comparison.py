"""Same 5000-seat legacy fixture, pre-Phase17 image versus current image; sequential HTTP samples."""
import json,sys,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend/tests'))
from phase17_http_test import sql,command
from phase17_scale import sample
PG=['docker','exec','-i','phase17-postgres','psql','-U','postgres','-qAt','-v','ON_ERROR_STOP=1']
def oldsql(q):return command(PG+['-d','phase17_baseline'],q)
def literal(v):return 'NULL' if v is None else "'"+str(v).replace("'","''")+"'"
sid='perf-session-phase16'
assert sql("SELECT count(*) FROM pg_database WHERE datname='phase17_baseline';")=='0','Refuse existing baseline DB'
sql('CREATE DATABASE phase17_baseline;')
oldsql(''.join(p.read_text(encoding='utf-8') for p in sorted((ROOT/'backend/db/migrations').glob('*.sql')) if p.name<'012'))
session=json.loads(sql(f"SELECT row_to_json(s) FROM sessions s WHERE id='{sid}';"));vid=session['venue_id'];eid=session['event_id']
primary=sql(f"SELECT primary_venue_id FROM events WHERE id='{eid}';")
for table,condition in [('venues',f"id IN ('{vid}','{primary}')"),('events',f"id='{eid}'"),('sessions',f"id='{sid}'"),('seats',f"venue_id='{vid}'"),('session_seats',f"session_id='{sid}'")]:
 cols=oldsql(f"SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name='{table}' ORDER BY ordinal_position;").splitlines()
 select=','.join('z.name AS zone' if c=='zone' else 't.'+c for c in cols)
 join=' JOIN venue_zones z ON z.id=t.zone_id' if table=='seats' else ''
 rows=json.loads(sql(f"SELECT json_agg(x) FROM (SELECT {select} FROM {table} t{join} WHERE t.{condition}) x;"))
 oldsql(f"INSERT INTO {table}({','.join(cols)}) VALUES "+','.join('('+','.join(literal(row[c]) for c in cols)+')' for row in rows)+';')
p=ROOT/'backend/build/phase17/baseline-config.json';config=json.loads((p.parent/'config.json').read_text());config['db_clients'][0]['dbname']='phase17_baseline';p.write_text(json.dumps(config),encoding='utf-8')
command(['docker','run','-d','--name','phase17-layout-baseline','--network','phase17-batch1','-p','127.0.0.1:18120:8080','--mount','type=bind,source='+str(p)+',target=/tmp/config.json,readonly','--entrypoint','./ticketing_backend','phase15-current:local','/tmp/config.json'])
import time,urllib.request
for _ in range(50):
 try:
  if urllib.request.urlopen('http://127.0.0.1:18120/health').status==200:break
 except Exception:time.sleep(.2)
import phase17_scale
current,_=sample('/sessions/'+sid+'/seat-layout')
# Reuse exact sampling code and only redirect the explicit base URL.
original=phase17_scale.urllib.request.urlopen
phase17_scale.urllib.request.urlopen=lambda url,**kw:original(url.replace(':18117',':18120'),**kw)
old,_=sample('/sessions/'+sid+'/seat-layout')
result={'baselineImage':command(['docker','image','inspect','phase15-current:local','--format','{{.Id}}']),'baselineDescription':'Existing pre-Phase17 Phase15 image including Phase16; not a newly rebuilt fixed-baseline binary','sameFixture':sid,'seatCount':5000,'baseline':old,'current':current}
(ROOT/'performance/experiments/phase17-admin-publishing/layout-comparison.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
command(['docker','stop','phase17-layout-baseline'])
