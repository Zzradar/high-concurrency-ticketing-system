import { createRequire } from 'node:module';
import { createServer, request } from 'node:http';
import { spawn, execFileSync } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const [root, out, upstream = 'http://127.0.0.1:18412'] = process.argv.slice(2);
const require = createRequire(path.join(root, 'frontend/package.json'));
const { chromium } = require('@playwright/test');
await mkdir(out, { recursive: false });
const results = { sourceCommit: execFileSync('git', ['-C', root, 'rev-parse', 'HEAD'], {encoding:'utf8',windowsHide:true}).trim(), fixture: 'Exact source via Vite HTTP mode; native Edge with real backend Set-Cookie; proxy holds complete upstream response until explicit release; no identity response mocks', cases: [], passed: false };
let gate, loginRequests = 0, notifications = 0;
const proxy = createServer((req, res) => {
  if (req.url === '/auth/login') loginRequests++;
  if (req.url.startsWith('/notifications')) notifications++;
  const own = req.url === '/auth/login' && gate && !gate.claimed ? gate : null;
  if (own) own.claimed = true;
  const target = new URL(req.url, upstream);
  const forward = request(target, { method: req.method, headers: {...req.headers, host: target.host} }, incoming => {
    const chunks = []; incoming.on('data', chunk => chunks.push(chunk));
    incoming.on('end', async () => {
      if (own) { own.received(); await own.releasePromise }
      res.writeHead(incoming.statusCode, incoming.headers); res.end(Buffer.concat(chunks));
    });
  });
  forward.on('error', e => { res.writeHead(502); res.end(e.message) }); req.pipe(forward);
});
await new Promise(r => proxy.listen(18421, '127.0.0.1', r));
const vite = spawn(process.execPath, ['node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', '18420', '--strictPort'], {cwd:path.join(root,'frontend'), env:{...process.env,VITE_USE_MOCK_API:'false',VITE_API_PROXY_TARGET:'http://127.0.0.1:18421'},windowsHide:true,stdio:'pipe'});
let viteLog = ''; vite.stdout.on('data', d => viteLog += d); vite.stderr.on('data', d => viteLog += d);
let browser;
function arm() { let received, release; const response = new Promise(r => received=r); const releasePromise = new Promise(r=>release=r); gate={received,releasePromise,claimed:false};return {response,release} }
async function state(page) { return page.evaluate(async()=> {const {authState:a}=await import('/src/auth/authState.ts');return {user:a.currentUser.value,loading:a.authLoading.value,path:location.pathname} }) }
async function consistency(page, expected) {
  const value = await page.evaluate(async()=> {const a=(await import('/src/auth/authState.ts')).authState;const response=await fetch('/api/auth/me');return {front:a.currentUser.value?.username??null,status:response.status,server:response.ok?(await response.json()).username:null} });
  assert.equal(value.front,expected);assert.equal(value.server,expected);assert.equal(value.status,expected?200:401);return value;
}
try {
  await new Promise((resolve,reject)=>{const limit=setTimeout(()=>reject(new Error('Vite startup: '+viteLog)),20000);vite.stdout.on('data',()=>{if(viteLog.includes('Local:')){clearTimeout(limit);resolve()}});if(viteLog.includes('Local:')){clearTimeout(limit);resolve()}});
  browser=await chromium.launch({executablePath:path.join(process.env['ProgramFiles(x86)'],'Microsoft/Edge/Application/msedge.exe'),headless:true});
  results.browser=browser.version(); const page=await browser.newPage();
  await page.goto('http://127.0.0.1:18420/login');await page.locator('input[name=username]').waitFor();
  async function reset() { gate=null;await page.evaluate(async()=>{await (await import('/src/auth/authState.ts')).authState.logout();await (await import('/src/router.ts')).router.push('/login')});await page.locator('input[name=username]').waitFor();notifications=0 }
  async function start(username='demo',password='Ticketing123!') {await page.locator('input[name=username]').fill(username);await page.locator('input[name=password]').fill(password);await page.locator('button[type=submit]').click()}
  await reset(); let hold=arm();await start();await hold.response;
  await page.evaluate(async()=>{window.logoutPending=(await import('/src/auth/authState.ts')).authState.logout()});assert.equal((await state(page)).user,null);
  hold.release();await page.evaluate(()=>window.logoutPending);await page.waitForFunction(()=>!document.querySelector('button[type=submit]')?.disabled);
  results.cases.push({name:'pending A / logout / late success',...(await consistency(page,null)),notifications});assert.equal(notifications,0);assert.equal((await state(page)).path,'/login');
  await reset();hold=arm();const before=loginRequests;await start();await hold.response;
  await page.evaluate(async()=>{window.bPending=(await import('/src/auth/authState.ts')).authState.login('admin','Ticketing123!')});assert.equal(loginRequests,before+1,'B must not dispatch before stale cookie cleanup');
  hold.release();await page.evaluate(()=>window.bPending);results.cases.push({name:'A held / B queued / real final B cookie',...(await consistency(page,'admin'))});assert.equal((await state(page)).path,'/login');
  await reset();hold=arm();await start();await hold.response;
  await page.evaluate(async()=>{await (await import('/src/router.ts')).router.push('/events')});assert.equal((await state(page)).user,null);hold.release();
  await page.evaluate(async()=>{await (await import('/src/api/authTransport.ts')).authenticationSettled()});
  results.cases.push({name:'leave LoginView / late success / discarded cookie removed',...(await consistency(page,null)),notifications});assert.equal(notifications,0);assert.equal((await state(page)).path,'/events');
  await reset();hold=arm();await start('demo','incorrect');await hold.response;
  await page.evaluate(async()=>{window.bPending=(await import('/src/auth/authState.ts')).authState.login('admin','Ticketing123!')});hold.release();await page.evaluate(()=>window.bPending);
  assert.equal(await page.locator('[role=alert]').count(),0);results.cases.push({name:'A failure / B succeeds / no stale error',...(await consistency(page,'admin'))});
  await reset();await start();await page.waitForURL('**/events');await page.waitForFunction(async()=> (await import('/src/auth/authState.ts')).authState.currentUser.value?.username==='demo');
  assert(notifications>0);results.cases.push({name:'valid UI login / navigation / polling',...(await consistency(page,'demo')),notifications});
  await reset();results.cases.push({name:'logout consistency',...(await consistency(page,null))});await start('admin');await page.waitForURL('**/events');results.cases.push({name:'relogin B consistency',...(await consistency(page,'admin'))});
  results.passed=true;
} catch(error) {results.error=error.stack;process.exitCode=1}
finally {gate?.received(); if(browser)await browser.close();vite.kill();proxy.closeAllConnections();proxy.close();results.endedUtc=new Date().toISOString();await writeFile(path.join(out,'identity-browser.json'),JSON.stringify(results,null,2));await writeFile(path.join(out,'vite.log'),viteLog);console.log(JSON.stringify(results,null,2))}
