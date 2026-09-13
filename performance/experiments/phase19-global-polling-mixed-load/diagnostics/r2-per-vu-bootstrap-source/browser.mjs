import { createRequire } from 'node:module';
import { readFile, writeFile, mkdir, access, readdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { spawn, execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fixture } from './browser-fixture.mjs';

// root base-url fresh-output scene baseline|after diagnostic|formal
const [root, base, out, scene, revision, kind = 'formal'] = process.argv.slice(2);
assert(['events', 'panel', 'seat', 'payment', 'refund', 'submitting', 'logout'].includes(scene));
assert(['baseline', 'after'].includes(revision));
const diagnostic = kind === 'diagnostic';
const durations = diagnostic ? [10000, 3000, 15000] : [60000, 91000, 30000];
const require = createRequire(path.resolve(root, 'frontend/package.json'));
const { chromium } = require('@playwright/test');
const env = JSON.parse(await readFile(new URL('./browser-environment.json', import.meta.url), 'utf8'));
const here = path.dirname(fileURLToPath(import.meta.url));
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const protocol = Object.fromEntries(await Promise.all((await readdir(here, { withFileTypes: true })).filter(entry => entry.isFile()).map(async entry => [entry.name, hash(await readFile(path.join(here, entry.name)))])));
if (!diagnostic) assert.deepEqual(JSON.parse(await readFile(path.join(here, '../protocol-sha256.json'), 'utf8')).files, protocol, 'Formal protocol drift');
const git = (...args) => execFileSync('git', ['-C', path.resolve(root), ...args], { encoding: 'utf8', windowsHide: true }).trim();
const frontendTree = git('rev-parse', 'HEAD:frontend/src');
if (revision === 'baseline') assert.equal(frontendTree, git('rev-parse', '2c680e78d532eace9e7f28862e7efb6ef2bdf4fb:frontend/src'));
assert.equal(git('diff', 'HEAD', '--', 'frontend/src', 'frontend/public'), '', 'Build from committed production source');
const artifacts = {};
async function collectArtifacts(dir, relative = '') {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const key = relative + entry.name;
    if (entry.isDirectory()) await collectArtifacts(path.join(dir, entry.name), key + '/');
    else { const body = await readFile(path.join(dir, entry.name)); artifacts[key] = { sha256: hash(body), bytes: body.length }; }
  }
}
await collectArtifacts(path.resolve(root, 'frontend/dist'));
assert.equal(require('playwright/package.json').version, env.playwright);
const executable = process.env.PHASE19_EDGE_EXE || path.join(process.env['ProgramFiles(x86)'], 'Microsoft/Edge/Application/msedge.exe');
assert.equal(createHash('sha256').update(await readFile(executable)).digest('hex'), env.binarySha256);
try { await access(out); throw new Error('Refuse overwriting browser point'); } catch (e) { if (e.code !== 'ENOENT') throw e; }
await mkdir(out, { recursive: true });
const profile = path.join(out, 'profile');
await mkdir(profile);
const argv = env.args.map(a => a === '--user-data-dir=PROFILE' ? '--user-data-dir=' + profile : a);
const child = spawn(executable, argv, { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
let logs = '';
child.stdout.on('data', d => logs += d); child.stderr.on('data', d => logs += d);
const result = { scene, revision, diagnostic, environment: env, sourceCommit: git('rev-parse', 'HEAD'), frontendTree, artifacts, protocol,
  httpFixture: 'browser-fixture.mjs; 75ms response delay; no provider calls; decoded bytes only, wire compression unavailable',
  buildRequirement: 'VITE_USE_MOCK_API=false', startedUtc: new Date().toISOString(), requests: [], initiations: [], visibility: [], phases: [], actions: [], topology: [], errors: [], passed: false };
const f = fixture(scene), pending = new Map(), bodyReads = [], flights = new Map();
let browser, page, action = 'navigation', phase = 'setup';
const save = () => writeFile(path.join(out, 'browser.json'), JSON.stringify(result, null, 2));
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
function group(url) {
  if (url.includes('/notifications')) return 'notifications';
  if (url.includes('/seat-availability')) return 'availability';
  if (url.includes('/payment-attempts/')) return 'payment';
  if (url.includes('/checkout-sessions/')) return 'checkout';
  if (url.includes('/orders/')) return 'order';
  return 'other';
}
async function doAction(name, fn) {
  action = name; result.actions.push({ name, epochMs: Date.now() });
  await fn(); action = 'periodic-or-lifecycle';
}
try {
  let endpoint;
  for (let i = 0; i < 100; i++) {
    try { endpoint = 'http://127.0.0.1:' + (await readFile(path.join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; break; } catch {}
    await delay(100);
  }
  assert(endpoint); browser = await chromium.connectOverCDP(endpoint, { noDefaults: true });
  assert.equal(browser.contexts().length, 1);
  const context = browser.contexts()[0];
  page = context.pages()[0]; const neutral = await context.newPage();
  assert.equal(context.pages().length, 2);
  await context.exposeBinding('phase19Record', ({ page: source }, item) => {
    if (source !== page) return;
    if (item.type === 'request') result.initiations.push(item); else result.visibility.push(item);
  });
  await context.addInitScript(() => {
    const record = item => { void window.phase19Record({ ...item, hidden: document.hidden, visibilityState: document.visibilityState, epochMs: Date.now(), monotonicMs: performance.now() }).catch(() => {}); };
    for (const type of ['visibilitychange', 'focus', 'blur']) window.addEventListener(type, event => record({ type, trusted: event.isTrusted }));
    record({ type: 'init' });
    // Observe actual send-time visibility; do not replace visibility or timer APIs.
    const open = XMLHttpRequest.prototype.open, send = XMLHttpRequest.prototype.send;
    const identity = new WeakMap();
    XMLHttpRequest.prototype.open = function(method, url, ...rest) { identity.set(this, { method, path: new URL(url, location.href).pathname }); return open.call(this, method, url, ...rest); };
    XMLHttpRequest.prototype.send = function(...args) { record({ type: 'request', ...identity.get(this) }); return send.apply(this, args); };
  });
  page.on('pageerror', error => result.errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error' || message.text().includes('[Vue warn]')) result.errors.push(message.text()); });
  await page.route(base + '/api/**', async route => {
    const [status, body] = f.response(route.request().method(), new URL(route.request().url()));
    if (status === 404) result.errors.push(body.message);
    await delay(75);
    await route.fulfill({ status, contentType: 'application/json', headers: { 'x-phase19-controlled-fixture': 'v1' }, body: JSON.stringify(body) });
  });
  page.on('request', request => {
    if (!request.url().startsWith(base + '/api/')) return;
    const endpoint = new URL(request.url()).pathname.replace(/^\/api/, '');
    const business = group(endpoint), method = request.method();
    const activeKey = method === 'GET' ? business : 'write';
    const active = (flights.get(activeKey) || 0) + 1; flights.set(activeKey, active);
    const item = { ordinal: result.requests.length, endpoint, method, business, phase, action, startEpochMs: Date.now(), startMonotonicNs: process.hrtime.bigint().toString(), inflightAtStart: active };
    result.requests.push(item); pending.set(request, item);
  });
  page.on('response', response => {
    const item = pending.get(response.request()); if (!item) return;
    item.status = response.status();
    bodyReads.push(response.body().then(body => {
      item.decodedBodyBytes = body.length;
      const value = JSON.parse(body);
      item.terminal = item.business === 'payment' ? ['SUCCEEDED', 'FAILED'].includes(value.status)
        : item.business === 'checkout' ? ['RESERVED', 'ABANDONED'].includes(value.status || value.checkoutSession?.status)
          : item.business === 'order' && scene === 'refund' ? ['SUCCEEDED', 'FAILED'].includes(value.buyerRefund?.status)
            : item.business === 'order' && scene === 'payment' ? value.status !== 'PENDING_PAYMENT' : false;
    }).catch(error => { item.bodyError = error.message; }));
  });
  const finish = (request, error) => {
    const item = pending.get(request); if (!item) return;
    item.endEpochMs = Date.now(); item.durationMs = Number(process.hrtime.bigint() - BigInt(item.startMonotonicNs)) / 1e6;
    if (error) item.error = error;
    const key = item.method === 'GET' ? item.business : 'write'; flights.set(key, flights.get(key) - 1); pending.delete(request);
  };
  page.on('requestfinished', request => finish(request));
  page.on('requestfailed', request => finish(request, request.failure()?.errorText));
  await neutral.goto('data:text/html,<title>Phase19 neutral</title><h1>Neutral tab</h1>');
  await page.bringToFront();
  await page.goto(base + (['payment', 'refund'].includes(scene) ? '/orders/phase19-browser-order' : ['seat', 'submitting'].includes(scene) ? '/sessions/phase19-browser-session/seats' : '/events'));
  await page.getByRole('button', { name: '通知中心', exact: true }).waitFor();
  if (scene === 'logout') await doAction('logout', async () => {
    await page.getByRole('button', { name: '账户菜单', exact: true }).click();
    await page.getByRole('button', { name: '退出登录', exact: true }).click();
    await page.waitForURL('**/login'); result.loggedOutEpochMs = Date.now();
  });
  for (const [name, target] of [['subject', page], ['neutral', neutral]]) {
    const cdp = await context.newCDPSession(target); const { targetInfo } = await cdp.send('Target.getTargetInfo');
    result.topology.push({ name, ...await cdp.send('Browser.getWindowForTarget', { targetId: targetInfo.targetId }) });
    if (name === 'subject') result.browser = await cdp.send('Browser.getVersion'); await cdp.detach();
  }
  assert.equal(result.topology[0].windowId, result.topology[1].windowId); assert.equal(result.browser.product, env.product);
  for (const [index, name] of ['visible', 'hidden', 'restored'].entries()) {
    await doAction('bringToFront-' + name, () => (name === 'hidden' ? neutral : page).bringToFront());
    await page.waitForFunction(hidden => document.hidden === hidden, name === 'hidden', { timeout: 5000 });
    phase = name;
    const began = Date.now(); result.phases.push({ name, began, activationEpochMs: result.actions.at(-1).epochMs, durationMs: durations[index], hidden: await page.evaluate(() => document.hidden) });
    const actions = [];
    if (name === 'visible' && scene === 'panel') actions.push([500, 'open-panel', () => page.getByRole('button', { name: '通知中心', exact: true }).click()], [durations[index] / 2, 'close-panel', () => page.getByRole('button', { name: '通知中心', exact: true }).click()]);
    if (name === 'visible' && scene === 'payment') actions.push([durations[index] - 5000, 'pay', () => page.locator('.order-pay-button').click()]);
    if (name === 'visible' && scene === 'refund') actions.push([durations[index] - 5000, 'refund', async () => { await page.getByRole('button', { name: '申请全额退款', exact: true }).click(); await page.getByRole('button', { name: '确认退款', exact: true }).click(); }]);
    if (name === 'visible' && scene === 'submitting') actions.push([durations[index] - 5000, 'resume-checkout', () => page.getByRole('button', { name: '继续处理', exact: true }).click()]);
    if (name === 'restored' && ['payment', 'refund', 'submitting'].includes(scene)) actions.push([10000, 'terminal-fixture-and-manual-refresh', async () => {
      f.state.terminal = true; result.terminalEpochMs = Date.now();
      if (scene === 'payment') await page.getByRole('button', { name: '刷新状态', exact: true }).click();
      if (scene === 'submitting') await page.getByRole('button', { name: '继续原确认', exact: true }).click();
    }]);
    for (const [offset, label, fn] of actions) { await delay(Math.max(0, began + offset - Date.now())); await doAction(label, fn); }
    await delay(Math.max(0, began + durations[index] - Date.now())); await save();
    console.log(JSON.stringify({ scene, phase, requests: result.requests.length, errors: result.errors.length }));
  }
  await Promise.all(bodyReads);
  const reads = result.requests.filter(r => r.method === 'GET' && r.business !== 'other');
  const hidden = result.phases.find(p => p.name === 'hidden'), restored = result.phases.find(p => p.name === 'restored');
  const restoredCounts = Object.fromEntries(['notifications', 'availability', 'payment', 'checkout', 'order'].map(business => [business, reads.filter(r => r.business === business && r.startEpochMs >= restored.activationEpochMs && r.startEpochMs < restored.activationEpochMs + 500).length]));
  const terminalBusiness = { payment: 'payment', refund: 'order', submitting: 'checkout' }[scene];
  const terminalRead = result.requests.find(r => r.terminal && (r.business === terminalBusiness || scene === 'payment' && r.business === 'order') && r.startEpochMs >= result.terminalEpochMs);
  result.checks = { hiddenNewReads: result.initiations.filter(r => r.epochMs >= result.phases[0].began && r.hidden && r.method === 'GET' && group(r.path) !== 'other').length,
    hiddenInflightFromBefore: reads.filter(r => r.startEpochMs < hidden.began && r.endEpochMs >= hidden.began).length,
    maxInflight: Object.fromEntries(['notifications', 'availability', 'payment', 'checkout', 'order'].map(business => [business, Math.max(0, ...reads.filter(r => r.business === business).map(r => r.inflightAtStart))])), restoredImmediateCounts: restoredCounts,
    logoutNewReads: result.loggedOutEpochMs ? reads.filter(r => r.startEpochMs >= result.loggedOutEpochMs).length : 0,
    terminalObserved: !terminalBusiness || Boolean(terminalRead),
    readsAfterTerminalSettled: terminalRead ? reads.filter(r => r.business === terminalBusiness && r.startEpochMs > terminalRead.endEpochMs + 1000).length : null,
    restorationFirstReadMs: Object.fromEntries(['notifications', 'availability', 'payment', 'checkout', 'order'].map(business => {
      const first = reads.find(r => r.business === business && r.startEpochMs >= restored.activationEpochMs);
      return [business, first ? first.startEpochMs - restored.activationEpochMs : null];
    })) };
  result.passed = result.errors.length === 0 && result.requests.length > 0 && result.requests.every(r => r.status < 400 && !r.error && !r.bodyError);
  result.passed &&= result.checks.terminalObserved && (result.checks.readsAfterTerminalSettled ?? 0) === 0;
  if (revision === 'after') result.passed &&= result.checks.hiddenNewReads === 0 && result.checks.logoutNewReads === 0 && Object.values(result.checks.maxInflight).every(n => n <= 1) && Object.values(restoredCounts).every(n => n <= 1);
} catch (error) {
  result.error = { message: error.message, stack: error.stack?.replaceAll(root, '<PHASE19_WORKTREE>').replaceAll(out, '<PRIVATE_BROWSER_OUTPUT>') };
  if (page) result.diagnosticPageText = await page.locator('body').innerText({ timeout: 2000 }).catch(() => 'unavailable');
}
finally {
  if (browser) { const cdp = await browser.newBrowserCDPSession(); await cdp.send('Browser.close').catch(() => {}); await browser.close(); } else child.kill();
  result.endedUtc = new Date().toISOString(); result.inflightAtClose = pending.size;
  await save(); await writeFile(path.join(out, 'browser.log'), logs.replaceAll(profile, '<PRIVATE_BROWSER_PROFILE>'));
  console.log(JSON.stringify({ passed: result.passed, scene, requests: result.requests.length, error: result.error?.message }));
  if (!result.passed) process.exitCode = 1;
}
