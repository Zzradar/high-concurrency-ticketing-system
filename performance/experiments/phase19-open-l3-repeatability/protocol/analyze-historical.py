import json,gzip,os,sys,hashlib,collections,datetime
from pathlib import Path
ROOT=Path.cwd(); P=ROOT/'performance/experiments/phase19-global-polling-mixed-load/protocol';sys.path.insert(0,str(P))
from report_tables import capacity
base=Path(os.environ['TEMP'])/'phase19-avfix-capacity-points';out=Path(os.environ['TEMP'])/'phase19-l3-repeatability/analysis';out.mkdir(exist_ok=True); assert not any(out.iterdir())
def save(name,x):(out/name).write_bytes((json.dumps(x,indent=2)+'\n').encode())
def metrics(o):return {l.rsplit(' ',1)[0]:float(l.rsplit(' ',1)[1]) for l in o['backendMetrics'].splitlines() if l and not l.startswith('#')}
def selected(m):return {k:v for k,v in m.items() if ('traffic_' in k and 'AVAILABILITY' in k) or 'overload_rejections' in k or k in ['ticketing_seat_map_compute_active_workers','ticketing_seat_map_compute_queue_depth'] or ('availability_events_total' in k) or ('seat_map_compute' in k and any(z in k for z in ['_sum','_count','submissions_total'])) or 'event_loop_lag' in k}
summary={}
for name in ['open-l3','open-l3-r2']:
 point=base/name;obs=json.loads((point/'system-observations.json').read_text()); rows=[];errors=[]
 with gzip.open(point/'k6-points.jsonl.gz','rt') as f:
  for line in f:
   x=json.loads(line)
   if x.get('type')=='Point' and x['metric']=='http_req_duration':
    d=x['data'];rows.append(d)
    if d.get('tags',{}).get('status')=='503':errors.append(d)
 enriched=[]
 for e in errors:
  t=datetime.datetime.strptime(e['time'][:26], '%Y-%m-%dT%H:%M:%S.%f')
  near=[d for d in rows if abs((datetime.datetime.strptime(d['time'][:26].rstrip('Z'), '%Y-%m-%dT%H:%M:%S.%f')-t).total_seconds())<=.15]
  enriched.append({**e,'session':'phase19-session-001-002','sessionEvidence':'frozen workload readOnce uses cfg.writerSession in open mode','endpoint':'/sessions/phase19-session-001-002/seat-availability','zone':None,'zoneUnavailableReason':'frozen systemTags do not export URL, zone, VU id or user identity; scenario is insufficient to infer actual VU assignment', 'handling':'rejected at Availability Bulkhead before read model / fallback / compute','nearbyHttpCompletionsWithin150ms':near})
 save(name+'-503-timeline.json',enriched)
 save(name+'-metric-timeline.json',[{'utc':o['utc'],'metrics':selected(metrics(o)),'postgres':o['postgres'],'redis':o['redis']} for o in obs])
 s=capacity(point);s['metricStart']=selected(metrics(obs[0]));s['metricEnd']=selected(metrics(obs[-1]));s['errors503']=len(errors)
 s['observeHttpCount']=sum(v for k,v in json.loads((point/'aggregate.json').read_text())['counts'].items() if k.startswith('http_reqs|') and json.loads(k.split('|',1)[1]).get('phase')=='observe')
 s['observe503Rate']=len(errors)/s['observeHttpCount']
 s['limitations']=['HTTP timestamp is k6 completion timestamp, not server admission time.','Gauge samples are cached and cannot reconstruct precise rejection-time queue/worker state.','No per-request PostgreSQL or Redis timing, client-pool backlog, or cache-key trace.','No retained cpu.stat throttle counters; average CPU is not proof against short stalls.']
 summary[name]=s
save('historical-comparison.json',summary)
print('Historical comparison recorded, eight failures retained')