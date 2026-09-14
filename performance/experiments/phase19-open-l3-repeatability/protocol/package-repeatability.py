from pathlib import Path
import os,sys,json,hashlib,subprocess
root=Path.cwd();tmp=Path(os.environ['TEMP']);base=tmp/'phase19-l3-repeatability';out=root/'performance/experiments/phase19-open-l3-repeatability'
sys.path[:0]=[str(root/'performance/scripts'),str(root/'performance/experiments/phase19-global-polling-mixed-load/protocol')]
from phase19_archive_candidate import redact
from phase19_archive_formal import package
from phase19_l3_repeatability import qualify
from report_tables import capacity,count
sha=lambda b:hashlib.sha256(b).hexdigest()
def save(p,x):
 assert not p.exists(),p
 p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((json.dumps(x,indent=2)+'\n').encode())
def copy(p,q):
 assert not q.exists(),q
 q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(redact(p.read_text(encoding='utf8').replace('\r\n','\n')).encode())
assert 'THREE INDEPENDENT SEQUENCES COMPLETE' in (tmp/'phase19-l3-repeatability-run.log').read_text(encoding='utf8')
rounds=[];full={}
for n in range(1,4):
 runtime=base/f'r{n}-runtime';points=base/f'r{n}-points'
 fixture=json.loads((runtime/'fixture-manifest.json').read_text());inv=json.loads((points/'initial-inventory.json').read_text());config=json.loads((runtime/'api-config.json').read_text());stack=json.loads((runtime/'stack.json').read_text())
 config['custom_config']['authentication']['allowed_origins']=[x if x!='http://127.0.0.1:'+str(stack['frontendPort']) else '<ROUND_FRONTEND_ORIGIN>' for x in config['custom_config']['authentication']['allowed_origins']]
 initial={'fixture':fixture,'formalVersionSum':inv['formalVersionSum'],'projectedFormalVersionSum':inv['projectedFormalVersionSum'],'readyGenerations':{k:bool(v) for k,v in inv['generations'].items()},'streams':{k:{'length':v['length'],'entries-added':v['entries-added']} for k,v in inv['streams'].items()},'normalizedConfigSha256':sha(json.dumps(config,sort_keys=True).encode()),'binarySha256':stack['binarySha256']}
 initialsha=sha(json.dumps(initial,sort_keys=True).encode());save(out/f'rounds/r{n}/canonical-initial-state.json',initial)
 for p in [runtime/'fixture-manifest.json',runtime/'initial-verifier.json',points/'initial-inventory.json',points/'initial-observation.json',points/'sequence-results.json',*points.glob('*-boundary-observation.json')]:copy(p,out/f'rounds/r{n}/boundaries'/p.name)
 copy(base/f'supplemental/r{n}-l3.json',out/f'rounds/r{n}/supplemental.json')
 round_={'prefix':stack['prefix'],'initialStateSha256':initialsha,'initialVerifierPassed':json.loads((runtime/'initial-verifier.json').read_text())['passed'],'points':[]}
 for name in ['precheck','l1','l2','l3']:
  p=points/name;target=out/f'rounds/r{n}/{name}';m=package(p,target)
  m['source']='<PRIVATE_TEMP>/'+p.relative_to(tmp).as_posix()
  if m['privateRawPoints']:m['privateRawPoints']['path']=m['source']+'/k6-points.jsonl.gz'
  (target/'archive-manifest.json').write_bytes((json.dumps(m,indent=2)+'\n').encode())
  s=capacity(p);full[f'r{n}/{name}']=s;r=s['result'];agg=json.loads((p/'aggregate.json').read_text())
  http=count(agg,'http_reqs',phase='observe');failed=count(agg,'http_reqs',phase='observe',status='503')
  round_['points'].append({'name':name,'valid':r['valid'],'dropped':r['droppedIterations'],'interrupted':r['interruptedIterations'],'unexpectedErrors':count(agg,'phase19_errors'),'http503':count(agg,'http_reqs',status='503'),'deltaPerSecond':s['observeDeltaReqPerSecond'],'writePerSecond':s['observeHttpWriteReqPerSecond'],'inventoryPassed':json.loads((p/'verifier-after.json').read_text())['passed'],'observeHttpRequests':http,'observe503':failed,'observe503ErrorRate':failed/http if http else None})
 rounds.append(round_)
save(out/'round-summary.json',rounds);save(out/'capacity-summary.json',full);save(out/'qualification.json',qualify(rounds))
copy(tmp/'phase19-l3-repeatability-run.log',out/'verification/sequence.log')
copy(Path(__file__),out/'protocol/package-repeatability.py')
print(json.dumps({'rounds':rounds,'qualification':qualify(rounds)},indent=2))