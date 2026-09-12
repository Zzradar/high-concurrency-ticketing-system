"""Read preserved Phase14 raw points; do not average shard percentiles."""
import gzip,json,re,shutil
from pathlib import Path
from datetime import datetime
from phase14_evidence import percentile, timestamp
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'performance/experiments/phase15-sales-window'
def summarize():
    rows=[]
    for variant in ['baseline','current']:
        for case in ['g0','u1','u2']:
            source=ROOT/'performance/results'/('phase15-'+variant+'-'+case)
            target=OUT/'comparison'/variant/case;target.mkdir(parents=True,exist_ok=True)
            for name in ['global-summary.json','correctness.json','smoke-check.json','postgres-light-summary.json','gate-query-ids.json','manifest.json','resource-preflight.json','warnings.json']:
                shutil.copyfile(source/name,target/name)
            (target/'postgres-delta.json.gz').write_bytes(gzip.compress((source/'postgres-delta.json').read_bytes(),mtime=0))
            for name in ['host-and-container.jsonl','postgres.jsonl','redis.jsonl']:
                (target/(name+'.gz')).write_bytes(gzip.compress((source/'samples'/name).read_bytes(),mtime=0))
            (target/'postgres-light.jsonl.gz').write_bytes(gzip.compress((source/'postgres-light.jsonl').read_bytes(),mtime=0))
            # Keep compressed raw HTTP samples for reproducible percentiles, no credentials.
            raw=source/'shards/0/raw.json.gz';shutil.copyfile(raw,target/'main-raw.json.gz')
            values=[];times=[]
            with gzip.open(raw,'rt',encoding='utf-8') as handle:
                for line in handle:
                    point=json.loads(line)
                    if point.get('type')=='Point' and point.get('metric')=='http_req_duration':
                        values.append(point['data']['value']);times.append(timestamp(point['data']['time']))
            samples=[json.loads(x) for x in (source/'samples/host-and-container.jsonl').read_text(encoding='utf-8').splitlines()]
            cpu=[];memory=[]
            for sample in samples:
                for stat in sample['dockerStats']:
                    if stat['Name'].endswith('-backend-1'):
                        cpu.append(float(stat['CPUPerc'].rstrip('%')))
                        number,unit=re.match(r'([0-9.]+)([A-Za-z]+)',stat['MemUsage']).groups()
                        memory.append(float(number)*{'B':1/1048576,'kB':1/1024,'KiB':1/1024,'MB':1,'MiB':1,'GB':1024,'GiB':1024}[unit])
            ids=json.loads((source/'gate-query-ids.json').read_text(encoding='utf-8'))
            pg=json.loads((source/'postgres-delta.json').read_text(encoding='utf-8'))
            gates=[x['delta'] for x in pg['statements'] if x['identity']['queryid'] in ids]
            calls=sum(x['calls'] for x in gates);ms=sum(x['total_exec_time'] for x in gates)
            row={'variant':variant,'case':case.upper(),'httpRequests':len(values),'observedRequestSpanSeconds':max(times)-min(times),
              'httpRequestsPerSecond':len(values)/(max(times)-min(times)),'p50Ms':percentile(values,.5),'p95Ms':percentile(values,.95),'p99Ms':percentile(values,.99),
              'backendCpuPeakPercent':max(cpu),'backendMemoryPeakMiB':max(memory),'pgLockWaitPeak':max(x['pgLockWaits'] for x in samples),
              'pgTransactionWaiterPeak':max(x['transactionWaiters'] for x in samples),'computeQueuePeak':max(x['seatQueue'] for x in samples),
              'pgDeadlocks':pg['database']['deadlocks'],'gateCalls':calls,'gateTotalExecutionMs':ms,'gateMeanExecutionMs':ms/calls if calls else None}
            rows.append(row)
    result={'scope':'Unchanged Phase14 smoke model, 20 active users, 100 seats/session. Main shard HTTP points only. Request rate uses first-to-last response span. Container peaks include warmup/load/recovery; CPU 100%=one core. Shared Docker host; not a production SLA.',
      'baseline':'d1d1fd7170553df86c73cfa2313f09d57fa718a6','pool':{'postgres':4,'redisSeatHolds':2,'computeWorkers':4,'computeQueue':16},'rows':rows}
    (OUT/'comparison.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
if __name__=='__main__':summarize()
