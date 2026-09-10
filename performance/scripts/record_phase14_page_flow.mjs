#!/usr/bin/env node
// Browser evidence only: records the real UI request graph; it is not a load generator.
import {createRequire} from 'node:module';
import {execFileSync} from 'node:child_process';
import {readFile, mkdir} from 'node:fs/promises';
import {createServer} from '../../frontend/node_modules/vite/dist/node/index.js';
import vue from '../../frontend/node_modules/@vitejs/plugin-vue/dist/index.mjs';
import {writeFile} from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import {fileURLToPath} from 'node:url';

const require = createRequire(import.meta.url);
const {chromium} = require('../../e2e/node_modules/@playwright/test');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const output = path.resolve(process.argv[2] || path.join(root, 'performance/results/phase14-browser-'+Date.now()+'/browser.json'));
const baseUrl = 'http://127.0.0.1:15174';
const evidenceRoot=path.dirname(output);
await mkdir(evidenceRoot,{recursive:true});
const targets=JSON.parse(await readFile(path.join(root,'performance/baseline/phase14-targets.json'),'utf8'));
const identities=JSON.parse(await readFile(path.join(root,`performance/generated/phase14/smoke-v${targets.version}/sessions.json`),'utf8'));
const {validateColdStartup}=await import('./phase14_browser_contract.mjs');
const identity=identities[0];
const sessionId = 'perf-session-001-001';
const git = args => execFileSync('git',args,{cwd:root,encoding:'utf8'}).trim();
const sourceTree=git(['rev-parse','HEAD:frontend']);
if(git(['status','--short','--','frontend']))throw new Error('frontend is not clean before calibration');

async function startFrontend() {
  // Inspect the current source without loading any .env or changing frontend files.
  for(const key of Object.keys(process.env))if(key.startsWith('VITE_'))delete process.env[key];
  const server=await createServer({root:path.join(root,'frontend'),configFile:false,envDir:false,
    cacheDir:path.join(evidenceRoot,'vite-cache'),plugins:[vue()],
    define:{'import.meta.env.VITE_USE_MOCK_API':JSON.stringify('false')},
    server:{host:'127.0.0.1',port:15174,strictPort:true,proxy:{'/api':{
      target:'http://127.0.0.1:18414',changeOrigin:true,rewrite:p=>p.replace(/^\/api/,''),
      configure:proxy=>proxy.on('proxyReq',request=>request.setHeader('Origin','http://performance.local'))
    }}}});
  await server.listen();return server;
}

async function waitForFrontend() {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const response = await fetch(baseUrl + '/events');
      if (response.ok) return;
    } catch (_) { /* retry */ }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error('frontend did not become ready');
}

const blockedHosts=new Set();
async function localContext(browser) {
  const context=await browser.newContext();
  await context.route('**/*',route=>{
    const host=new URL(route.request().url()).hostname;
    if(host==='127.0.0.1' || host==='localhost')return route.continue();
    blockedHosts.add(host);return route.abort();
  });
  return context;
}

function capture(page) {
  const requests = [],pending=[],records=new Map(),start=performance.now();
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) {
      const row={sequence:requests.length+1,method:request.method(),path:url.pathname.slice(4),
        query:Object.fromEntries(url.searchParams),startedAfterMs:performance.now()-start};
      requests.push(row);records.set(request,row);
      pending.push(request.allHeaders().then(headers=>{
        row.hasSessionCookie=/(?:^|;\s*)ticketing_session=/.test(headers.cookie||'');
        row.hasCsrfHeader=Boolean(headers['x-csrf-token']);
      }));
    }
  });
  page.on('response',response=>{const row=records.get(response.request());if(row){row.responseAfterMs=performance.now()-start;row.status=response.status();}});
  page.on('requestfinished',request=>{
    const row=records.get(request);if(row)row.finishedAfterMs=performance.now()-start;
  });
  requests.settled=()=>Promise.all(pending);
  return requests;
}

function summarize(requests) {
  const matching = suffix => requests.filter(item => item.path.endsWith(suffix));
  return {
    requestCount: requests.length,
    sessionReads: matching(`/sessions/${sessionId}`).length,
    eventReads: matching('/events/perf-event-001').length,
    layoutReads: matching('/seat-layout').length,
    availabilityReads: matching('/seat-availability').length,
    legacySeatReads: requests.filter(item => item.method === 'GET' &&
      item.path === `/sessions/${sessionId}/seats`).length,
    checkoutCreates: requests.filter(item => item.method === 'POST' && item.path === '/checkout-sessions').length,
    checkoutSeatUpdates: requests.filter(item => item.method === 'PUT' && item.path.endsWith('/seats')).length,
    requests: requests.map(item => ({...item, query: {...item.query}})),
  };
}

