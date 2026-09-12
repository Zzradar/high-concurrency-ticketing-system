"""Capture an explicitly INCOMPLETE baseline checkpoint without altering the SUT."""
import datetime,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(r'D:\Documents\vscode\high-concurrency-ticketing-system-phase18')
OUT=Path(__file__).resolve().parent
def run(*args):
 p=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',timeout=45)
 return {'exitCode':p.returncode,'stdout':p.stdout.strip(),'stderr':p.stderr.strip()}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
images={name:json.loads(run('docker','image','inspect',name)['stdout'])[0] for name in ['phase14-engineering-build:20260910-v3','postgres:16-alpine','redis:7.4-alpine','nginx:1.28-alpine']}
containers={}
for name in ['phase18-baseline-build','phase18-postgres','phase18-redis','phase18-api','phase18-frontend']:
 c=json.loads(run('docker','inspect',name)['stdout'])[0];h=c['HostConfig']
 containers[name]={'image':c['Image'],'state':c['State'],'limits':{k:h.get(k) for k in ['NanoCpus','Memory','MemorySwap','PidsLimit','Ulimits']},'ports':c['NetworkSettings']['Ports']}
manifest={
 'status':'BLOCKED_STAGE0_NOT_VALID','baselineSutSha':run('git','-C',str(ROOT),'rev-parse','HEAD')['stdout'],
 'gitDirty':bool(run('git','-C',str(ROOT),'status','--porcelain')['stdout']),
 'branch':'phase18/admission-overload-control','worktree':str(ROOT),'capturedUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'blocker':'Real Edge browser did not enter document.hidden after tab switch. Chromium launch failed; first Edge build used default mock mode; real-API build collected requests but visibility gate failed. Stop required by implementation prompt.',
 'build':{'cmake':['-DCMAKE_BUILD_TYPE=Release','-DBUILD_TESTING=ON','-DBUILD_SHARED_LIBS=OFF','-DTICKETING_FETCH_DROGON=ON','-DFETCHCONTENT_SOURCE_DIR_DROGON=/src/build/_deps/drogon-src'],'parallel':2,'cppStandard':20,'drogonSha':'4c5430757ea5451a7c38fbbef4b4bef7dbb47f2f','trantorSha':'63a4e5e164e219dc3bf30cdbfa1462ae5602fa97','frontendEnv':{'VITE_USE_MOCK_API':'false'},'backendBinarySha256':sha(OUT/'ticketing_backend')},
 'versions':{'node':run('node','--version'),'python':run('python','--version'),'docker':run('docker','version','--format','{{json .}}')},
 'images':{name:{'id':v['Id'],'repoDigests':v['RepoDigests']} for name,v in images.items()},
 'containers':containers,'networks':['phase18-stage0','phase18-ingress'],
 'dockerResources':run('docker','info','--format','CPUs={{.NCPU}} Memory={{.MemTotal}}'),
 'otherContainers':run('docker','ps','--format','{{.Names}}'),
 'repositoryConfigs':{p.name:{'sha256':sha(p),'relatedFields':{k:json.loads(p.read_text(encoding='utf-8')).get(k) for k in ['app','redis_clients']}} for p in (ROOT/'backend/config').glob('*.json')},
 'runtimeConfigSha256':sha(OUT/'config.json'),
 'verification':{'ctest':{'passed':34,'failed':0},'vitest':{'passed':265,'failed':0},'databaseChecks':{'passed':27,'violations':0},'burst':{'offered':8,'created':1,'seatConflict':7}},
 'limitations':['Stage0 incomplete; no after measurement and no performance improvement claim.','Browser hidden/foreground gate failed; browser data is diagnostic only.','Initial network and mock-build failures retained.','Measurement protocol is not yet frozen or committed; external/committed script identity gate not satisfied.','No complete browser PG/Redis/resource sampling or k6 summary; no complete baseline manifest.','Host shared with historical running containers.','No production source, configuration, migration or tracked test changes; no commit or push.'],
 'files':{str(p.relative_to(OUT)):{'sha256':sha(p),'bytes':p.stat().st_size} for p in OUT.rglob('*') if p.is_file() and p.name!='checkpoint.json'}
}
(OUT/'checkpoint.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
print('Saved incomplete Stage0 checkpoint.')
