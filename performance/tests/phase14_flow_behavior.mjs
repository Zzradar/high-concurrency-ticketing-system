import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
const targets=JSON.parse(fs.readFileSync(0,'utf8'));
const root=path.resolve('performance/k6/lib');
const source=fs.readFileSync(path.join(root,'phase14-model.js'),'utf8');
const model=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
assert.equal(model.hotspotTarget(10,targets,20).sessionId,'perf-session-002-001');
assert.deepEqual(Object.fromEntries(['browse','hold','order'].map(g=>[g,Array.from({length:20},(_,i)=>model.group(i,targets)).filter(x=>x===g).length])),{browse:12,hold:5,order:3});
for (const [status,body,expected,result] of [[200,{id:1},200,'business_success'],[409,{code:'SEAT_CONFLICT'},201,'business_conflict'],[503,{code:'AUTH_BUSY'},200,'capacity_rejection'],[503,{code:'OTHER'},200,'system_error'],[0,null,200,'system_error'],[200,null,200,'system_error'],[200,{},200,'unexpected_contract']]) {
    assert.equal(model.classify(status,body,expected,x=>x.id===1,['SEAT_CONFLICT']),result);
}
assert.throws(()=>model.boundedIndex(2,[0,2]));
const once=model.onceState();assert(once.claim());assert(!once.claim());

async function harness({fn='burst',index=0,failConfirm=false,failLogin=false,neverPay=false,kind='J1',role='main'}={}) {
    let clock=100000,jarUser=null;const requests=[],points=[],sleeps=[],events=[];
    const users=Array.from({length:targets.dataset.activeAuthSessions},(_,i)=>({userId:'user-'+i,sessionToken:'session-'+i,csrfToken:'csrf-'+i}));
    const loginUsers=Array.from({length:20},(_,i)=>({userId:'login-'+i,username:'login-'+i}));
    const execution={scenario:{name:'main',iterationInTest:index},vu:{idInTest:index+1}};
    const spec={targets,case:kind,releaseAtMs:100000,runId:'phase14-test',idempotencyNamespace:'phase14-test',
        scenarios:{main:{},control_auth:{},payment:{}},mapping:{main:{count:20,users:20,path:'formal',sessionCount:1}}};
    let checkout=null,paid=false;
    function respond(method,url,body,params) {
        clock+=2;body=body===null||body===undefined?null:typeof body==='string'?JSON.parse(body):body;
        requests.push({method,url,body,params});
        assert(!Object.keys(params.tags).some(x=>['url','user','order','seat','session','runId'].includes(x)));
        assert(!params.tags.name.includes('perf-'));assert(!params.tags.name.includes('phase14-test'));
        const u=Number(/session-(\d+)/.exec(params.headers.Cookie||'')?.[1]||0);
        const sid=/\/sessions\/([^/?]+)/.exec(url)?.[1];let status=200,b;
        if(url.endsWith('/auth/login')){if(failLogin){status=503;b={code:'AUTH_BUSY'};}else{jarUser=body.username;b={id:jarUser};}}
        else if(url.endsWith('/notifications')||url.includes('/checkout-sessions?')||url.includes('/orders?'))b=[];
        else if(url.endsWith('/auth/me'))b={id:params.headers.Cookie?users[u].userId:jarUser};
        else if(sid&&url.includes('/seat-'))b={sessionId:sid,seats:Array.from({length:targets.dataset.seatsPerSession},(_,j)=>({id:sid+'-'+j,status:'AVAILABLE'}))};
        else if(sid)b={id:sid,eventId:'event'};
        else if(url.endsWith('/events/event'))b={id:'event'};
        else if(url.endsWith('/checkout-sessions')&&method==='POST'){status=201;checkout={id:'checkout',userId:users[u].userId,sessionId:body.sessionId,seatIds:body.seatIds,revision:0};b=checkout;}
        else if(url.endsWith('/checkout-sessions/checkout/seats')){checkout={...checkout,seatIds:body.seatIds,revision:1};b=checkout;}
        else if(url.endsWith('/abandon'))b={...checkout,status:'ABANDONED'};
        else if(url.endsWith('/confirm')){checkout={...checkout,status:'RESERVED',order:{id:'order'},reservation:{id:'reservation'}};status=failConfirm?0:200;b=failConfirm?null:{checkoutSession:checkout};}
        else if(url.endsWith('/checkout-sessions/checkout'))b=checkout;
        else if(url.endsWith('/orders/order/pay')){status=202;b={paymentAttempt:{id:'attempt',status:'PROCESSING'}};}
        else if(url.endsWith('/payment-attempts/attempt')){paid=!neverPay;b={id:'attempt',orderId:'order',status:paid?'SUCCEEDED':'PROCESSING',acceptedAt:paid?'now':null};}
        else if(url.endsWith('/orders/order'))b={id:'order',reservationId:'reservation',sessionId:checkout.sessionId,seatIds:checkout.seatIds,status:paid?'PAID':'PENDING_PAYMENT'};
        else throw new Error('unexpected mock request '+url);
        return {status,json:()=>b,timings:{duration:2}};
    }
    const http={asyncRequest:(...args)=>{const step=args[3].tags.step;events.push(['start',step]);return new Promise(resolve=>setTimeout(()=>{const value=respond(...args);events.push(['end',step]);resolve(value);},1));},request:respond,batch:items=>items.map(x=>respond(x.method,x.url,null,x.params)),cookieJar:()=>({clear:()=>{jarUser=null;}})};
    class Metric{constructor(name){this.name=name;}add(value,tags){points.push({metric:this.name,value,tags:{scenario:execution.scenario.name,...tags}});}}
    const context=vm.createContext({__ENV:{PHASE14_SPEC:'spec',SHARD:'0',PHASE14_ROLE:role,LOGIN_PASSWORD:'synthetic'},open:()=>JSON.stringify(spec),Date:{now:()=>clock},console});
    const mocks={'k6/http':{default:http},'k6':{sleep:n=>{sleeps.push(n);clock+=n*1000;}},'k6/execution':{default:execution},'k6/metrics':{Counter:Metric,Trend:Metric},'./data.js':{loadSessions:()=>users,loadWorkloadUsers:()=>loginUsers}};
    const cache=new Map();
    async function link(name){
        if(cache.has(name))return cache.get(name);
        const m=mocks[name]?new vm.SyntheticModule(Object.keys(mocks[name]),function(){for(const [k,v] of Object.entries(mocks[name]))this.setExport(k,v);},{context}):new vm.SourceTextModule(fs.readFileSync(path.join(root,name),'utf8'),{context});
        cache.set(name,m);await m.link(link);return m;
    }
    const flow=await link('./phase14-flow.js');await flow.evaluate();await flow.namespace[fn]();
    if(fn==='online'){execution.vu.idInTest=999;await flow.namespace.online();}
    const starts=points.filter(x=>x.metric==='phase14_started');
    for(const step of new Set(starts.map(x=>x.tags.step)))assert.equal(starts.filter(x=>x.tags.step===step).length,points.filter(x=>x.metric==='phase14_results'&&x.tags.step===step).length);
    return {requests,points,sleeps,events,options:flow.namespace.options};
}
for(const kind of ['J1','O1']) {
    const h=await harness({kind,failConfirm:true});
    assert.equal(h.requests.filter(x=>x.method==='POST'&&x.url.endsWith('/checkout-sessions')).length,1);
    assert(h.requests.some(x=>x.url.endsWith('/checkout-sessions/checkout')));
    assert.equal(h.requests.some(x=>x.url.includes('/seat-layout')),kind==='J1');
    assert.equal(h.points.filter(x=>x.metric==='phase14_results'&&x.tags.step==='order'&&x.tags.result==='business_success').length,1);
}
for(const g of ['browse','hold','order']) {
    const index=Array.from({length:20},(_,i)=>i).find(i=>model.group(i,targets)===g);
    const h=await harness({fn:'online',index});
    assert.equal(h.points.filter(x=>x.metric==='phase14_users_entered').length,1);
    for(const [step,count] of Object.entries(targets.pageStartup.stepCounts))assert.equal(h.points.filter(x=>x.metric==='phase14_started'&&x.tags.step===step).length,count);
    assert.equal(h.requests.filter(x=>x.url.endsWith('/auth/me')).length,2);
    assert.equal(h.requests.filter(x=>x.method==='POST'&&x.url.endsWith('/checkout-sessions')).length,g==='browse'?0:1);
    if(g==='hold')assert(h.requests.some(x=>x.url.endsWith('/abandon')));
}
for(const failLogin of [false,true]) {
    const h=await harness({fn:'login',failLogin});
    assert.equal(h.requests.filter(x=>x.url.endsWith('/auth/me')).length,failLogin?0:1);
}
for(const neverPay of [false,true]) {
    const h=await harness({fn:'payment',neverPay,role:'probe'});
    const terminal=h.points.find(x=>x.metric==='phase14_results'&&x.tags.step==='payment_terminal');
    assert.equal(terminal.tags.result,neverPay?'unexpected_contract':'business_success');
    const cookie=h.requests.find(x=>x.method==='POST').params.headers.Cookie;
    assert(cookie.includes('session-'+targets.slices.payment[0]+';'));
    assert.deepEqual(Object.keys(h.options.scenarios),['control_auth','payment']);
}
console.log('PASS Phase14 flow: grouping, classification, bounds, once-only branches, same-checkout recovery, login jar, payment terminal/deadline, bounded tags');

