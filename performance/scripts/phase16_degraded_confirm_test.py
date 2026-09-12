"""Read-model outage must not take authority away from PostgreSQL Confirm."""
import json,uuid,os
from phase16_system_test import OUTPUT,sql,docker,request,until,SESSION
from phase16_read_model_test import ReadModelTest
from auth_test_support import AuthenticatedClient,test_user_values,username_for_user
user='P16-degraded-'+uuid.uuid4().hex[:10]
sql('INSERT INTO app_users(id,display_name,username,password_hash,status) VALUES '+test_user_values([user])+';')
client=AuthenticatedClient(username_for_user(user));client.login()
seat='perf-ss-phase16-00030'
status,checkout,_=client.request('/checkout-sessions',method='POST',body={'sessionId':SESSION,'seatIds':[seat]})
assert status==201,(status,checkout)
old=request();docker('stop','phase16-api-redis')
try:
    degraded=request(generation=old['generation'],since=old['cursor'])
    assert degraded['degraded'] and degraded['cursor'] is None
    status,result,_=client.request('/checkout-sessions/'+checkout['id']+'/confirm',method='POST')
    assert status==200,(status,result)
    assert sql("SELECT status FROM session_seats WHERE id='"+seat+"';")=='HELD'
    assert int(sql("SELECT count(*) FROM seat_availability_outbox WHERE session_seat_id='"+seat+"';"))>0
    evidence={'passed':True,'degradedSnapshot':True,'confirmHttpStatus':status,'formalStatus':'HELD','outboxPreserved':True}
finally:docker('start','phase16-api-redis')
until(lambda:request()['degraded'] is False)
until(lambda:sql('SELECT count(*) FROM seat_availability_outbox;')=='0')
assert {'id':seat,'status':'HELD'} in request()['seats']
order=sql("SELECT o.id FROM orders o JOIN checkout_sessions c ON c.reservation_id=o.reservation_id WHERE c.id='"+checkout['id']+"';")
status,body,_=client.request('/orders/'+order+'/cancel',method='POST');assert status==200,(status,body)
until(lambda:sql('SELECT count(*) FROM seat_availability_outbox;')=='0')
assert sql("SELECT status FROM session_seats WHERE id='"+seat+"';")=='AVAILABLE'
# Finalization ran while Redis was down: its original temporary Hold can survive until TTL.
os.environ['PHASE16_REDIS_CONTAINER']='phase16-api-redis'
from phase16_system_test import PREFIX
test=ReadModelTest();test.session=SESSION;test.prefix=PREFIX
test.hold('Release',[seat],checkout['id'])
assert {'id':seat,'status':'AVAILABLE'} in request()['seats']
evidence['recoveredAndReleased']=True
(OUTPUT/'degraded-confirm.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
print('PASS Redis outage, degraded Snapshot, real Confirm and recovery',flush=True)
