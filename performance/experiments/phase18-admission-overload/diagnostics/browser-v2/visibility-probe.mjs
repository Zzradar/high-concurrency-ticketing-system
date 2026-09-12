import { createRequire } from 'node:module';
import { writeFile, readFile, mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import path from 'node:path';
import assert from 'node:assert/strict';
const [root, out, profile, channel='msedge'] = process.argv.slice(2);
const require = createRequire(path.join(root, 'frontend/package.json'));
const { chromium } = require('@playwright/test');
const result = { playwright: require('playwright/package.json').version, channel, headless:false,
 connection:'launchPersistentContext (Playwright pipe); CDP only for topology read and removal of focus emulation',
 profile, launchOptions:{...(channel==='msedge'?{channel}:{}),headless:false}, timeline:[], topology:[], samples:[], passed:false };
await mkdir(path.dirname(out), {recursive:true});
let context;
try {
 context = await chromium.launchPersistentContext(profile,result.launchOptions);
 await context.addInitScript(() => {
   window.visibilityRecords=[];
   const record=type=>window.visibilityRecords.push({type,hidden:document.hidden,visibilityState:document.visibilityState,
     dateNow:Date.now(),performanceNow:performance.now(),entries:performance.getEntriesByType('visibility-state').map(x=>x.toJSON())});
   for(const type of ['visibilitychange','focus','blur'])window.addEventListener(type,()=>record(type));
   record('init');
 });
 assert.equal(context.browser().contexts().length,1);
 const seat=context.pages()[0] || await context.newPage();
 const other=await context.newPage();
 assert.equal(context.pages().length,2);
 await seat.goto('data:text/html,<title>Seat visibility probe</title><h1>Seat probe</h1>');
 await other.goto('data:text/html,<title>Neutral visibility probe</title><h1>Neutral</h1>');
 const sessions=[];
 for(const [name,page] of [['seat',seat],['other',other]]) {
  const cdp=await context.newCDPSession(page);sessions.push(cdp);
  const {targetInfo}=await cdp.send('Target.getTargetInfo');
  const window=await cdp.send('Browser.getWindowForTarget',{targetId:targetInfo.targetId});
  result.topology.push({name,targetId:targetInfo.targetId,browserContextId:targetInfo.browserContextId,...window});
 }
 assert.equal(result.topology[0].windowId,result.topology[1].windowId,'Pages must be tabs in one real window');
 const cdp=sessions[0];
 result.browser=await cdp.send('Browser.getVersion');
 result.commandLine=await cdp.send('Browser.getBrowserCommandLine').catch(e=>({unavailable:e.message,source:'complete pw:browser launch log'}));
 const exe=channel==='msedge'?'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe':chromium.executablePath();result.executablePath=exe;
 result.binarySha256=createHash('sha256').update(await readFile(exe)).digest('hex');
 async function sample(label) {
  const snapshot=await seat.evaluate(()=>({hidden:document.hidden,visibilityState:document.visibilityState,dateNow:Date.now(),performanceNow:performance.now()}));
  result.samples.push({label,...snapshot});return snapshot;
 }
 await seat.bringToFront();await seat.waitForTimeout(200);await sample('default-seat-front');
 await other.bringToFront();await seat.waitForTimeout(1000);await sample('default-other-front');
 // Playwright enables this by default. Disable the override once, then use real tab activation only.
 for(const cdp of sessions)await cdp.send('Emulation.setFocusEmulationEnabled',{enabled:false});
 result.focusOverrideRemovedAt=Date.now();
 for(let trial=0;trial<3;trial++) {
  await seat.bringToFront();await seat.waitForFunction(()=>!document.hidden && document.visibilityState==='visible',null,{timeout:5000});
  await sample(`trial-${trial}-seat-front`);
  await other.bringToFront();await seat.waitForFunction(()=>document.hidden && document.visibilityState==='hidden',null,{timeout:5000,polling:50});
  await sample(`trial-${trial}-other-front`);
  await seat.bringToFront();await seat.waitForFunction(()=>!document.hidden && document.visibilityState==='visible',null,{timeout:5000});
  await sample(`trial-${trial}-restored`);
 }
 result.passed=true;
} catch(e) { result.error={message:e.message,stack:e.stack};process.exitCode=1; }
finally {
 if(context) {
  for(const page of context.pages())result.timeline.push({url:page.url(),records:await page.evaluate(()=>window.visibilityRecords || []).catch(()=>[])});
  await context.close();
 }
 await writeFile(out,JSON.stringify(result,null,2));
 console.log(JSON.stringify({passed:result.passed,samples:result.samples,error:result.error?.message}));
}
