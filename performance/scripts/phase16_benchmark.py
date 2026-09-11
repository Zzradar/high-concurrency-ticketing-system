from pathlib import Path
import gzip
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from urllib.parse import urlencode
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend/tests'))
from phase16_system_test import docker,redis,sql,request,until,SESSION,PREFIX,BASE,OUTPUT
from phase16_read_model_test import ReadModelTest

def metrics():return urllib.request.urlopen(BASE+'/metrics').read().decode()
def pg():return json.loads(sql("SELECT COALESCE(json_agg(row_to_json(s)),'[]') FROM (SELECT query,calls,mean_exec_time,total_exec_time FROM pg_stat_statements WHERE query NOT ILIKE '%pg_stat_statements%') s;"))
def hold(ids,release=False):
    os.environ['PHASE16_REDIS_CONTAINER']='phase16-api-redis'
    test=ReadModelTest();test.session=SESSION;test.prefix=PREFIX
    for offset in range(0,len(ids),6):
        if release:test.hold('Release',ids[offset:offset+6],'phase16-controlled')
        else:test.hold('Ensure',ids[offset:offset+6],'phase16-controlled',1,300)

def snapshot_resources():
    raw=docker('stats','--no-stream','--format','{{json .}}','phase16-api-backend','phase16-api-postgres','phase16-api-redis')
    return {'at':time.time(),'containers':[json.loads(line) for line in raw.splitlines()]}

def probe(mode,snap):
    params={} if mode=='legacy' else {'zone':'Zone 0'}
    if mode in ['delta','controlled']:params.update(generation=snap['generation'],since=snap['cursor'])
    url=BASE+'/sessions/'+SESSION+'/seat-availability'+('?' + urlencode(params) if params else '')
    raw=urllib.request.urlopen(url).read()
    req=urllib.request.Request(url,headers={'Accept-Encoding':'gzip'})
    with urllib.request.urlopen(req) as r: compressed=r.read();encoding=r.headers.get('Content-Encoding')
    body=json.loads(raw)
    return {'rawBytes':len(raw),'gzipBytes':len(compressed),'contentEncoding':encoding,'changedSeats':len(body.get('changes',[]))}

def main():
    evidence={'machine':docker('info','--format','{{json .}}') if False else {'dockerCpus':docker('info','--format','{{.NCPU}}'),'dockerMemoryBytes':docker('info','--format','{{.MemTotal}}'),'otherRunningContainers':docker('ps','--format','{{.Names}}').splitlines()},'rows':[]}
    assert len(json.load(urllib.request.urlopen(BASE+'/sessions/'+SESSION+'/seat-layout'))['seats'])==5000
    ids=['perf-ss-phase16-'+str(i).zfill(5) for i in range(1,51)]
    hold(ids,True)
    for mode in ['legacy','snapshot','delta','controlled']:
        snap=request()
        if mode=='controlled':hold(ids[:1])
        for _ in range(30):probe(mode,snap)
        record={'mode':mode,'rate':200,'durationSeconds':20,'body':probe(mode,snap),'pgBefore':pg(),'redisBefore':redis('INFO','all')}
        (OUTPUT/(mode+'-metrics-before.txt')).write_text(metrics(),encoding='utf-8')
        samples=[];stop=threading.Event()
        def sample():
            while not stop.is_set():
                samples.append(snapshot_resources());stop.wait(1)
        sampler=threading.Thread(target=sample);sampler.start()
        args=['docker','run','--rm','--network','phase16-test','--mount','type=bind,source='+str(OUTPUT)+',target=/evidence',
          '-e','MODE='+mode,'-e','RATE=200','-e','DURATION=20s','-e','RESULT=/evidence/'+mode+'-k6.json',
          '-e','GENERATION='+snap['generation'],'-e','CURSOR='+snap['cursor'],'-e','CHANGES='+('1' if mode=='controlled' else '0'),
          'grafana/k6:2.2.0','run','/evidence/availability.js']
        try:r=subprocess.run(args,capture_output=True,text=True,encoding='utf-8')
        finally:stop.set();sampler.join()
        (OUTPUT/(mode+'-k6.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
        record.update(exitCode=r.returncode,resourceSamples=samples,pgAfter=pg(),redisAfter=redis('INFO','all'))
        (OUTPUT/(mode+'-metrics-after.txt')).write_text(metrics(),encoding='utf-8')
        record['streamLength']=redis('XLEN',PREFIX+':zone:Zone 0:changes')
        record['streamMemoryBytes']=redis('MEMORY','USAGE',PREFIX+':zone:Zone 0:changes')
        evidence['rows'].append(record)
        (OUTPUT/'warm-evidence.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
        hold(ids,True)
        print(('PASS' if r.returncode==0 else 'UNSTABLE')+' warm '+mode+' 200 req/s',flush=True)
        if mode=='delta':assert r.returncode==0,(mode,r.stdout[-1500:],r.stderr)
    controlled=[]
    for count in [1,10,50]:
        snap=request();hold(ids[:count]);body=probe('controlled',snap)
        assert body['changedSeats']==count
        controlled.append({'changed':count,**body});hold(ids[:count],True)
    evidence['controlledBodySizes']=controlled
    evidence['finalOutbox']=int(sql('SELECT count(*) FROM seat_availability_outbox;'))
    evidence['finalActiveLeases']=int(sql('SELECT count(*) FROM seat_availability_outbox WHERE lease_until>CURRENT_TIMESTAMP;'))
    (OUTPUT/'warm-evidence.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    print('PASS controlled 1/10/50 body size evidence',flush=True)
if __name__=='__main__':main()
