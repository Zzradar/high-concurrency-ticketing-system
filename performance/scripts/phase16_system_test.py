"""Destructive fault gates are restricted to this task's named Phase16 containers."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlencode

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend/tests'))
from phase16_api_test import sql
SESSION='perf-session-phase16'
PREFIX='ticketing:seat-availability:{'+SESSION+'}'
BASE=os.environ.get('PHASE16_BASE_URL','http://127.0.0.1:18096')
OUTPUT=Path(os.environ.get('PHASE16_OUTPUT',str(ROOT/'performance/experiments/phase16-availability')))

def docker(*args):
    r=subprocess.run(['docker',*args],capture_output=True,text=True,encoding='utf-8')
    if r.returncode:raise RuntimeError(r.stderr)
    return r.stdout.strip()

def redis(*args):
    raw=docker('exec',os.environ.get('PHASE16_REDIS_CONTAINER','phase16-api-redis'),'redis-cli','--json',*[str(x) for x in args])
    return raw if args[0]=='INFO' else json.loads(raw)

def request(base=BASE,**params):
    return json.load(urllib.request.urlopen(base+'/sessions/'+SESSION+'/seat-availability?'+urlencode({'zone':'Zone 0',**params}),timeout=10))

def until(predicate, seconds=12):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        try:
            value=predicate()
            if value:return value
        except Exception:pass
        time.sleep(.1)
    raise AssertionError('deadline exceeded')

def healthy(base=BASE):
    return until(lambda:urllib.request.urlopen(base+'/health',timeout=1).status==200)

def fault_backend(name,flag):
    existing=docker('ps','-a','--filter','name=^/'+name+'$','--format','{{.ID}}')
    if existing:
        details=json.loads(docker('inspect',name))[0]
        assert flag+'=1' in details['Config']['Env']
        assert any(Path(m['Source']).name=='phase16' for m in details['Mounts'])
        assert not details['State']['Running']
        docker('start',name)
        return
    docker('run','-d','--name',name,'--network','phase16-test','-p','127.0.0.1:18097:8080',
       '-e',flag+'=1','--mount','type=bind,source='+str(ROOT/'backend/build/phase16')+',target=/phase16,readonly',
       '--workdir','/tmp','--entrypoint','/phase16/ticketing_backend','phase14-engineering-build:20260910-v3','/phase16/fault-config.json')

def main():
    evidence={}
    healthy()
    # Cold model, concurrent HTTP, one PG initializer. Exact namespace only.
    redis('DEL',PREFIX+':meta')
    query="SELECT COALESCE(sum(calls),0) FROM pg_stat_statements WHERE query ILIKE '%inventory.formal_version%' AND query ILIKE '%ORDER BY seat.row_no%';"
    before=int(sql(query));cpu=redis('INFO','cpu');stats=redis('INFO','commandstats')
    start=time.perf_counter()
    with ThreadPoolExecutor(max_workers=24) as pool:
        responses=list(pool.map(lambda _:request(),range(48)))
    elapsed=time.perf_counter()-start
    assert all(not r['degraded'] and len(r['seats'])==1000 for r in responses)
    assert len({r['generation'] for r in responses})==1
    assert int(sql(query))-before==1
    evidence['cold']={'requests':48,'concurrency':24,'elapsedSeconds':elapsed,'fullPgQueries':int(sql(query))-before,
      'redisCpuBefore':cpu,'redisCpuAfter':redis('INFO','cpu'),'redisCommandsBefore':stats,'redisCommandsAfter':redis('INFO','commandstats')}
    evidence['cold']['pgStatements']=json.loads(sql("SELECT COALESCE(json_agg(row_to_json(s)),'[]') FROM (SELECT calls,mean_exec_time,total_exec_time FROM pg_stat_statements WHERE query ILIKE '%inventory.formal_version%' AND query ILIKE '%ORDER BY seat.row_no%') s;"))
    print('PASS cold 5000 singleflight',flush=True)
    # Terminate precisely after Redis apply but before database acknowledgement.
    seat='perf-ss-phase16-00001';old=request();docker('stop','phase16-api-backend')
    before_len=redis('XLEN',PREFIX+':zone:Zone 0:changes')
    sql("UPDATE session_seats SET status='SOLD' WHERE id='"+seat+"';")
    fault_backend('phase16-fault-projector','PHASE16_FAULT_AFTER_REDIS_APPLY')
    until(lambda:docker('inspect','phase16-fault-projector','--format','{{.State.Running}}')=='false')
    assert docker('inspect','phase16-fault-projector','--format','{{.State.ExitCode}}')=='86'
    assert int(sql('SELECT count(*) FROM seat_availability_outbox;'))>0
    assert redis('XLEN',PREFIX+':zone:Zone 0:changes')==before_len+1
    docker('start','phase16-api-backend');healthy()
    until(lambda:sql('SELECT count(*) FROM seat_availability_outbox;')=='0')
    assert redis('XLEN',PREFIX+':zone:Zone 0:changes')==before_len+1
    delta=request(generation=old['generation'],since=old['cursor'])
    assert {'id':seat,'status':'SOLD'} in delta['changes']
    sql("UPDATE session_seats SET status='AVAILABLE' WHERE id='"+seat+"';")
    until(lambda:sql('SELECT count(*) FROM seat_availability_outbox;')=='0')
    evidence['projectorCrash']={'exitCode':86,'outboxDrained':True,'duplicateBusinessChanges':0}
    print('PASS projector crash/replay',flush=True)
    # Kill initializer after PG snapshot, leaving an expiring lease; restart builds a new generation.
    old=request();docker('stop','phase16-api-backend');redis('DEL',PREFIX+':meta')
    fault_backend('phase16-fault-init','PHASE16_FAULT_AFTER_PG_SNAPSHOT');healthy('http://127.0.0.1:18097')
    try:request('http://127.0.0.1:18097')
    except Exception:pass
    until(lambda:docker('inspect','phase16-fault-init','--format','{{.State.Running}}')=='false')
    assert docker('inspect','phase16-fault-init','--format','{{.State.ExitCode}}')=='87'
    assert redis('EXISTS',PREFIX+':meta')==0
    time.sleep(2.1);docker('start','phase16-api-backend');healthy();rebuilt=request()
    assert rebuilt['generation']!=old['generation']
    evidence['initCrash']={'exitCode':87,'rebuilt':True,'generationChanged':True}
    print('PASS initializer crash/rebuild',flush=True)
    # Redis outage must keep the formal update in PostgreSQL/outbox.
    old=request();docker('stop','phase16-api-redis')
    try:
        sql("UPDATE session_seats SET status='SOLD' WHERE id='"+seat+"';")
        degraded=request(generation=old['generation'],since=old['cursor'])
        assert degraded['degraded'] and degraded['reset'] and degraded['generation'] is None
        assert {'id':seat,'status':'SOLD'} in degraded['seats']
        assert int(sql('SELECT count(*) FROM seat_availability_outbox;'))>0
    finally:docker('start','phase16-api-redis')
    until(lambda:request()['degraded'] is False)
    until(lambda:sql('SELECT count(*) FROM seat_availability_outbox;')=='0')
    sql("UPDATE session_seats SET status='AVAILABLE' WHERE id='"+seat+"';")
    until(lambda:sql('SELECT count(*) FROM seat_availability_outbox;')=='0')
    evidence['redisOutage']={'degradedFormalSnapshot':True,'eventPreserved':True,'recovered':True}
    print('PASS Redis unavailable/degraded/recovery',flush=True)
    old=request();redis('FLUSHDB')
    rebuilt=request(generation=old['generation'],since=old['cursor'])
    assert rebuilt['reset'] and rebuilt['mode']=='snapshot' and rebuilt['generation']!=old['generation']
    assert all(s['status']=='AVAILABLE' for s in rebuilt['seats'])
    evidence['redisFlush']={'generationReset':True,'pgSnapshotRecovered':True}
    sql("BEGIN;UPDATE session_seats SET status='SOLD' WHERE id='"+seat+"';ROLLBACK;")
    assert sql("SELECT status FROM session_seats WHERE id='"+seat+"';")=='AVAILABLE'
    assert sql('SELECT count(*) FROM seat_availability_outbox;')=='0'
    evidence['pgRollback']={'inventoryPreserved':True,'outboxRows':0}
    OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/'fault-and-cold.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    print('PASS Redis flush and PostgreSQL rollback; evidence saved',flush=True)

if __name__=='__main__':main()
