import {createRequire} from 'node:module';
import {readFile,writeFile,mkdir,access} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {spawn} from 'node:child_process';
import path from 'node:path';
import assert from 'node:assert/strict';
const [root,out,profile]=process.argv.slice(2);
const require=createRequire(path.join(root,'frontend/package.json'));
const {chromium}=require('@playwright/test');
const env=JSON.parse(await readFile(new URL('./browser-environment.json',import.meta.url),'utf8'));
assert.equal(require('playwright/package.json').version,env.playwright);
assert.equal(createHash('sha256').update(await readFile(env.executable)).digest('hex'),env.binarySha256,'Browser binary drift invalidates A/B');
try{await access(profile);throw new Error('Refuse reused browser profile');}catch(e){if(e.code!=='ENOENT')throw e;}
await mkdir(profile,{recursive:true});
const args=env.args.map(a=>a==='--user-data-dir=PROFILE'?'--user-data-dir='+profile:a);
const result={startedUtc:new Date().toISOString(),environment:env,profile,args,connection:'CDP noDefaults=true',requests:[],phases:[],timeline:[],topology:[],errors:[],maxInflight:0,passed:false};
const child=spawn(env.executable,args,{windowsHide:true,stdio:['ignore','pipe','pipe']});let logs='';
child.stdout.on('data',d=>logs+=d);child.stderr.on('data',d=>logs+=d);
let browser;let active=0;let sequence=0;const pending=new Map();const bodies=[];
try{
 let endpoint;
 for(let i=0;i<100;i++){
  try{endpoint='http://127.0.0.1:'+(await readFile(path.join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0];break;}catch{}
  await new Promise(r=>setTimeout(r,100));
 }
 assert(endpoint);browser=await chromium.connectOverCDP(endpoint,{noDefaults:true});
 assert.equal(browser.contexts().length,1);const context=browser.contexts()[0];
 await context.addInitScript(()=>{
  window.phase18Visibility=[];
  const record=(type,trusted)=>window.phase18Visibility.push({type,trusted,hidden:document.hidden,visibilityState:document.visibilityState,dateNow:Date.now(),performanceNow:performance.now(),entries:performance.getEntriesByType('visibility-state').map(x=>x.toJSON())});
  for(const type of ['visibilitychange','focus','blur'])window.addEventListener(type,e=>record(type,e.isTrusted));record('init',null);
 });
 const seat=context.pages()[0];const other=await context.newPage();assert.equal(context.pages().length,2);
 seat.on('pageerror',e=>result.errors.push(e.message));
 seat.on('request',r=>{
  if(!r.url().includes('/seat-availability'))return;
  assert(r.url().startsWith('http://127.0.0.1:18183/api/'));
  const item={id:++sequence,url:r.url(),startEpochMs:Date.now(),startMonotonicNs:process.hrtime.bigint().toString()};
  pending.set(r,item);result.requests.push(item);active++;result.maxInflight=Math.max(result.maxInflight,active);
 });
 seat.on('response',r=>{
  const item=pending.get(r.request());if(!item)return;
  item.status=r.status();item.headersEpochMs=Date.now();item.fixture=r.headers()['x-phase18-fixture'];
  bodies.push(r.body().then(raw=>{item.bytes=raw.length;const b=JSON.parse(raw);item.mode=b.mode;item.changeCount=b.changes?.length;item.hasMore=b.hasMore;}).catch(e=>{item.bodyError=e.message;}));
 });
 function finish(r,error){const item=pending.get(r);if(!item)return;item.endEpochMs=Date.now();item.ms=Number(process.hrtime.bigint()-BigInt(item.startMonotonicNs))/1e6;if(error)item.error=error;active--;pending.delete(r);}
 seat.on('requestfinished',r=>finish(r));seat.on('requestfailed',r=>finish(r,r.failure()?.errorText));
 await other.goto('data:text/html,<title>Neutral tab</title><h1>Neutral</h1>');
 await seat.bringToFront();
 const first=seat.waitForResponse(r=>r.url().includes('/seat-availability')&&r.status()===200,{timeout:20000});
 const navigation=await seat.goto('http://127.0.0.1:18183/sessions/p18-s-5000/seats');
 assert.equal(navigation.headers()['x-phase18-fixture'],'stage0-v2');await first;
 for(const [name,p]of [['seat',seat],['neutral',other]]){
  const cdp=await context.newCDPSession(p);const {targetInfo}=await cdp.send('Target.getTargetInfo');
  result.topology.push({name,...targetInfo,...await cdp.send('Browser.getWindowForTarget',{targetId:targetInfo.targetId})});
  if(name==='seat')result.browser=await cdp.send('Browser.getVersion');await cdp.detach();
 }
 assert.equal(result.topology[0].windowId,result.topology[1].windowId);
 assert.equal(result.browser.product,env.product);
 for(const [state,target,hidden,duration]of [['visible',seat,false,60000],['hidden',other,true,10000],['restored',seat,false,10000]]){
  const actionAt=Date.now();await target.bringToFront();
  await seat.waitForFunction(h=>document.hidden===h && document.visibilityState===(h?'hidden':'visible'),hidden,{timeout:5000,polling:50});
  result.phases.push({state,actionAt,observedAt:Date.now(),durationMs:duration,...await seat.evaluate(()=>({hidden:document.hidden,visibilityState:document.visibilityState}))});
  await seat.waitForTimeout(duration);
 }
 await Promise.all(bodies);assert.equal(result.errors.length,0);assert(result.requests.length>0);
 assert(result.requests.every(r=>r.status===200&&r.fixture==='stage0-v2'&&!r.error));
 // Baseline records native background behavior; it does not enforce the after-policy silence rule.
 result.passed=true;
}catch(e){result.error={message:e.message,stack:e.stack};process.exitCode=1;}
finally{
 if(browser){
  for(const p of browser.contexts()[0].pages())result.timeline.push({url:p.url(),records:await p.evaluate(()=>window.phase18Visibility||[]).catch(()=>[])});
  const cdp=await browser.newBrowserCDPSession();await cdp.send('Browser.close').catch(()=>{});await browser.close();
 }else child.kill();
 result.endedUtc=new Date().toISOString();result.inflightAtClose=active;
 await writeFile(out,JSON.stringify(result,null,2));await writeFile(out+'.browser.log',logs);
 console.log(JSON.stringify({passed:result.passed,requests:result.requests.length,maxInflight:result.maxInflight,phases:result.phases,error:result.error?.message}));
}
