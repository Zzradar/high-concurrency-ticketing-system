"""Control only the explicitly named isolated Phase18 browser fixture; output no credentials."""
import os,sys,json,hashlib
import phase18_admission_http_test as fixture
from auth_test_support import AuthenticatedClient
command=sys.argv[1]
if command=='create':
 test=fixture.AdmissionHTTP();test.setUp();test.policy('PAUSED');print(json.dumps({'eventId':test.e,'sessionId':test.s}));sys.exit()
event=sys.argv[2]
assert event and '/' not in event and len(event)<128
admin=AuthenticatedClient('admin');path='/admin/events/'+event+'/admission-policy'
status,policy,_=admin.request(path);assert status==200
root='ticketing:admission:{evt:'+hashlib.sha256(event.encode()).hexdigest()+'}:'
if command=='mode':
 mode=sys.argv[3];assert mode in ['OFF','OBSERVE','PAUSED','ENFORCED']
 body={k:policy[k] for k in ['prequeueSeconds','maxActiveUsers','admissionRatePerSecond','leaseSeconds']};body.update(mode=mode,expectedPolicyVersion=policy['policyVersion'])
 status,policy,_=admin.request(path,method='PUT',body=body);assert status==200
elif command=='reset':
 old=policy['queueGeneration']
 fixture.redis('DEL',root+'runtime',*[root+old+':'+suffix for suffix in ['prequeue','waiting','presence','active','heartbeat','sequence','release','pause']])
 policy=fixture.until(lambda:(p if (p:=admin.request(path)[1])['queueGeneration']!=old else None))
elif command=='limit':
 clock=fixture.redis('TIME');now=int(clock[0])*1000+int(clock[1])//1000
 key=root+policy['queueGeneration']+':rate:ADMISSION_STATUS:event'
 fixture.redis('HSET',key,'tokens',0,'time',now+10000);fixture.redis('PEXPIRE',key,60000)
elif command=='counts':
 counts={s:fixture.redis('ZCARD',root+policy['queueGeneration']+':'+s) for s in ['prequeue','waiting','active']}
 print(json.dumps(counts));sys.exit()
else:raise ValueError('Unknown fixture operation')
print(json.dumps({'mode':policy['mode'],'generation':policy['queueGeneration'],'version':policy['policyVersion']}))
