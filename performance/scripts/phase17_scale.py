"""Sequential data-size characterization. Not a load/capacity/SLA benchmark."""
from pathlib import Path
import gzip,json,math,sys,time,urllib.request
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend/tests'))
from phase17_http_test import AuthenticatedClient,sql,command,REDIS
from phase17_publishing_test import instant
OUT=ROOT/'performance/experiments/phase17-admin-publishing'
def rjson(*args):return json.loads(command(['docker','exec',REDIS,'redis-cli','--json',*map(str,args)]))
def stats():
    return json.loads(sql("SELECT coalesce(json_agg(x),'[]') FROM (SELECT queryid::text id,query,calls,total_exec_time ms FROM pg_stat_statements WHERE query NOT LIKE '%pg_stat_statements%') x;"))
def difference(before,after):
    old={x['id']:x for x in before}
    return [dict(query=x['query'],calls=x['calls']-old.get(x['id'],{}).get('calls',0),ms=x['ms']-old.get(x['id'],{}).get('ms',0)) for x in after if x['calls']>old.get(x['id'],{}).get('calls',0)]
def timed(fn):
    start=time.perf_counter();value=fn();return value,round((time.perf_counter()-start)*1000,3)
def sample(path,n=20):
    times=[];raw=b''
    for _ in range(n):
        raw,ms=timed(lambda:urllib.request.urlopen('http://127.0.0.1:18117'+path,timeout=30).read());times.append(ms)
    return {'n':n,'p50Ms':sorted(times)[math.ceil(n*.5)-1],'p95Ms':sorted(times)[math.ceil(n*.95)-1],'jsonBytes':len(raw),'gzipBytes':len(gzip.compress(raw,mtime=0)),'samplesMs':times},json.loads(raw)
def main():
    a=AuthenticatedClient('admin');a.login()
    def api(path,body):
        status,value,_=a.request(path,method='POST',body=body,timeout=60);assert status in (200,201),(status,value);return value
    records=[]
    for size in [5000,10000]:
        plan={'name':f'Phase17 scale {size}','city':'Chengdu','zones':[{'code':f'Z{i}','name':f'Zone {i}','rows':[{'label':chr(65+j),'seatCount':100} for j in range(size//500)]} for i in range(5)]}
        before=stats();v,venueMs=timed(lambda:api('/admin/venues',plan));venueSql=difference(before,stats());assert v['totalSeats']==size
        e=api('/admin/events',{'name':f'Phase17 scale {size}','description':'Sequential characterization','category':'Concert','coverUrl':'/images/concert-cover.png','venueId':v['id'],'salesStartsAt':instant(-1),'salesEndsAt':instant(72)})
        path='/admin/events/'+e['id'];e=api(path+'/sessions',{'hallName':'Hall','startTime':instant(48),'gateTime':instant(47)});sid=e['savedSessionId']
        status,_,_=a.request(path+'/sessions/'+sid+'/prices',method='PUT',body={'prices':[{'zoneId':z['id'],'price':10000} for z in v['zones']]});assert status==200
        before=stats();result,publishMs=timed(lambda:api(path+'/publish',None));publishSql=difference(before,stats());assert result['inventory']['sessionSeatCount']==size
        assert sql(f"SELECT count(*) FROM session_seats WHERE session_id='{sid}';")==str(size)
        base='/sessions/'+sid;layout,_=sample(base+'/seat-layout')
        rjson('CONFIG','SET','slowlog-log-slower-than','0');rjson('SLOWLOG','RESET')
        try:
            before=stats();cold,snapshot=sample(base+'/seat-availability?zone=Zone%200',1);coldSql=difference(before,stats());slow=rjson('SLOWLOG','GET','128')
        finally:rjson('CONFIG','SET','slowlog-log-slower-than','10000')
        assert snapshot['mode']=='snapshot',snapshot
        hot,_=sample(base+'/seat-availability?zone=Zone%200')
        before=stats();delta,body=sample(base+'/seat-availability?zone=Zone%200&generation='+snapshot['generation']+'&since='+str(snapshot['cursor']));deltaSql=difference(before,stats())
        assert body['mode']=='delta' and not body['changes'],body
        record={'seatCount':size,'zoneCount':5,'sessionCount':1,'eventId':e['id'],'sessionId':sid,'venueId':v['id'],'venueMs':venueMs,'venueSql':venueSql,'publishMs':publishMs,'publishSql':publishSql,'actualInventory':size,'layout':layout,'coldInitHttp':cold,'coldSql':coldSql,'redisEvalMicroseconds':[x[2] for x in slow if x[3][0].lower() in ('eval','evalsha')],'snapshot':hot,'delta':delta,'deltaSql':deltaSql}
        records.append(record);OUT.mkdir(parents=True,exist_ok=True);(OUT/'scale.json').write_text(json.dumps(records,indent=2),encoding='utf-8');print(json.dumps({k:v for k,v in record.items() if k in ['seatCount','venueMs','publishMs','actualInventory']}),flush=True)
if __name__=='__main__':main()
