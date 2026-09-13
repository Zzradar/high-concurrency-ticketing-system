import json,os,sys,urllib.request,urllib.error,hashlib,subprocess
from pathlib import Path
R=Path(r'C:\Users\a12\AppData\Local\Temp\phase18-review-v2-8a62d57');O=Path(__file__).parent
os.environ.update(PHASE18_BASE_URL='http://127.0.0.1:18382',PHASE18_POSTGRES_CONTAINER='phase18-review-v2-postgres',PHASE18_REDIS_CONTAINER='phase18-review-v2-redis')
sys.path.insert(0,str(R/'backend/tests'))
from phase18_admission_http_test import AdmissionHTTP,sql
def get(s,tag=None):
 req=urllib.request.Request(os.environ['PHASE18_BASE_URL']+'/sessions/'+s+'/seat-layout',headers={'If-None-Match':tag} if tag else {})
 try:r=urllib.request.urlopen(req,timeout=10)
 except urllib.error.HTTPError as e:r=e
 with r:
  b=r.read();return {'status':r.status,'headers':dict(r.headers),'etag':r.headers.get('ETag'),'body':b.decode(),'sha256':hashlib.sha256(b).hexdigest()}
f=AdmissionHTTP();f.setUp();sid=f.s;seat=f.seats[0]['id']
def revision():return int(sql("SELECT revision FROM public.session_layout_revisions WHERE session_id='"+sid+"'"))
before=get(sid);rv=revision();assert json.loads(before['body'])['seats'][0]['price']==100
try:
 sql("UPDATE public.session_seats SET price=101 WHERE id='"+seat+"'")
 after=get(sid);old=get(sid,before['etag']);new=get(sid,after['etag']);v1=get(sid,before['etag'].replace('seat-layout-v2','seat-layout-v1'))
 original={'before':before,'revisionBefore':rv,'revisionAfter':revision(),'after':after,'oldTag':old,'newTag':new,'v1Tag':v1}
 assert before['etag']!=after['etag'] and before['sha256']!=after['sha256']
 assert old['status']==200 and new['status']==304 and new['body']=='' and v1['status']==200
finally:sql("UPDATE public.session_seats SET price=100 WHERE id='"+seat+"'")
original['restored']=get(sid);assert original['restored']['sha256']==before['sha256']
(O/'original-price-closed.json').write_text(json.dumps(original,indent=2),encoding='utf-8');print('Original price 100->101 case PASS; old tag 200, new tag 304, v1 200; restored')
# A SQL session can contain a temporary table without changing its search_path.
# Trigger helpers must resolve their own schema, not a caller's temp namespace.
baseline=get(sid);beforeRevision=revision()
mutation="""BEGIN;
SHOW search_path;
CREATE TEMP TABLE session_layout_revisions AS SELECT * FROM public.session_layout_revisions;
UPDATE public.session_seats SET price=101 WHERE id='%s';
SELECT 'public',revision FROM public.session_layout_revisions WHERE session_id='%s';
SELECT 'temporary',revision FROM pg_temp.session_layout_revisions WHERE session_id='%s';
COMMIT;"""%(seat,sid,sid)
try:
 result=sql(mutation);actual=get(sid);conditional=get(sid,baseline['etag'])
 shadow={'session':sid,'sql':mutation,'sqlOutput':result,'before':baseline,'after':actual,'conditional':conditional,'revisionBefore':beforeRevision,'revisionAfter':revision(),'functions':sql("SELECT proname,prosecdef,proconfig FROM pg_proc JOIN pg_namespace n ON n.oid=pronamespace WHERE n.nspname='public' AND proname LIKE '%layout%' ORDER BY proname")}
finally:sql("UPDATE public.session_seats SET price=100 WHERE id='"+seat+"'")
shadow['restored']=get(sid);assert shadow['restored']['sha256']==baseline['sha256']
(O/'schema-shadow-counterexample.json').write_text(json.dumps(shadow,indent=2),encoding='utf-8')
print(json.dumps({'beforeRevision':beforeRevision,'afterRevision':shadow['revisionAfter'],'bodyChanged':actual['sha256']!=baseline['sha256'],'etagChanged':actual['etag']!=baseline['etag'],'conditionalStatus':conditional['status'],'sqlOutput':result},indent=2))
assert actual['sha256']!=baseline['sha256']
assert conditional['status']==200 and actual['etag']!=baseline['etag'],'MAJOR: temporary table shadows revision updates; changed public Layout validates stale ETag'