async function waitForCount(requests, predicate, expected) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    if (requests.filter(predicate).length >= expected) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`request count did not reach ${expected}`);
}

const frontend = await startFrontend();
let browser;
try {
  await waitForFrontend();
  browser = await chromium.launch({headless: true});

  const anonymousContext = await localContext(browser);
  const anonymousPage = await anonymousContext.newPage();
  const anonymousRequests = capture(anonymousPage);
  await anonymousPage.goto(`${baseUrl}/sessions/${sessionId}/seats`);
  await anonymousPage.getByRole('region', {name: '场次座位状态与区域筛选'}).waitFor();
  await waitForCount(anonymousRequests, item => item.path.endsWith('/seat-availability'), 1);
  await anonymousRequests.settled();
  const anonymousInitial = summarize(anonymousRequests);
  if (anonymousInitial.sessionReads !== 1 || anonymousInitial.eventReads !== 1 ||
      anonymousInitial.layoutReads !== 1 || anonymousInitial.availabilityReads !== 1 ||
      anonymousInitial.legacySeatReads !== 0) throw new Error('anonymous request graph mismatch');
  await anonymousContext.close();

  const context = await localContext(browser);
  const page = await context.newPage();
  await context.addCookies([
    {name:'ticketing_session',value:identity.sessionToken,domain:'127.0.0.1',path:'/',httpOnly:true,sameSite:'Lax'},
    {name:'ticketing_csrf',value:identity.csrfToken,domain:'127.0.0.1',path:'/',sameSite:'Lax'}
  ]);
  const requests = capture(page);
  await page.goto(`${baseUrl}/sessions/${sessionId}/seats`);
  await page.getByRole('region', {name: '场次座位状态与区域筛选'}).waitFor();
  await waitForCount(requests, item => item.path.endsWith('/seat-availability'), 1);
  await requests.settled();
  await page.waitForLoadState('networkidle');
  const authenticatedInitial = summarize(requests);
  const startupContract=validateColdStartup(authenticatedInitial);
  await writeFile(path.join(evidenceRoot,'cold-startup.json'),JSON.stringify({authenticatedInitial,startupContract},null,2)+'\n');
  if(!startupContract.passed)throw new Error('cold startup mismatch: '+JSON.stringify(startupContract));

  await page.getByRole('button', {name: /^R001-005，可选，/}).click();
  await page.getByRole('button', {name: '移除座位 R001-005'}).waitFor();
  await waitForCount(requests, item => item.path.endsWith('/seat-availability'), 2);
  await requests.settled();
  const afterFirstSelection = summarize(requests);
  const locator = await page.evaluate(userId => JSON.parse(
    sessionStorage.getItem('ticketing.checkout.'+userId) || '{}'),identity.userId);
  const ownedReads = requests.filter(item => item.path.endsWith('/seat-availability') &&
    item.query.checkoutSessionId === locator.checkoutSessionId);
  if (!locator.checkoutSessionId || ownedReads.length < 1 || afterFirstSelection.layoutReads !== 1 ||
      afterFirstSelection.checkoutCreates !== 1) throw new Error('first selection request graph mismatch');

  await page.getByRole('button', {name: /^R001-006，可选，/}).click();
  await page.getByRole('button', {name: '移除座位 R001-006'}).waitFor();
  await waitForCount(requests, item => item.path.endsWith('/seat-availability'), 3);
  await requests.settled();
  const afterSecondSelection = summarize(requests);
  const mutations=requests.filter(x=>x.method==='POST'||x.method==='PUT');
  if(mutations.some(x=>!x.hasSessionCookie||!x.hasCsrfHeader))throw new Error('mutation credential/header calibration failed');
  if(git(['status','--short','--','frontend']))throw new Error('frontend changed during calibration');
  const evidence = {startupContract,targetsVersion:targets.version,frontendTree:sourceTree,recordedAt: new Date().toISOString(), sessionId, phase14:true, sourceUnmodified:true, envFilesLoaded:false, backend:'http://127.0.0.1:18414',
    anonymousInitial, authenticatedInitial, afterFirstSelection, afterSecondSelection, blockedExternalHosts:[...blockedHosts]};
  await writeFile(output, JSON.stringify(evidence, null, 2) + '\n');
  if (afterSecondSelection.layoutReads !== 1 || afterSecondSelection.availabilityReads !== 3 ||
      afterSecondSelection.checkoutSeatUpdates !== 1 || afterSecondSelection.legacySeatReads !== 0)
    throw new Error('second selection request graph mismatch: ' + JSON.stringify(afterSecondSelection));
  await context.close();
  console.log(`[PASS] real page flow recorded: ${output}`);
} finally {
  if (browser) await browser.close();
  await frontend.close();
}
