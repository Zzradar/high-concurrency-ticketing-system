import {createRequire} from 'node:module';
import {readFile,writeFile,mkdir,access} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {spawn,execFile} from 'node:child_process';
import {promisify} from 'node:util';
import path from 'node:path';
import assert from 'node:assert/strict';
const [root,out,profile]=process.argv.slice(2);
const require=createRequire(path.join(root,'frontend/package.json'));
const {chromium}=require('@playwright/test');const run=promisify(execFile);
const env=JSON.parse(await readFile(new URL('../../protocol/browser-environment.json',import.meta.url),'utf8'));
assert.equal(require('playwright/package.json').version,env.playwright);
assert.equal(createHash('sha256').update(await readFile(env.executable)).digest('hex'),env.binarySha256);
const processEnv={...process.env,PYTHONUTF8:'1',PHASE18_BASE_URL:'http://127.0.0.1:18184',PHASE18_POSTGRES_CONTAINER:'phase18-policy-http-postgres',PHASE18_REDIS_CONTAINER:'phase18-policy-http-redis'};
async function fixture(...args){return JSON.parse((await run('python',['backend/tests/phase18_browser_fixture.py',...args],{cwd:root,env:processEnv})).stdout)}
const business=await fixture('create');
try{await access(profile);throw new Error('Refuse reused profile')}catch(e){if(e.code!=='ENOENT')throw e}
await mkdir(profile,{recursive:true});
const args=env.args.map(x=>x==='--user-data-dir=PROFILE'?'--user-data-dir='+profile:x);
const child=spawn(env.executable,args,{windowsHide:true,stdio:['ignore','pipe','pipe']});let browser,logs='';
child.stdout.on('data',d=>logs+=d);child.stderr.on('data',d=>logs+=d);
const result={purpose:'Waiting Room capability only, not OFF A/B',environment:env,business,requests:[],visibility:[],checks:[],maxAvailabilityInflight:0,passed:false};
const pending=new Map();let availability=0;
try{
 let endpoint;for(let i=0;i<100;i++){try{endpoint='http://127.0.0.1:'+(await readFile(path.join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0];break}catch{}await new Promise(r=>setTimeout(r,100))}
 browser=await chromium.connectOverCDP(endpoint,{noDefaults:true});assert.equal(browser.contexts().length,1);const context=browser.contexts()[0];
 await context.addInitScript(()=>{window.nativeVisibility=[];for(const type of ['visibilitychange','focus','blur'])window.addEventListener(type,e=>window.nativeVisibility.push({type,trusted:e.isTrusted,hidden:document.hidden,state:document.visibilityState,at:Date.now()}))});
 const seat=context.pages()[0],other=await context.newPage();assert.equal(context.pages().length,2);
 function record(page){
  page.on('request',r=>{if(!/\/(admission|seat-availability)(\?|\/|$)/.test(r.url()))return;const row={page:page===seat?'seat':'other',url:r.url(),method:r.method(),start:Date.now()};result.requests.push(row);pending.set(r,row);if(r.url().includes('seat-availability'))result.maxAvailabilityInflight=Math.max(result.maxAvailabilityInflight,++availability)});
  page.on('response',r=>{const row=pending.get(r.request());if(row)row.status=r.status()});
  const finish=(r,error)=>{const row=pending.get(r);if(!row)return;row.end=Date.now();if(error)row.error=error;if(r.url().includes('seat-availability'))availability--;pending.delete(r)};
  page.on('requestfinished',r=>finish(r));page.on('requestfailed',r=>finish(r,r.failure()?.errorText));
 }
 record(seat);record(other);
 await other.goto('data:text/html,<h1>Neutral</h1>');await seat.bringToFront();
 await seat.goto('http://127.0.0.1:18183/sessions/'+business.sessionId+'/seats');
 await seat.waitForURL('**/login?**');assert.equal(result.requests.filter(r=>r.url.includes('seat-availability')).length,0);
 assert(new URL(seat.url()).searchParams.get('redirect').includes('/waiting-room?sessionId='+business.sessionId));
 // Existing explicit demo fixture password is passed through private subprocess memory only.
 let password=(await run('python',['-c',"import sys;sys.path.insert(0,'backend/tests');from auth_test_support import TEST_PASSWORD;sys.stdout.write(TEST_PASSWORD)"],{cwd:root,env:processEnv})).stdout;
 await seat.getByLabel('用户名').fill('demo');await seat.getByLabel('密码',{exact:true}).fill(password);password='';await seat.getByRole('button',{name:'登录',exact:true}).click();
 await seat.waitForURL('**/waiting-room?**');await seat.getByRole('button',{name:'加入队列',exact:true}).waitFor();
 assert.equal(result.requests.filter(r=>r.method==='POST').length,0);await seat.getByRole('button',{name:'加入队列',exact:true}).click();
 await seat.getByText('暂缓放行，你的排队位置会保留。',{exact:true}).waitFor();result.checks.push('direct URL metadata -> login -> explicit join -> PAUSED');
 const room=seat.url();await other.goto(room);await other.bringToFront();await other.getByText('前方约 0 人',{exact:true}).waitFor();
 const counts=await fixture('counts',business.eventId);assert.equal(counts.prequeue+counts.waiting+counts.active,1);result.checks.push('two real tabs share one position');
 await other.goto('data:text/html,<h1>Neutral</h1>');await seat.waitForFunction(()=>document.hidden===true);
 const hiddenAt=Date.now();await seat.waitForTimeout(35000);assert.equal(result.requests.filter(r=>r.start>hiddenAt+1000).length,0);
 await seat.bringToFront();await seat.getByRole('button',{name:'加入队列',exact:true}).waitFor();result.checks.push('real hidden stops status and heartbeat; presence expires');
 await seat.getByRole('button',{name:'加入队列',exact:true}).click();await seat.getByText('暂缓放行，你的排队位置会保留。',{exact:true}).waitFor();
 await run('docker',['stop','phase18-policy-http-redis']);
 try{await seat.getByText('当前访问较多，请稍候，我们会自动重试。',{exact:true}).waitFor({timeout:15000})}
 finally{await run('docker',['start','phase18-policy-http-redis'])}
 await seat.getByText('当前访问较多，请稍候，我们会自动重试。',{exact:true}).waitFor({state:'hidden',timeout:20000});result.checks.push('real Redis outage returns recoverable HTTP 503 UI');
 await fixture('limit',business.eventId);await seat.getByText('操作较频繁，请稍候再试。',{exact:true}).waitFor({timeout:10000});result.checks.push('real HTTP 429 consumer message');
 await other.bringToFront();await seat.waitForFunction(()=>document.hidden===true);await fixture('reset',business.eventId);
 await seat.bringToFront();await seat.getByRole('button',{name:'重新加入队列',exact:true}).waitFor({timeout:15000});
 await seat.getByRole('button',{name:'重新加入队列',exact:true}).click();await seat.getByText('暂缓放行，你的排队位置会保留。',{exact:true}).waitFor();result.checks.push('old generation requires explicit reset join');
 await seat.screenshot({path:out+'.png'});
 await fixture('mode',business.eventId,'ENFORCED');await seat.waitForURL('**/sessions/'+business.sessionId+'/seats',{timeout:20000});await seat.locator('.seat-grid').waitFor();
 const entered=Date.now();await seat.waitForTimeout(6500);
 assert.equal(result.requests.filter(r=>r.start>=entered&&r.url.includes('/admission')&&r.method==='GET').length,0);
 assert(result.requests.some(r=>r.start>=entered&&r.url.includes('/heartbeat')));assert.equal(result.maxAvailabilityInflight,1);result.checks.push('ADMITTED replaces waiting polls with seat polling plus independent heartbeat');
 await seat.getByRole('button',{name:'返回选择场次',exact:true}).click();await seat.goBack();await seat.locator('.seat-grid').waitFor();result.checks.push('browser back restores admitted seat route');
 await seat.getByRole('button',{name:'账户菜单',exact:true}).click();await seat.getByRole('button',{name:'退出登录',exact:true}).click();await seat.waitForURL(/\/login(?:\?|$)/,{timeout:10000});const logoutAt=Date.now();await seat.waitForTimeout(6000);
 assert.equal(result.requests.filter(r=>r.start>logoutAt+1000&&r.url.includes('/heartbeat')).length,0);result.checks.push('logout stops qualification heartbeat');result.passed=true;
}catch(e){result.error={message:e.message,stack:e.stack};process.exitCode=1}
finally{
 if(browser){for(const page of browser.contexts()[0].pages())result.visibility.push({url:page.url(),records:await page.evaluate(()=>window.nativeVisibility??[]).catch(()=>[])});const cdp=await browser.newBrowserCDPSession();await cdp.send('Browser.close').catch(()=>{});await browser.close()}else child.kill();
 await writeFile(out,JSON.stringify(result,null,2));await writeFile(out+'.browser.log',logs);console.log(JSON.stringify({passed:result.passed,checks:result.checks,error:result.error?.message,maxAvailabilityInflight:result.maxAvailabilityInflight}));
}