for(const fn of ['enter','refresh','burst','hotspot','login','backgroundHold','backgroundOrder','control','payment']) {
    const h=await harness({fn,index:targets.dataset.registeredUsers+1});
    assert.equal(h.requests.length,0,fn+' tail must not send HTTP or acquire an identity');
    assert.deepEqual(h.points.map(x=>x.metric),['phase14_scheduler_boundary']);
}

// Source dependency edges and parallel groups, independently of wall-clock jitter.
const graph=await harness({kind:'J1'});const e=graph.events;
const at=(type,step)=>e.findIndex(x=>x[0]===type&&x[1]===step);
assert.equal(e.slice(0,2).filter(x=>x[0]==='start'&&x[1]==='startup_auth').length,2);
assert(at('end','startup_auth')<at('start','startup_session'));
for(const step of ['startup_event','startup_layout','startup_availability']){
  assert(at('end','startup_session')<at('start',step));
  for(const other of ['startup_event','startup_layout','startup_availability'])assert(at('start',step)<at('end',other));
  for(const list of ['startup_checkouts','startup_orders'])assert(at('end',step)<at('start',list));
}
assert(at('start','startup_orders')<at('end','startup_checkouts'));
for(const kind of ['O1','H1','E1']){const h=await harness({kind});assert.equal(h.events.length,0);}
// Global logical indices split into two shards consume exactly the same startup identities.
for(const shards of [1,2]){
  const seen=[];
  for(let shard=0;shard<shards;shard++)for(let index=shard;index<20;index+=shards){
    const h=await harness({fn:'enter',kind:'U2',index});
    assert.equal(h.events.filter(x=>x[0]==='start').length,10);
    seen.push(h.requests.find(x=>x.url.endsWith('/auth/me')).params.headers.Cookie);
  }
  assert.equal(new Set(seen).size,20);
}
