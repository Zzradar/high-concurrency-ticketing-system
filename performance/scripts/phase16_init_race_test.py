"""Real PG snapshot and Redis publication barrier with concurrent hold/outbox writes."""
import json,os,sys,time,uuid
from phase16_system_test import ROOT,OUTPUT,sql,redis,request,until,PREFIX,SESSION
sys.path.insert(0,str(ROOT/'backend/tests'))
from phase16_read_model_test import ReadModelTest
os.environ['PHASE16_REDIS_CONTAINER']='phase16-api-redis'
test=ReadModelTest();test.session=SESSION;test.prefix=PREFIX
ids=['perf-ss-phase16-'+str(i).zfill(5) for i in (21,22,23)]
token='barrier-'+uuid.uuid4().hex;generation='race-'+uuid.uuid4().hex
assert test.hold('Ensure',[ids[0]],'before-snapshot',1,300)==1
redis('DEL',PREFIX+':meta');redis('SET',PREFIX+':init-lock',token,'PX',15000)
rows=json.loads(sql("SELECT json_agg(x.row) FROM (SELECT json_build_array(i.id,i.status,i.formal_version::text,s.zone) AS row FROM session_seats i JOIN seats s ON s.id=i.seat_id WHERE i.session_id='"+SESSION+"' ORDER BY s.row_no,s.seat_no,i.id) x;"))
assert len(rows)==5000
try:
    assert test.hold('Ensure',[ids[1]],'after-snapshot',2,300)==1
    sql("UPDATE session_seats SET status='SOLD' WHERE id='"+ids[2]+"';")
    time.sleep(.7)
    assert int(sql("SELECT count(*) FROM seat_availability_outbox WHERE session_seat_id='"+ids[2]+"';"))==1
    assert test.init(token,generation,rows)==['READY',generation]
    assert redis('HGET',PREFIX+':holds',ids[0]).startswith('before-snapshot|1|')
    assert redis('HGET',PREFIX+':holds',ids[1]).startswith('after-snapshot|2|')
    until(lambda:sql('SELECT count(*) FROM seat_availability_outbox;')=='0')
    current=request();assert {'id':ids[2],'status':'SOLD'} in current['seats']
    assert redis('HGET',PREFIX+':formal',ids[2])=='SOLD|'+sql("SELECT formal_version FROM session_seats WHERE id='"+ids[2]+"';")
    result={'passed':True,'pgSnapshotSeats':len(rows),'preexistingHoldImported':True,'postSnapshotHoldImported':True,'initializingOutboxRetained':True,'postPublicationProjectionConverged':True}
    (OUTPUT/'init-race.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print('PASS real PG/Redis init barrier',flush=True)
finally:
    test.hold('Release',[ids[0]],'before-snapshot');test.hold('Release',[ids[1]],'after-snapshot')
    sql("UPDATE session_seats SET status='AVAILABLE' WHERE id='"+ids[2]+"';")
    redis('DEL',PREFIX+':init-lock')
    until(lambda:sql('SELECT count(*) FROM seat_availability_outbox;')=='0')
