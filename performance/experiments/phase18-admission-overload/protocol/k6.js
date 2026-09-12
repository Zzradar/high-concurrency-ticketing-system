import http from 'k6/http';
import {check} from 'k6';
export const options={scenarios:{idle:{executor:'constant-arrival-rate',rate:8,timeUnit:'1s',duration:'15s',preAllocatedVUs:4,maxVUs:8}},thresholds:{http_req_failed:['rate==0'],checks:['rate==1'],dropped_iterations:['count==0']}};
export default function(){
 const r=http.get('http://phase18v2-api:8080/sessions/p18-s-5000/seat-availability?zone=Zone%200&generation='+__ENV.GENERATION+'&since='+__ENV.CURSOR);
 check(r,{'status 200':r=>r.status===200,'empty delta':r=>{const b=r.json();return b.mode==='delta'&&b.changes.length===0;}});
}
export function handleSummary(data){return {'/evidence/k6-summary.json':JSON.stringify(data,null,2)};}
