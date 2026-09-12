"""Independent representation-change regression. Mutates only isolated fixture DB."""
import json,os,sys,hashlib,urllib.request,urllib.error
from pathlib import Path
O=Path(__file__).parent
R=Path(__file__).resolve().parents[5]
os.environ.update(PHASE18_BASE_URL='http://127.0.0.1:18184',PHASE18_POSTGRES_CONTAINER='phase18-policy-http-postgres',PHASE18_REDIS_CONTAINER='phase18-policy-http-redis')
sys.path.insert(0,str(R/'backend/tests'))
from phase18_admission_http_test import AdmissionHTTP,sql
f=AdmissionHTTP();f.setUp()
def get(tag=None,gzip=False):
 h={}
 if tag:h['If-None-Match']=tag
 if gzip:h['Accept-Encoding']='gzip'
 req=urllib.request.Request(os.environ['PHASE18_BASE_URL']+'/sessions/'+f.s+'/seat-layout',headers=h)
 try:r=urllib.request.urlopen(req,timeout=10)
 except urllib.error.HTTPError as e:r=e
 with r:b=r.read();return {'status':r.status,'headers':dict(r.headers),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b),'body':b.decode() if not r.headers.get('Content-Encoding') else None}
before=get();tag=next(v for k,v in before['headers'].items() if k.lower()=='etag')
cases={v:get(v) for v in [tag,tag[2:],'"other", '+tag,'*',tag+',',tag+' garbage']}
seat=f.seats[0]['id']
# PostgreSQL accepts an authoritative price correction; do not alter timestamps or identity.
q="UPDATE session_seats SET price=price+1 WHERE id='"+seat+"' RETURNING price"
new_price=sql(q)
try:
 unconditional=get();conditional=get(tag)
finally:sql("UPDATE session_seats SET price=price-1 WHERE id='"+seat+"'")
result={'session':f.s,'mutationSql':q,'returnedPrice':new_price,'before':before,'headerCases':cases,'gzip':get(gzip=True),'afterUnconditional':unconditional,'afterConditional':conditional,'restored':get()}
(O/'independent-layout.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
assert before['status']==unconditional['status']==200
assert before['sha256']!=unconditional['sha256'],'fixture must change actual HTTP representation'
assert conditional['status']==200,'STALE_304: old ETag validated after authoritative PG price and HTTP body changed'
