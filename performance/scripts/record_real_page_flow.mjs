#!/usr/bin/env node
// Browser evidence only: records the real UI request graph; it is not a load generator.
import {createRequire} from 'node:module';
import {spawn} from 'node:child_process';
import {writeFile} from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import {fileURLToPath} from 'node:url';

const require = createRequire(import.meta.url);
const {chromium} = require('../../e2e/node_modules/@playwright/test');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const output = path.resolve(process.argv[2] || path.join(root, 'performance/results/real-page-flow-browser.json'));
const baseUrl = 'http://127.0.0.1:5173';
const sessionId = 'perf-session-001-001';

function startFrontend() {
  const executable = process.platform === 'win32' ? 'cmd.exe' : 'npm';
  const childArgs = process.platform === 'win32'
    ? ['/d', '/s', '/c', 'npm run dev -- --host 127.0.0.1 --port 5173']
    : ['run', 'dev', '--', '--host', '127.0.0.1', '--port', '5173'];
  return spawn(executable, childArgs, {
    cwd: path.join(root, 'frontend'),
    env: {...process.env, VITE_USE_MOCK_API: 'false', VITE_API_PROXY_TARGET: 'http://127.0.0.1:18080'},
    shell: false, stdio: 'ignore', windowsHide: true,
  });
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

function capture(page) {
  const requests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) {
      requests.push({sequence: requests.length + 1, method: request.method(),
        path: url.pathname.slice(4), query: Object.fromEntries(url.searchParams)});
    }
  });
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

const frontend = startFrontend();
let browser;
try {
  await waitForFrontend();
  browser = await chromium.launch({headless: true});

  const anonymousContext = await browser.newContext();
  const anonymousPage = await anonymousContext.newPage();
  const anonymousRequests = capture(anonymousPage);
  await anonymousPage.goto(`${baseUrl}/sessions/${sessionId}/seats`);
  await anonymousPage.getByRole('region', {name: '场次座位状态与区域筛选'}).waitFor();
  await waitForCount(anonymousRequests, item => item.path.endsWith('/seat-availability'), 1);
  const anonymousInitial = summarize(anonymousRequests);
  if (anonymousInitial.sessionReads !== 1 || anonymousInitial.eventReads !== 1 ||
      anonymousInitial.layoutReads !== 1 || anonymousInitial.availabilityReads !== 1 ||
      anonymousInitial.legacySeatReads !== 0) throw new Error('anonymous request graph mismatch');
  await anonymousContext.close();

  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto(baseUrl + '/login');
  await page.getByLabel('用户名').fill('demo');
  await page.getByLabel('密码').fill('Ticketing123!');
  await page.getByRole('button', {name: '登录', exact: true}).click();
  await page.getByRole('heading', {name: '这一场，值得亲临。'}).waitFor();
  const requests = capture(page);
  await page.goto(`${baseUrl}/sessions/${sessionId}/seats`);
  await page.getByRole('region', {name: '场次座位状态与区域筛选'}).waitFor();
  await waitForCount(requests, item => item.path.endsWith('/seat-availability'), 1);
  const authenticatedInitial = summarize(requests);

  await page.getByRole('button', {name: /^R001-005，可选，/}).click();
  await page.getByRole('button', {name: '移除座位 R001-005'}).waitFor();
  await waitForCount(requests, item => item.path.endsWith('/seat-availability'), 2);
  const afterFirstSelection = summarize(requests);
  const locator = await page.evaluate(() => JSON.parse(
    sessionStorage.getItem('ticketing.checkout.U-1001') || '{}'));
  const ownedReads = requests.filter(item => item.path.endsWith('/seat-availability') &&
    item.query.checkoutSessionId === locator.checkoutSessionId);
  if (!locator.checkoutSessionId || ownedReads.length < 1 || afterFirstSelection.layoutReads !== 1 ||
      afterFirstSelection.checkoutCreates !== 1) throw new Error('first selection request graph mismatch');

  await page.getByRole('button', {name: /^R001-006，可选，/}).click();
  await page.getByRole('button', {name: '移除座位 R001-006'}).waitFor();
  await waitForCount(requests, item => item.path.endsWith('/seat-availability'), 3);
  const afterSecondSelection = summarize(requests);
  const evidence = {recordedAt: new Date().toISOString(), sessionId,
    anonymousInitial, authenticatedInitial, afterFirstSelection, afterSecondSelection};
  await writeFile(output, JSON.stringify(evidence, null, 2) + '\n');
  if (afterSecondSelection.layoutReads !== 1 || afterSecondSelection.availabilityReads !== 3 ||
      afterSecondSelection.checkoutSeatUpdates !== 1 || afterSecondSelection.legacySeatReads !== 0)
    throw new Error('second selection request graph mismatch: ' + JSON.stringify(afterSecondSelection));
  await context.close();
  console.log(`[PASS] real page flow recorded: ${output}`);
} finally {
  if (browser) await browser.close();
  if (frontend.pid) frontend.kill();
}
