"""Read-only inventory and Redis convergence verifier for the Phase16 fixture."""
from pathlib import Path
import json
import sys
import urllib.request
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'performance/scripts'))
from phase16_system_test import sql,redis,until,BASE,OUTPUT

def ashash(value):return value if isinstance(value,dict) else dict(zip(value[::2],value[1::2]))
def verify():
    until(lambda:sql('SELECT count(*) FROM seat_availability_outbox;')=='0')
    checks={}
    checks['negativeFormalVersions']=int(sql('SELECT count(*) FROM session_seats WHERE formal_version<0;'))
    checks['outboxDuplicates']=int(sql('SELECT count(*) FROM (SELECT session_seat_id,formal_version FROM seat_availability_outbox GROUP BY 1,2 HAVING count(*)>1) x;'))
    checks['outboxBacklog']=int(sql('SELECT count(*) FROM seat_availability_outbox;'))
    checks['activeLeases']=int(sql('SELECT count(*) FROM seat_availability_outbox WHERE lease_until>CURRENT_TIMESTAMP;'))
    inventory=json.loads(sql("SELECT json_agg(row_to_json(r)) FROM (SELECT i.id,i.session_id,i.status,i.formal_version,z.name AS zone FROM session_seats i JOIN seats s ON s.id=i.seat_id JOIN venue_zones z ON z.id=s.zone_id AND z.venue_id=s.venue_id ORDER BY i.session_id,i.id) r;"))
    sessions={r['session_id'] for r in inventory}
    checked=0
    for session in sorted(sessions):
        prefix='ticketing:seat-availability:{'+session+'}'
        if redis('HGET',prefix+':meta','ready')!='1':continue
        zones=redis('LRANGE',prefix+':zones',0,-1)
        if zones:
            urllib.request.urlopen(BASE+'/sessions/'+session+'/seat-availability?'+urlencode({'zone':zones[0]})).read()
        formal=ashash(redis('HGETALL',prefix+':formal'));mapping=ashash(redis('HGETALL',prefix+':seat-zone'));holds=ashash(redis('HGETALL',prefix+':holds'))
        rows=[r for r in inventory if r['session_id']==session]
        checks[session+':formalMismatch']=sum(formal.get(r['id'])!=r['status']+'|'+str(r['formal_version']) for r in rows)
        checks[session+':extraFormalSeats']=len(set(formal)-{r['id'] for r in rows})
        checks[session+':zoneMapMismatch']=sum(mapping.get(r['id'])!=r['zone'] for r in rows)
        for zone in zones:
            members={r['id'] for r in rows if r['zone']==zone}
            checks[session+':'+zone+':membership']=len(members.symmetric_difference(set(redis('SMEMBERS',prefix+':zone:'+zone+':seats'))))
            expected={'total':len(members),'available':0,'held':0,'sold':0}
            for row in (r for r in rows if r['zone']==zone):
                status=row['status']
                if status=='AVAILABLE' and row['id'] in holds:status='HELD'
                expected[status.lower()]+=1
            actual={k:int(v) for k,v in ashash(redis('HGETALL',prefix+':zone:'+zone+':summary')).items()}
            checks[session+':'+zone+':summary']=int(expected!=actual)
        for seat,value in holds.items():
            raw,expiry=value.rsplit('|',1)
            checks[session+':'+seat+':hold']=int(redis('GET','ticketing:seat-hold:{'+session+'}:'+seat)!=raw)
        checked+=len(rows)
    baseline=sql((ROOT/'performance/verification/verify.sql').read_text(encoding='utf-8'))
    for line in baseline.splitlines():
        name,count=line.rsplit('|',1);checks['existing:'+name]=int(count)
    result={'passed':not any(checks.values()),'checkedRedisSeats':checked,'checks':checks}
    OUTPUT.mkdir(parents=True,exist_ok=True)
    (OUTPUT/'verifier.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    return result
if __name__=='__main__':
    if not verify()['passed']:raise SystemExit(1)
