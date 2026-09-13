"""Read-only A/B integrity checks. Reuses frozen summaries and phase_at; never rewrites protocol/statistics."""
import argparse,collections,hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];E=ROOT/'performance/experiments/phase18-admission-overload';B=E/'baseline'
sys.path.insert(0,str(E/'protocol'))
from stats import phase_at
BASE_SUT='ed51447154418e05ed9e4c49728f3eb114713db9'
FROZEN={'manifest.json':'19f394034d74e027a19e62f3e61f2ab82c9806b542604d666dc24d948640f338','baseline/manifest.json':'c0891851436eb997e3414c4d2b6b5525a72c38b7fe635a9cb582e46d77b2e402'}
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def preflight():
 for p,digest in FROZEN.items():assert sha(E/p)==digest,p
 m=read(B/'manifest.json');assert m['source']['sha']==BASE_SUT
 assert len(m['source']['scripts'])==8
 for p,digest in m['source']['scripts'].items():assert sha(E/'protocol'/p)==digest,p
 env=read(E/'protocol/browser-environment.json');assert sha(Path(env['executable']))==env['binarySha256']
 assert read(ROOT/'frontend/node_modules/playwright/package.json')['version']==env['playwright']
 for role,info in m['images'].items():
  current=json.loads(subprocess.check_output(['docker','image','inspect',info['tag']],text=True,encoding='utf-8'))[0]
  assert current['Id']==info['id'] and current['RepoDigests']==info['repoDigests'],role
 return m

def browser(d):
 timeline=next(t['records'] for t in d['timeline'] if '/sessions/' in t['url'])
 transitions=[r for r in timeline if r['type']=='visibilitychange'];hidden=next(r for r in transitions if r['hidden']);restored=next(r for r in transitions if not r['hidden'] and r['dateNow']>hidden['dateNow'])
 assert hidden['trusted'] and restored['trusted'] and hidden['visibilityState']=='hidden' and restored['visibilityState']=='visible'
 h,r=hidden['dateNow'],restored['dateNow'];counts=collections.Counter(phase_at(x['startEpochMs'],h,r) for x in d['requests'])
 resumed=[x for x in d['requests'] if x['startEpochMs']>=r]
 return {'nativeHiddenAt':h,'nativeRestoredAt':r,'hiddenDurationMs':r-h,'requestStartsByPhase':{p:counts[p] for p in ['visible','hidden','restored']},'restoreFirstRequestMs':min(x['startEpochMs'] for x in resumed)-r,'restoredSnapshots':sum(x.get('mode')=='snapshot' for x in resumed),'networkMaxInflight':d['maxInflight'],'totalRequests':len(d['requests'])}

def sql_features(folder,n):
 before={r['queryid']:r for r in read(folder/f'layout-{n}-before-database.json')['pg']};result=[]
 for r in read(folder/f'layout-{n}-after-database.json')['pg']:
  q=r['query'];kind='fullLayout' if 'inventory.price' in q and 'seat.seat_label' in q and 'inventory.status' not in q else 'layoutIdentity' if 's.created_at' in q and 'e.published_at' in q else None
  if not kind:continue
  old=before.get(r['queryid'],{});calls=r['calls']-old.get('calls',0);rows=r['rows']-old.get('rows',0)
  if calls:result.append({'kind':kind,'query':q,'calls':calls,'returnedRows':rows})
 return result

