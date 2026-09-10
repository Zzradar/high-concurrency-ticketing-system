import http from 'k6/http';
import { sleep } from 'k6';
import exec from 'k6/execution';
import { Counter, Trend } from 'k6/metrics';
import { loadSessions, loadWorkloadUsers } from './data.js';
import { mutationHeaders, reservationHeaders, jsonHeaders } from './http.js';
import { SYSTEM_TAGS } from './config.js';
import { boundedIndex, classify, group, onceState, randomSeconds, seat, steps, hotspotTarget } from './phase14-model.js';

export const spec=JSON.parse(open(__ENV.PHASE14_SPEC));
const t=spec.targets;const sessions=loadSessions();const users=loadWorkloadUsers();
const base=__ENV.BASE_URL||'http://backend:8080';const shard=__ENV.SHARD;
if(!Number.isInteger(Number(shard))||Number(shard)<0||Number(shard)>=t.generator.maxShards)throw new Error('invalid shard');
const probeRole=__ENV.PHASE14_ROLE==='probe';
const selectedScenarios=Object.fromEntries(Object.entries(spec.scenarios).filter(([name])=>
    (name.startsWith('control_')||name==='payment')===probeRole));
export const options={systemTags:SYSTEM_TAGS,scenarios:selectedScenarios,discardResponseBodies:false,summaryTrendStats:['p(50)','p(95)','p(99)','max']};
const started=new Counter('phase14_started');const outcomes=new Counter('phase14_results');
const duration=new Trend('phase14_duration_ms',true);const iterStarted=new Counter('phase14_iterations_started');
const iterCompleted=new Counter('phase14_iterations_completed');const offset=new Trend('phase14_start_offset_ms',true);
const entered=new Counter('phase14_users_entered');const boundary=new Counter('phase14_scheduler_boundary');
const state=onceState();let onlineIndex=null;let sequence=0;

