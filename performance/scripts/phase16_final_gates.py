"""Final real expiry/Phase14 reconciliation and isolated cold timing probe."""
import json
import sys
import time
from pathlib import Path
from phase16_system_test import ROOT,OUTPUT,sql,redis,request,until,PREFIX,SESSION
sys.path.insert(0,str(ROOT/'performance/verification'))
from phase16_verify import verify
from phase14_verify import verify_run
from auth_test_support import AuthenticatedClient,test_user_values,username_for_user

def main():
    # Allocate a fresh one-user slice; expected success comes from the real HTTP result.
    index=int(sql("SELECT COALESCE(max(substring(id from '[0-9]+$')::int),160100)+1 FROM app_users WHERE id ~ '^perf-user-160[1-9][0-9][0-9]$';"))
    assert 160101<=index<160900
    user='perf-user-'+str(index)
    sql('INSERT INTO app_users(id,display_name,username,password_hash,status) VALUES '+test_user_values([user])+';')
    client=AuthenticatedClient(username_for_user(user));client.login()
    seat='perf-ss-phase16-00020'
    status,body,_=client.request('/reservations',method='POST',body={'sessionId':SESSION,'seatIds':[seat]},headers={'Idempotency-Key':'phase16-expiry-'+str(index)})
    assert status==201,(status,body)
    order=body['order']['id'];reservation=body['reservation']['id']
    until(lambda:sql('SELECT count(*) FROM seat_availability_outbox;')=='0')
    held=request();assert {'id':seat,'status':'HELD'} in held['seats']
    sql("BEGIN;UPDATE reservations SET created_at=CURRENT_TIMESTAMP-INTERVAL '20 minutes',expires_at=CURRENT_TIMESTAMP-INTERVAL '1 second' WHERE id='"+reservation+"';UPDATE orders SET created_at=CURRENT_TIMESTAMP-INTERVAL '20 minutes',expires_at=CURRENT_TIMESTAMP-INTERVAL '1 second' WHERE id='"+order+"';COMMIT;")
    until(lambda:sql("SELECT status FROM orders WHERE id='"+order+"';")=='EXPIRED',seconds=15)
    until(lambda:sql('SELECT count(*) FROM seat_availability_outbox;')=='0')
    delta=request(generation=held['generation'],since=held['cursor'])
    assert {'id':seat,'status':'AVAILABLE'} in delta['changes']
    class Environment:
        root=OUTPUT
        sql=staticmethod(sql)
        invariants=staticmethod(verify)
    spec={'case':'S1','targets':{'slices':{'main':[index-1,index],'login':[161000,161001],'payment':[161100,161101]},'probes':{'paymentDeadlineSeconds':20}}}
    summary={'counts':[{'metric':'phase14_results','tags':['main','reservation','business_success'],'count':1}]}
    result=verify_run(Environment(),spec,summary)
    assert result['passed'],result
    result['expiry']={'orderStatus':'EXPIRED','observedFormalHeld':True,'observedDeltaAvailable':True,'reservationCreatedHttpStatus':status}
    (OUTPUT/'phase14-and-expiry.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('PASS actual order expiry and existing Phase14 verify_run',flush=True)
    query="SELECT COALESCE(sum(calls),0)||'|'||COALESCE(sum(total_exec_time),0) FROM pg_stat_statements WHERE query ILIKE '%inventory.formal_version%' AND query ILIKE '%ORDER BY seat.row_no%';"
    before=sql(query).split('|');redis('DEL',PREFIX+':meta')
    old=redis('CONFIG','GET','slowlog-log-slower-than')
    threshold=old['slowlog-log-slower-than'] if isinstance(old,dict) else old[1]
    redis('CONFIG','SET','slowlog-log-slower-than',1000)
    try:
        start=time.perf_counter();snap=request();elapsed=time.perf_counter()-start
        entries=redis('SLOWLOG','GET',128)
    finally:redis('CONFIG','SET','slowlog-log-slower-than',threshold)
    after=sql(query).split('|')
    # Do not persist Redis command payloads, only durations for this generation.
    matching=[entry[2] for entry in entries if len(entry[3])>5 and str(entry[3][0]).upper()=='EVAL' and snap['generation'] in entry[3]]
    assert len(matching)==1,matching
    evidence={'httpMilliseconds':elapsed*1000,'pgFullQueries':int(after[0])-int(before[0]),'pgExecutionMilliseconds':float(after[1])-float(before[1]),'initLuaMicroseconds':matching[0],'seats':5000,'returnedZoneSeats':len(snap['seats'])}
    assert evidence['pgFullQueries']==1
    (OUTPUT/'cold-timing.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    print('PASS cold timing '+json.dumps(evidence),flush=True)
if __name__=='__main__':main()
