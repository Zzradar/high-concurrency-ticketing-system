import http from 'k6/http';
import exec from 'k6/execution';
import { sleep } from 'k6';
import { SharedArray } from 'k6/data';
import { Counter, Trend, Gauge } from 'k6/metrics';
import { delayMs, compareCursor, flowKind, validateSync } from './policy.mjs';

const users = new SharedArray('phase19 users', () => JSON.parse(open('/fixture/users.json')));
const cfg = JSON.parse(open('/fixture/config.json'));
const mode = __ENV.MODE || 'closed';
const vus = Number(__ENV.VUS || 100);
const duration = Number(__ENV.SECONDS || 150);
const warmup = Number(__ENV.WARMUP_SECONDS || 0);
const readerVus = Number(__ENV.READER_VUS || 100);
const writerVus = Number(__ENV.WRITER_VUS || 100);
const rate = Number(__ENV.READ_RATE || 50);
const transitions = Number(__ENV.TRANSITIONS_RATE || 5);
const base = __ENV.BASE_URL;
if (!base || users.length < Math.max(vus, 3000 + writerVus)) throw new Error('Insufficient fixture or missing URL');

const started = new Counter('phase19_started');
const completed = new Counter('phase19_completed');
const errors = new Counter('phase19_errors');
const actual = new Counter('phase19_initialized_vus');
const syncs = new Counter('phase19_sync');
const advanced = new Counter('phase19_cursor_advances');
const changes = new Counter('phase19_changed_seats');
const writeRequests = new Counter('phase19_write_requests');
const flows = new Counter('phase19_flows');
const intervals = new Trend('phase19_poll_interval_ms', true);
const inflight = new Gauge('phase19_max_inflight');

const scenarios = mode === 'open' ? {
  readers: { executor: 'constant-arrival-rate', exec: 'openReader', rate, timeUnit: '1s', duration: `${duration}s`, preAllocatedVUs: readerVus, maxVUs: readerVus, gracefulStop: '40s' },
  // Weighted mean is 2.8 target seat-state transitions per journey (2/4/4/2).
  writers: { executor: 'constant-arrival-rate', exec: 'writer', rate: transitions * 5, timeUnit: '14s', duration: `${duration}s`, preAllocatedVUs: writerVus, maxVUs: writerVus, gracefulStop: '40s' },
} : { readers: { executor: 'constant-vus', exec: 'closedReader', vus, duration: `${duration}s`, gracefulStop: '40s' } };

export const options = {
  scenarios, systemTags: ['status', 'method', 'name', 'scenario', 'expected_response', 'error_code'],
  thresholds: { phase19_errors: ['count==0'], dropped_iterations: ['count==0'], http_req_failed: ['rate==0'] },
  summaryTrendStats: ['avg', 'med', 'p(95)', 'p(99)', 'max'],
  discardResponseBodies: false,
};
http.setResponseCallback(http.expectedStatuses(200, 201));

let initialized = false, state, lastStart, empty = 0;
function phase() { return exec.instance.currentTestRunDuration < warmup * 1000 ? 'warmup' : 'observe'; }
function identity() {
  if (!initialized) {
    initialized = true; actual.add(1); errors.add(0);
    if (Number(__ENV.INIT_IDLE_SECONDS || 0)) sleep(Number(__ENV.INIT_IDLE_SECONDS));
  }
  const index = exec.vu.idInTest - 1;
  return { user: users[index], zone: cfg.zones[index % cfg.zones.length] };
}
function headers(user) {
  return { Accept: 'application/json', 'Content-Type': 'application/json',
    Cookie: `ticketing_session=${user.sessionToken}; ticketing_csrf=${user.csrfToken}`,
    'X-CSRF-Token': user.csrfToken, Origin: 'http://performance.local' };
}
function request(method, path, user, name, body) {
  if (method !== 'GET') writeRequests.add(1, { name, phase: phase() });
  const response = http.request(method, base + path, body === undefined ? null : JSON.stringify(body), {
    headers: headers(user), tags: { name, phase: phase() }, timeout: '10s',
  });
  if (![200, 201].includes(response.status)) {
    errors.add(1, { kind: response.status === 0 ? 'network' : response.status >= 500 ? 'system' : 'unexpected_status', name });
    throw new Error(`Unexpected ${name} status ${response.status}`);
  }
  try { return response.json(); } catch { errors.add(1, { kind: 'json', name }); throw new Error('Invalid response JSON'); }
}