function tags(step,result=null) {
    if(!steps.includes(step))throw new Error('unbounded step');
    return {scenario:exec.scenario.name,step,shard,...(result?{result}:{})};
}
function record(step,result,ms) { outcomes.add(1,tags(step,result));duration.add(ms,tags(step,result)); }
function request(method,path,name,step,identity,body,expected,valid,conflicts=[]) {
    started.add(1,tags(step));let response=null;let parsed=null;const begin=Date.now();
    try {
        response=http.request(method,base+path,body===null?null:JSON.stringify(body),{
            headers:identity?mutationHeaders(identity):jsonHeaders({Origin:'http://performance.local'}),
            tags:{name,...tags(step)},timeout:`${t.probes.paymentDeadlineSeconds}s`,
        });
        parsed=response.json();
    } catch(_) {}
    const result=classify(response&&response.status,parsed,expected,valid,conflicts);
    record(step,result,Date.now()-begin);
    return {ok:result==='business_success',result,body:parsed};
}
function identity(slice,index){return sessions[boundedIndex(index,t.slices[slice])];}
function target(slice,index){
    const sessions=t.dataset.events*t.dataset.sessionsPerEvent;
    const slot=slice==='main'?index%sessions+Math.floor(index/sessions)*sessions*t.behavior.maxSeats:index;
    return seat(boundedIndex(slot,t.seatSlices[slice]),t);
}
function waitRelease(){const seconds=(spec.releaseAtMs-Date.now())/1000;if(seconds>0)sleep(seconds);}
export function setup(){waitRelease();return {};}
async function run(fn){waitRelease();iterStarted.add(1,{shard});try{await fn();iterCompleted.add(1,{shard});}catch(error){throw error;}}
function mapped(){return spec.mapping[exec.scenario.name];}
function nextIndex(m){const i=exec.scenario.iterationInTest;if(i>=m.count){boundary.add(1,{shard});return null;}return i+(m.offset||0);}
function auth(user,step='auth'){return request('GET','/auth/me','GET /auth/me',step,user,null,200,b=>b.id===user.userId);}
function availability(user,chosen,checkoutId=null) {
    const path=`/sessions/${chosen.sessionId}/seat-availability${checkoutId?'?checkoutSessionId='+checkoutId:''}`;
    return request('GET',path,'GET /sessions/{sessionId}/seat-availability','availability',user,null,200,b=>
        b.sessionId===chosen.sessionId&&Array.isArray(b.seats)&&b.seats.length===t.dataset.seatsPerSession&&
        b.seats.every(x=>x.id&&['AVAILABLE','HELD','SOLD'].includes(x.status)));
}
// Browser dependency graph: router and App auth start independently. The first
// successful auth triggers the watcher; App auth also triggers its mounted callback.
async function startupRead(path,name,step,user,valid) {
    started.add(1,tags(step));let response=null,body=null;const begin=Date.now();
    try {response=await http.asyncRequest('GET',base+path,null,{headers:mutationHeaders(user),
        tags:{name,...tags(step)},timeout:`${t.probes.paymentDeadlineSeconds}s`});body=response.json();}catch(_){}
    const result=classify(response&&response.status,body,200,valid);
    record(step,result,Date.now()-begin);return {ok:result==='business_success',result,body};
}
async function page(user,chosen) {
    started.add(1,tags('startup'));const begin=Date.now();let result='business_success';
    const read=(path,name,step,valid)=>startupRead(path,name,step,user,valid).then(x=>{if(!x.ok)result=x.result;return x;});
    const notification=()=>read('/notifications','GET /notifications','startup_notifications',Array.isArray);
    // App mount runs before the router's queued initial navigation guard.
    const appAuth=read('/auth/me','GET /auth/me','startup_auth',b=>b.id===user.userId);
    const routerAuth=read('/auth/me','GET /auth/me','startup_auth',b=>b.id===user.userId);
    let notified=false;
    const watch=async x=>{if(x.ok&&!notified){notified=true;await notification();}};
    const watchers=[routerAuth.then(watch),appAuth.then(watch)];
    const mounted=appAuth.then(x=>x.ok?notification():null);
    const route=async()=>{
        if(!(await routerAuth).ok)return;
        started.add(1,tags('page'));const pageBegin=Date.now();
        try {
        const s=await read(`/sessions/${chosen.sessionId}`,'GET /sessions/{sessionId}','startup_session',b=>b.id===chosen.sessionId&&b.eventId);
        if(!s.ok)return;
        const [event,layout,dynamic]=await Promise.all([
            read(`/events/${s.body.eventId}`,'GET /events/{eventId}','startup_event',b=>b.id===s.body.eventId),
            read(`/sessions/${chosen.sessionId}/seat-layout`,'GET /sessions/{sessionId}/seat-layout','startup_layout',b=>b.sessionId===chosen.sessionId&&Array.isArray(b.seats)&&b.seats.length===t.dataset.seatsPerSession),
            read(`/sessions/${chosen.sessionId}/seat-availability`,'GET /sessions/{sessionId}/seat-availability','startup_availability',b=>b.sessionId===chosen.sessionId&&Array.isArray(b.seats)&&b.seats.length===t.dataset.seatsPerSession)
        ]);
        if(![event,layout,dynamic].every(x=>x.ok))return;
        const ids=new Set(layout.body.seats.map(x=>x.id));
        if(ids.size!==t.dataset.seatsPerSession||new Set(dynamic.body.seats.map(x=>x.id)).size!==ids.size||!dynamic.body.seats.every(x=>ids.has(x.id)&&['AVAILABLE','HELD','SOLD'].includes(x.status))){result='unexpected_contract';return;}
        } finally {record('page',result,Date.now()-pageBegin);}
        if(result!=='business_success')return;
        await Promise.all([
            read(`/checkout-sessions?sessionId=${chosen.sessionId}&recoverable=true`,'GET /checkout-sessions','startup_checkouts',Array.isArray),
            read(`/orders?sessionId=${chosen.sessionId}&limit=${t.pageStartup.orderListLimit}`,'GET /orders','startup_orders',Array.isArray)
        ]);
    };
    await Promise.all([...watchers,mounted,route()]);
    record('startup',result,Date.now()-begin);return result;
}
async function purchase(user,chosen,index,kind,withPage,think=false) {
    started.add(1,tags('journey'));const begin=Date.now();let paused=0;let result='unexpected_contract';
    function pause(){if(think){const seconds=randomSeconds(index,sequence++,t.behavior.thinkSeconds,t.seed);sleep(seconds);paused+=seconds*1000;}}
    try {
        if(withPage){
            const pageResult=await page(user,chosen);if(pageResult!=='business_success'){result=pageResult;return null;}
        }
        pause();
        if(kind==='browse'){result=availability(user,chosen).result;return null;}
        const holds=kind==='hold'&&withPage;
        const count=holds?index%t.behavior.maxSeats+1:1;
        const firstNumber=Number(chosen.sessionSeatId.slice(-6));const prefix=chosen.sessionSeatId.slice(0,-6);
        const seatIds=Array.from({length:count},(_,j)=>prefix+String(firstNumber+j).padStart(6,'0'));
        const c=request('POST','/checkout-sessions','POST /checkout-sessions','hold',user,{sessionId:chosen.sessionId,seatIds},201,b=>b.id&&b.userId===user.userId&&b.sessionId===chosen.sessionId,['SEAT_TEMPORARILY_HELD','SEAT_CONFLICT']);
        if(!c.ok){result=c.result;return null;}
        pause();
        const adjustedIds=holds?(count===t.behavior.maxSeats?seatIds.slice(0,-1):[...seatIds,prefix+String(firstNumber+count).padStart(6,'0')]):seatIds;
        const adjusted=request('PUT',`/checkout-sessions/${c.body.id}/seats`,'PUT /checkout-sessions/{id}/seats','adjust',user,{seatIds:adjustedIds,expectedRevision:c.body.revision},200,b=>b.id===c.body.id&&b.seatIds.length===adjustedIds.length&&b.seatIds.every(id=>adjustedIds.includes(id)));
        if(!adjusted.ok){result=adjusted.result;return null;}
        if(kind==='hold') {
            const a=request('POST',`/checkout-sessions/${c.body.id}/abandon`,'POST /checkout-sessions/{id}/abandon','abandon',user,null,200,b=>b.id===c.body.id&&b.status==='ABANDONED');
            result=a.result;return null;
        }
        let confirmed=request('POST',`/checkout-sessions/${c.body.id}/confirm`,'POST /checkout-sessions/{id}/confirm','confirm',user,null,200,b=>b.checkoutSession&&b.checkoutSession.id===c.body.id&&b.checkoutSession.status==='RESERVED'&&b.checkoutSession.order,['SEAT_CONFLICT']);
        let checkout=confirmed.body&&confirmed.body.checkoutSession;
        if(!confirmed.ok&&confirmed.result==='system_error') {
            // Restore the same checkout. Never create another logical purchase.
            const recovered=request('GET',`/checkout-sessions/${c.body.id}`,'GET /checkout-sessions/{id}','recover',user,null,200,b=>b.id===c.body.id&&b.userId===user.userId&&b.sessionId===chosen.sessionId);
            checkout=recovered.body;
        }
        if(!checkout||checkout.status!=='RESERVED'||!checkout.order){result=confirmed.result;return null;}
        const order=request('GET',`/orders/${checkout.order.id}`,'GET /orders/{orderId}','order',user,null,200,b=>b.id===checkout.order.id&&b.reservationId===checkout.reservation.id&&b.sessionId===chosen.sessionId&&b.seatIds.length===1&&b.seatIds[0]===chosen.sessionSeatId&&b.status==='PENDING_PAYMENT');
        result=order.result;return order.ok?order.body:null;
    } finally {record('journey',result,Math.max(0,Date.now()-begin-paused));}
}