def compare(after):
 bm=preflight();am=read(after/'manifest.json')
 assert not am['source']['gitDirty'] and am['source']['sha']!=BASE_SUT
 assert am['source']['sha']!='4dd48c177516caf950103ce3f7751cc0fb056029', 'After SUT invalidated by direct-PostgreSQL ETag defect; preserve historical evidence and collect after-v2'
 assert am['source']['sha']!='6807a01516a75cf834ca1fac46fb1ac9abcdc53e', 'After SUT invalidated by search_path shadowing; preserve after-v2 and collect after-v3'
 assert am['source']['scripts']==bm['source']['scripts'];assert am['images']==bm['images'];assert am['protocol']==bm['protocol']
 assert read(after/'data-fingerprint.json')==read(B/'data-fingerprint.json')
 for role in ['build','api','frontend','postgres','redis','k6']:
  b=next(v for k,v in bm['containers'].items() if k.endswith('-'+role));a=next(v for k,v in am['containers'].items() if k.endswith('-'+role));assert a['limits']==b['limits'],role;assert a['image']==b['image'],role
 for p,info in am['files'].items():assert sha(after/p)==info['sha256'],p
 bb,ab=read(B/'browser.json'),read(after/'browser.json');assert ab['environment']==bb['environment'];assert ab['browser']==bb['browser'];assert ab['connection']==bb['connection'];assert ab['passed']
 assert len(ab['topology'])==2 and len({x['windowId'] for x in ab['topology']})==1 and len({x['browserContextId'] for x in ab['topology']})==1
 baselineBrowser,afterBrowser=browser(bb),browser(ab);assert afterBrowser['networkMaxInflight']==1;assert afterBrowser['requestStartsByPhase']['hidden']==0;assert 0<=afterBrowser['restoreFirstRequestMs']<1000;assert afterBrowser['restoredSnapshots']==1
 beforeReads,afterReads=read(B/'reads.json'),read(after/'reads.json');rows=[]
 for b,a in zip(beforeReads,afterReads,strict=True):
  assert a['seatCount']==b['seatCount'];assert a['layout'][0]['sha256']==b['layout'][0]['sha256']
  assert all(x['status']==(304 if x['kind']=='conditional' else 200) for x in a['layout']);assert all(x['bytes']==0 for x in a['layout'] if x['kind']=='conditional')
  n=a['seatCount'];oldSql,newSql=sql_features(B,n),sql_features(after,n)
  assert sum(x['calls'] for x in oldSql if x['kind']=='fullLayout')==42
  assert sum(x['calls'] for x in newSql if x['kind']=='fullLayout')==22
  rows.append({'seats':n,'beforeLayout':b['summaries'],'afterLayout':a['summaries'],'beforePayload':b['layout'][0]['bytes'],'afterPayload':a['layout'][0]['bytes'],'beforeGzipWire':b['gzipWire']['bytes'],'afterGzipWire':a['gzipWire']['bytes'],'beforeSnapshot':b['availability']['snapshotSummary'],'afterSnapshot':a['availability']['snapshotSummary'],'beforeDelta':b['availability']['deltaSummary'],'afterDelta':a['availability']['deltaSummary'],'beforeSql':oldSql,'afterSql':newSql})
 assert read(after/'verifier.json')['passed'];resources=read(after/'resource-samples.json');assert not resources['errors'] and len(resources['samples'])>20
 burst=read(after/'burst.json')['rows'];assert sum(r['status']==201 for r in burst)==1 and sum(r.get('code')=='SEAT_CONFLICT' for r in burst)==7
 k6=read(after/'k6-summary.json')['metrics'];assert k6['checks']['values']['fails']==0 and k6['http_req_failed']['values']['rate']==0 and k6['dropped_iterations']['values']['count']==0
 return {'passed':True,'baselineSutSha':BASE_SUT,'afterSutSha':am['source']['sha'],'frozenManifests':FROZEN,'baselineManifestSha256':sha(B/'manifest.json'),'afterManifestSha256':sha(after/'manifest.json'),'protocolHashes':bm['source']['scripts'],'layoutAndAvailability':rows,'beforeBrowser':baselineBrowser,'afterBrowser':afterBrowser,'beforeK6':read(B/'k6-summary.json')['metrics']['http_req_duration']['values'],'afterK6':k6['http_req_duration']['values'],'resourceSamples':len(resources['samples']),'limitations':['One identical OFF trial on a shared host, not production SLA.','PostgreSQL rows are returned rows from pg_stat_statements, not physical buffer-page scans.','OBSERVE/ENFORCED capability results are excluded from OFF improvements.','The frozen protocol retains its historical STAGE0_VALID manifest label; this comparison identifies the after SUT separately.']}
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--after',type=Path);args=parser.parse_args()
 result=compare(args.after) if args.after else {'preflightPassed':bool(preflight())};print(json.dumps(result,indent=2))
