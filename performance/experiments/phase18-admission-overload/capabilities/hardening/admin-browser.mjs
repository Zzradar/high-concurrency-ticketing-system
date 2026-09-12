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
const result={purpose:'Admin policy native UI capability; not OFF A/B',environment:env,checks:[],responses:[],passed:false};
try{
 let endpoint;for(let i=0;i<100;i++){try{endpoint='http://127.0.0.1:'+(await readFile(path.join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0];break}catch{}await new Promise(r=>setTimeout(r,100))}
 browser=await chromium.connectOverCDP(endpoint,{noDefaults:true});assert.equal(browser.contexts().length,1);const page=browser.contexts()[0].pages()[0];await page.bringToFront();
 await page.goto('http://127.0.0.1:18183/admin/events/'+business.eventId);await page.waitForURL('**/login?**');
 let password=(await run('python',['-c',"import sys;sys.path.insert(0,'backend/tests');from auth_test_support import TEST_PASSWORD;sys.stdout.write(TEST_PASSWORD)"],{cwd:root,env:processEnv})).stdout;
 await page.getByLabel('用户名').fill('admin');await page.getByLabel('密码',{exact:true}).fill(password);password='';await page.getByRole('button',{name:'登录',exact:true}).click();
 await page.waitForURL('**/admin/events/'+business.eventId);await page.getByLabel('准入模式').waitFor();
 async function save(mode){
  await page.getByLabel('准入模式').selectOption(mode);
  const response=page.waitForResponse(r=>r.url().endsWith('/admission-policy')&&r.request().method()==='PUT');
  await page.getByRole('button',{name:'保存准入策略',exact:true}).click();const r=await response;const data=await r.json();result.responses.push({at:Date.now(),status:r.status(),mode:data.mode,version:data.policyVersion,generation:data.queueGeneration});assert.equal(r.status(),200);await page.getByText('准入策略已保存',{exact:true}).waitFor();return data;
 }
 const shadow=await save('OBSERVE');const formal=await save('PAUSED');assert.notEqual(shadow.queueGeneration,formal.queueGeneration);
 const enforced=await save('ENFORCED');assert.equal(enforced.queueGeneration,formal.queueGeneration);await save('OFF');const fresh=await save('ENFORCED');assert.notEqual(fresh.queueGeneration,formal.queueGeneration);
 result.checks.push('Admin UI persists modes and preserves/rotates formal/shadow generation correctly');
 await fixture('mode',business.eventId,'PAUSED');await page.getByLabel('准入模式').selectOption('OBSERVE');await page.getByRole('button',{name:'保存准入策略',exact:true}).click();await page.getByText('策略已被其他管理员修改，请重新加载后再保存',{exact:true}).waitFor();
 assert(await page.getByRole('button',{name:'保存准入策略',exact:true}).isDisabled());await page.getByRole('button',{name:'重新加载准入策略',exact:true}).click();await page.waitForFunction(()=>document.querySelector('[aria-label="准入模式"]')?.value==='PAUSED');
 result.checks.push('OCC conflict disables stale save and explicit reload restores current version');await page.screenshot({path:out+'.png'});result.passed=true;
}catch(e){result.error={message:e.message,stack:e.stack};process.exitCode=1}
finally{if(browser){const cdp=await browser.newBrowserCDPSession();await cdp.send('Browser.close').catch(()=>{});await browser.close()}else child.kill();await writeFile(out,JSON.stringify(result,null,2));await writeFile(out+'.browser.log',logs)}
console.log(JSON.stringify({passed:result.passed,checks:result.checks,error:result.error?.message}));
