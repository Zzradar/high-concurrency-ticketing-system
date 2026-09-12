// Official Edge channel-resolved executable/arguments, with CDP noDefaults to preserve native visibility.
import { createRequire } from 'node:module';
import { readFile,writeFile,mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import path from 'node:path';
import assert from 'node:assert/strict';
const [root,out,profile,launchLog]=process.argv.slice(2);
const require=createRequire(path.join(root,'frontend/package.json'));
const {chromium}=require('@playwright/test');
const launch=(await readFile(launchLog,'utf8')).split('\n').find(l=>l.includes('<launching> ')).split('<launching> ')[1].trim();
const end=launch.indexOf('.exe')+4;const executable=launch.slice(0,end);
assert.equal(executable,'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe');
const args=launch.slice(end).trim().split(' ').map(a=>a.startsWith('--user-data-dir=')?'--user-data-dir='+profile:a==='--remote-debugging-pipe'?'--remote-debugging-port=0':a);
assert(!args.some(a=>a.includes('headless')));assert(args.includes('about:blank'));
await mkdir(profile,{recursive:true});
const result={playwright:require('playwright/package.json').version,channelResolution:'official msedge launchPersistentContext log',executable,args,profile,headless:false,
 binarySha256:createHash('sha256').update(await readFile(executable)).digest('hex'),connection:'connectOverCDP(noDefaults:true); dedicated headed browser',topology:[],samples:[],timeline:[],passed:false};
const child=spawn(executable,args,{windowsHide:true,stdio:['ignore','pipe','pipe']});
let logs='';child.stdout.on('data',d=>logs+=d);child.stderr.on('data',d=>logs+=d);
let browser;
try{
 let endpoint;
 for(let i=0;i<100;i++){
  try{const data=await readFile(path.join(profile,'DevToolsActivePort'),'utf8');endpoint='http://127.0.0.1:'+data.split('\n')[0];break;}catch{}
  await new Promise(r=>setTimeout(r,100));
 }
 assert(endpoint,'Dedicated Edge DevTools endpoint unavailable');
 browser=await chromium.connectOverCDP(endpoint,{noDefaults:true});
 assert.equal(browser.contexts().length,1);const context=browser.contexts()[0];
 await context.addInitScript(()=>{
  window.visibilityRecords=[];
  const record=type=>window.visibilityRecords.push({type,hidden:document.hidden,visibilityState:document.visibilityState,dateNow:Date.now(),performanceNow:performance.now(),entries:performance.getEntriesByType('visibility-state').map(e=>e.toJSON())});
  for(const type of ['visibilitychange','focus','blur'])window.addEventListener(type,()=>record(type));record('init');
 });
 const seat=context.pages()[0];const other=await context.newPage();assert.equal(context.pages().length,2);
 await seat.goto('data:text/html,<title>Seat probe</title><h1>Seat</h1>');
 await other.goto('data:text/html,<title>Neutral probe</title><h1>Neutral</h1>');
 for(const [name,p]of [['seat',seat],['other',other]]){
  const cdp=await context.newCDPSession(p);const {targetInfo}=await cdp.send('Target.getTargetInfo');
  result.topology.push({name,...targetInfo,...await cdp.send('Browser.getWindowForTarget',{targetId:targetInfo.targetId})});
  if(name==='seat')result.browser=await cdp.send('Browser.getVersion');await cdp.detach();
 }
 assert.equal(result.topology[0].windowId,result.topology[1].windowId);
 for(let trial=0;trial<3;trial++)for(const [label,target,hidden]of [['visible',seat,false],['hidden',other,true],['restored',seat,false]]){
  const actionAt=Date.now();await target.bringToFront();
  await seat.waitForFunction(h=>document.hidden===h && document.visibilityState===(h?'hidden':'visible'),hidden,{timeout:5000,polling:50});
  result.samples.push({trial,label,actionAt,...await seat.evaluate(()=>({dateNow:Date.now(),performanceNow:performance.now(),hidden:document.hidden,visibilityState:document.visibilityState}))});
 }
 result.passed=true;
}catch(e){result.error={message:e.message,stack:e.stack};process.exitCode=1;}
finally{
 if(browser){
  for(const p of browser.contexts()[0].pages())result.timeline.push({url:p.url(),records:await p.evaluate(()=>window.visibilityRecords||[]).catch(()=>[])});
  const cdp=await browser.newBrowserCDPSession();await cdp.send('Browser.close').catch(()=>{});await browser.close();
 }else child.kill();
 await writeFile(out,JSON.stringify(result,null,2));await writeFile(out+'.browser.log',logs);
 console.log(JSON.stringify({passed:result.passed,samples:result.samples,error:result.error?.message}));
}
