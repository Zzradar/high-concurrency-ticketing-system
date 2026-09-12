import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
const errors=new Counter('phase16_system_errors');
export const options={
  scenarios:{availability:{executor:'constant-arrival-rate',rate:Number(__ENV.RATE||200),timeUnit:'1s',duration:__ENV.DURATION||'20s',preAllocatedVUs:100,maxVUs:100}},
  thresholds:{http_req_failed:['rate==0'],phase16_system_errors:['count==0'],dropped_iterations:['count==0'],checks:['rate==1']},
  summaryTrendStats:['min','med','p(90)','p(95)','p(99)','max','avg'],
};
export function setup(){
  const root='http://phase16-api-backend:8080/sessions/perf-session-phase16/seat-availability';
  const snap=http.get(root+'?zone=Zone%200').json();
  let url=root;
  if(__ENV.MODE!=='legacy')url+='?zone=Zone%200';
  if(__ENV.MODE==='delta' || __ENV.MODE==='controlled')url+='&generation='+encodeURIComponent(__ENV.GENERATION||snap.generation)+'&since='+encodeURIComponent(__ENV.CURSOR||snap.cursor);
  return {url};
}
export default function(data){
  const r=http.get(data.url,{tags:{mode:__ENV.MODE},headers:{'Accept-Encoding':'gzip'}});
  const ok=check(r,{'HTTP 200':r=>r.status===200,'expected payload':r=>{
    try {const body=r.json();return __ENV.MODE==='legacy'?body.seats.length===5000:__ENV.MODE==='snapshot'?body.mode==='snapshot'&&body.seats.length===1000:body.mode==='delta'&&body.changes.length===Number(__ENV.CHANGES||0);} catch(_){return false;}
  }});
  errors.add(ok?0:1);
}
export function handleSummary(data){return {[__ENV.RESULT]:JSON.stringify(data,null,2)};}