export function online() {return run(async()=>{
    const m=mapped();if(onlineIndex===null)onlineIndex=exec.vu.idInTest-1;
    const user=identity('main',onlineIndex);const chosen=target('main',onlineIndex);
    if(state.claim()){entered.add(1,{shard});await purchase(user,chosen,onlineIndex,group(onlineIndex,t),true,true);}
    else availability(user,chosen);
    const range=t.behavior.refreshSeconds;
    sleep(randomSeconds(onlineIndex,sequence++,range,t.seed));
});}
export function enter() {const m=mapped();const i=nextIndex(m);if(i===null)return;return run(async()=>{entered.add(1,{shard});await purchase(identity('main',i),target('main',i),i,group(i,t),true,true);});}
export function refresh() {const m=mapped();const next=nextIndex(m);if(next===null)return;return run(()=>{const i=next%m.users;availability(identity(m.slice||'main',i),target('main',i));});}
export function burst() {const m=mapped();const i=nextIndex(m);if(i===null)return;return run(()=>purchase(identity('main',i),target('main',i),i,'order',spec.case==='J1'));}
export function hotspot() {const m=mapped();const i=nextIndex(m);if(i===null)return;return run(()=>{
    const chosen=hotspotTarget(i,t,m.sessionCount,spec.case==='H3');
    const user=identity('main',i);offset.add(Date.now()-spec.releaseAtMs,tags(m.path==='formal'?'reservation':'hold'));
    if(m.path==='formal') {
        started.add(1,tags('reservation'));let response=null,b=null;const begin=Date.now();
        try{response=http.post(base+'/reservations',JSON.stringify({sessionId:chosen.sessionId,seatIds:[chosen.sessionSeatId]}),{headers:reservationHeaders(user,`${spec.idempotencyNamespace}-${i}`),tags:{name:'POST /reservations',...tags('reservation')}});b=response.json();}catch(_){}
        record('reservation',classify(response&&response.status,b,201,x=>x.reservation&&x.reservation.userId===user.userId&&x.order&&x.order.seatIds[0]===chosen.sessionSeatId,['SEAT_CONFLICT']),Date.now()-begin);
    } else request('POST','/checkout-sessions','POST /checkout-sessions','hold',user,{sessionId:chosen.sessionId,seatIds:[chosen.sessionSeatId]},201,b=>b.id&&b.userId===user.userId,['SEAT_TEMPORARILY_HELD']);
});}
export function login() {const m=mapped();const i=nextIndex(m);if(i===null)return;return run(()=>{
    const user=users[i];if(!user)throw new Error('login slice exhausted');http.cookieJar().clear(base);
    const result=request('POST','/auth/login','POST /auth/login','login',null,{username:user.username,password:__ENV.LOGIN_PASSWORD},200,b=>b.id===user.userId);
    if(result.ok)request('GET','/auth/me','GET /auth/me','login_identity',null,null,200,b=>b.id===user.userId);
});}
export function backgroundHold(){const m=mapped();const i=nextIndex(m);if(i===null)return;return run(()=>purchase(identity('backgroundHold',i),target('backgroundHold',i),i,'hold',false));}
export function backgroundOrder(){const m=mapped();const i=nextIndex(m);if(i===null)return;return run(()=>purchase(identity('backgroundOrder',i),target('backgroundOrder',i),i,'order',false));}
export function control() {const m=mapped();const next=nextIndex(m);if(next===null)return;return run(()=>{
    const i=next%(t.slices.control[1]-t.slices.control[0]);const user=identity('control',i);
    if(m.step==='health')request('GET','/health','GET /health','health',null,null,200,b=>b.status==='ok'&&b.database==='up');
    else if(m.step==='auth')auth(user);else {
        const chosen=spec.sentinel;
        request('GET',`/sessions/${chosen.sessionId}/seat-availability`,'GET /sessions/{sessionId}/seat-availability','availability',user,null,200,b=>b.sessionId===chosen.sessionId&&b.seats.some(x=>x.id===chosen.sessionSeatId&&x.status==='HELD'));
    }
});}
export function payment() {const m=mapped();const i=nextIndex(m);if(i===null)return;return run(async()=>{
    const begin=Date.now();
    const user=identity('payment',i);const chosen=target('payment',i);const order=await purchase(user,chosen,i,'order',false);
    started.add(1,tags('payment_terminal'));let ok=false;
    try{
        if(!order)return;
        const paid=request('POST',`/orders/${order.id}/pay`,'POST /orders/{orderId}/pay','payment_start',user,null,202,b=>b.paymentAttempt&&b.paymentAttempt.status==='PROCESSING');
        if(!paid.ok)return;const attempt=paid.body.paymentAttempt.id;
        while(Date.now()-begin<t.probes.paymentDeadlineSeconds*1000){
            sleep(t.probes.pollSeconds);
            const poll=request('GET',`/payment-attempts/${attempt}`,'GET /payment-attempts/{id}','payment_poll',user,null,200,b=>b.id===attempt&&b.orderId===order.id);
            if(!poll.ok)return;
            if(poll.body.status==='SUCCEEDED'&&poll.body.acceptedAt){
                const terminal=request('GET',`/orders/${order.id}`,'GET /orders/{orderId}','order',user,null,200,b=>b.id===order.id&&b.status==='PAID');
                ok=terminal.ok&&Date.now()-begin<=t.probes.paymentDeadlineSeconds*1000;return;
            }
        }
    }finally{record('payment_terminal',ok?'business_success':'unexpected_contract',Date.now()-begin);}
});}
export function handleSummary(data){return {[`/results/${spec.runId}/shards/${shard}/summary.json`]:JSON.stringify(data),stdout:`Phase14 shard ${shard} summary saved\n`};}

export function warmPage(){const m=mapped();const i=nextIndex(m);if(i===null)return;return run(()=>page(identity(m.slice,i),target(m.seatSlice,i)));}