function readOnce(snapshot = false) {
  const { user, zone } = identity();
  const session = mode === 'open' ? cfg.writerSession : cfg.readerSession;
  const before = Date.now();
  if (lastStart !== undefined) intervals.add(before - lastStart, { phase: phase() });
  lastStart = before;
  let query = '?zone=' + encodeURIComponent(zone);
  if (state && !snapshot) query += '&generation=' + encodeURIComponent(state.generation) + '&since=' + encodeURIComponent(state.cursor);
  inflight.add(1);
  const body = validateSync(request('GET', `/sessions/${session}/seat-availability${query}`, user, snapshot || !state ? 'GET snapshot' : 'GET delta'), session, zone);
  inflight.add(0);
  if (state && state.generation === body.generation && compareCursor(body.cursor, state.cursor) < 0) throw new Error('Cursor regressed');
  if (state && state.generation === body.generation && compareCursor(body.cursor, state.cursor) > 0) advanced.add(1, { phase: phase() });
  syncs.add(1, { mode: body.mode, reset: String(body.reset), hasMore: String(body.hasMore), phase: phase() });
  const count = (body.changes || []).length;
  changes.add(count, { phase: phase() });
  empty = body.mode === 'delta' && !count ? Math.min(empty + 1, 6) : 0;
  state = { generation: body.generation, cursor: body.cursor };
  return body;
}

function guarded(kind, action) {
  started.add(1, { kind, phase: phase() });
  try { action(); completed.add(1, { kind, phase: phase() }); }
  catch (cause) { errors.add(1, { kind: 'iteration', flow: kind }); throw cause; }
}

export function closedReader() {
  guarded('closed', () => {
    let body = readOnce();
    while (body.hasMore) { sleep(.001); body = readOnce(); }
    sleep(delayMs(body.pollAfterMs, empty, 0) / 1000);
  });
}
export function openReader() {
  guarded('read', () => {
    if (!state) readOnce(true); // Each actual VU establishes its own snapshot, never a shared cursor.
    readOnce(); // Arrival rate is independent of completion; no pacing sleep in an open iteration.
  });
}

export function writer() {
  const kind = flowKind(exec.scenario.iterationInTest);
  guarded(kind, () => {
    identity();
    const slot = exec.vu.idInTest - readerVus - 1;
    if (slot < 0 || slot >= writerVus) throw new Error('Writer slot outside disjoint pool');
    const user = users[3000 + slot];
    const seat = cfg.writerSeats[slot * 2], other = cfg.writerSeats[slot * 2 + 1];
    if (!seat || !other) throw new Error('Writer seat pool exhausted');
    let checkout = request('POST', '/checkout-sessions', user, 'POST checkout', { sessionId: cfg.writerSession, seatIds: [seat] });
    if (kind === 'adjust') checkout = request('PUT', `/checkout-sessions/${checkout.id}/seats`, user, 'PUT checkout seats', { seatIds: [other], expectedRevision: checkout.revision });
    if (kind === 'cancel') {
      const confirmed = request('POST', `/checkout-sessions/${checkout.id}/confirm`, user, 'POST confirm');
      const order = confirmed.checkoutSession?.order;
      if (!order || confirmed.checkoutSession.status !== 'RESERVED') throw new Error('Confirmation contract');
      request('GET', `/orders/${order.id}`, user, 'GET order');
      const cancelled = request('POST', `/orders/${order.id}/cancel`, user, 'POST cancel');
      if (cancelled.order?.status !== 'CANCELLED') throw new Error('Cancellation contract');
    } else if (kind === 'expiry') {
      sleep(cfg.holdTtlSeconds + 1);
      const expired = request('GET', `/checkout-sessions/${checkout.id}`, user, 'GET expired checkout');
      if (expired.status !== 'EXPIRED') throw new Error('Natural expiry did not complete');
    } else {
      request('POST', `/checkout-sessions/${checkout.id}/abandon`, user, 'POST abandon');
    }
    flows.add(1, { kind, phase: phase() });
  });
}

export function handleSummary(data) {
  return { '/output/k6-summary.json': JSON.stringify({ mode, duration, warmup, vus, readerVus, writerVus, rate, transitions, data }, null, 2) };
}
