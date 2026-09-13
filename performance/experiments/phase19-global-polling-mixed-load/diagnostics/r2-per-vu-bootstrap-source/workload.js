import http from 'k6/http';
import exec from 'k6/execution';
import { sleep } from 'k6';
import { SharedArray } from 'k6/data';
import { Counter, Trend, Gauge } from 'k6/metrics';
import { delayMs, compareCursor, flowKind, validateSync, writerSlot } from './policy.mjs';

const users = new SharedArray('phase19 users', () => JSON.parse(open('/fixture/users.json')));
const writerSeats = new SharedArray('phase19 writer seats', () => JSON.parse(open('/fixture/seats.json')));
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
const httpStarted = new Counter('phase19_http_started');
const flows = new Counter('phase19_flows');
const intervals = new Trend('phase19_poll_interval_ms', true);
const inflight = new Gauge('phase19_max_inflight');
const hotOutcomes = new Counter('phase19_hot_outcomes');
const hotWinners = new Counter('phase19_hot_winners');

if (mode === 'open' && (rate % 10 || readerVus % 10)) throw new Error('Open readers require ten equal arrival streams');
function readerScenario(i) {
  return { exec: 'openReader', startTime: `${warmup * 1000 + i * 1000 / rate}ms`, timeUnit: '1s', preAllocatedVUs: readerVus / 10, maxVUs: readerVus / 10, gracefulStop: '40s',
    executor: 'constant-arrival-rate', rate: rate / 10, duration: `${duration - warmup}s` };
}
if (mode === 'open' && warmup > 0 && warmup < (readerVus + writerVus) / 50 + 5) throw new Error('Bootstrap window too short');
const scenarios = mode === 'open' ? {
  ...(warmup > 0 ? { bootstrap: { executor: 'per-vu-iterations', exec: 'bootstrapReader', vus: readerVus + writerVus, iterations: 1, maxDuration: `${warmup}s`, gracefulStop: '0s' } } : {}),
  ...Object.fromEntries(Array.from({ length: 10 }, (_, i) => [`readers${i}`, readerScenario(i)])),
  // Weighted mean is 2.8 target seat-state transitions per journey (2/4/4/2).
  writers: { executor: 'constant-arrival-rate', exec: 'writer', startTime: `${warmup}s`, rate: transitions * 5, timeUnit: '14s', duration: `${duration - warmup}s`, preAllocatedVUs: writerVus, maxVUs: writerVus, gracefulStop: '40s' },
} : mode === 'hotspot' ? { wave: { executor: 'per-vu-iterations', exec: 'hotspot', vus, iterations: 1, maxDuration: '40s' } }
  : mode === 'journeys' ? { journeys: { executor: 'constant-arrival-rate', exec: 'journey', rate: Number(__ENV.JOURNEY_RATE || 20), timeUnit: '1s', duration: `${duration}s`, preAllocatedVUs: vus, maxVUs: vus, gracefulStop: '40s' } }
  : { readers: { executor: 'constant-vus', exec: 'closedReader', vus, duration: `${duration}s`, gracefulStop: '40s' } };

export const options = {
  scenarios, systemTags: ['status', 'method', 'name', 'scenario', 'expected_response', 'error_code'],
  thresholds: { phase19_errors: ['count==0'], dropped_iterations: ['count==0'], http_req_failed: ['rate==0'], ...(mode === 'hotspot' ? { phase19_hot_winners: ['count==1'] } : {}) },
  summaryTrendStats: ['avg', 'med', 'p(95)', 'p(99)', 'max'],
  discardResponseBodies: false,
};
http.setResponseCallback(http.expectedStatuses(...(['hotspot', 'journeys'].includes(mode) ? [200, 201, 409, 429] : [200, 201])));

let initialized = false, state, lastStart, empty = 0, assignedZone;
function phase() { return exec.instance.currentTestRunDuration < warmup * 1000 ? 'warmup' : 'observe'; }
function identity() {
  if (!initialized) {
    initialized = true; actual.add(1); errors.add(0);
    if (Number(__ENV.INIT_IDLE_SECONDS || 0)) sleep(Number(__ENV.INIT_IDLE_SECONDS));
    if (mode === 'closed' && Number(__ENV.INIT_SPREAD_SECONDS || 0)) sleep((exec.vu.idInTest - 1) / vus * Number(__ENV.INIT_SPREAD_SECONDS));
  }
  const index = exec.vu.idInTest - 1;
  assignedZone ??= cfg.zones[index % cfg.zones.length];
  return { user: users[index], zone: assignedZone };
}
function headers(user) {
  return { Accept: 'application/json', 'Content-Type': 'application/json',
    Cookie: `ticketing_session=${user.sessionToken}; ticketing_csrf=${user.csrfToken}`,
    'X-CSRF-Token': user.csrfToken, Origin: 'http://performance.local' };
}
function request(method, path, user, name, body) {
  httpStarted.add(1, { name, method, phase: phase() });
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
export function bootstrapReader() {
  guarded('bootstrap', () => {
    sleep((exec.vu.idInTest - 1) / 50);
    readOnce(true);
  });
}
export function openReader() {
  guarded('read', () => {
    if (warmup > 0 && !state) throw new Error('Reader did not retain its own bootstrapped cursor');
    if (!state) readOnce(true); // Each actual VU establishes its own snapshot, never a shared cursor.
    let body = readOnce(); // Arrival rate is independent of completion; no pacing sleep in an open iteration.
    while (body.hasMore) { sleep(.001); body = readOnce(); }
  });
}

export function writer() {
  const kind = flowKind(exec.scenario.iterationInTest);
  guarded(kind, () => {
    identity();
    const slot = writerSlot(exec.vu.idInTest, readerVus + writerVus, writerSeats.length / 2);
    const user = users[3000 + slot];
    const seat = writerSeats[slot * 2], other = writerSeats[slot * 2 + 1];
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
      // Redis TTL/read-model cleanup expires temporary ownership. The production
      // Checkout state remains SELECTING; EXPIRED is an Order state, not Checkout.
      const expired = request('GET', `/sessions/${cfg.writerSession}/seat-availability?zone=${encodeURIComponent(cfg.zones[0])}`, user, 'GET expiry snapshot');
      if (expired.degraded || expired.seats?.find(s => s.id === seat)?.status !== 'AVAILABLE') throw new Error('Natural hold expiry did not complete');
      request('POST', `/checkout-sessions/${checkout.id}/abandon`, user, 'POST expired checkout cleanup');
    } else {
      request('POST', `/checkout-sessions/${checkout.id}/abandon`, user, 'POST abandon');
    }
    flows.add(1, { kind, phase: phase() });
  });
}

function contend(user, group, seat) {
  const began = Date.now();
  httpStarted.add(1, { name: 'POST hotspot', method: 'POST', phase: phase() });
  writeRequests.add(1, { name: 'POST hotspot', phase: phase() });
  const r = http.post(base + '/checkout-sessions', JSON.stringify({ sessionId: cfg.hotspotSession, seatIds: [seat] }), {
    headers: headers(user), tags: { name: 'POST hotspot', phase: phase() }, timeout: '10s',
  });
  let body;
  try { body = r.json(); } catch { body = {}; }
  const outcome = r.status === 201 && body.id ? 'winner'
    : r.status === 409 && ['SEAT_CONFLICT', 'SEAT_TEMPORARILY_HELD'].includes(body.code) ? 'conflict'
      : r.status === 429 && body.code === 'RATE_LIMITED' ? 'rate_limited' : 'unexpected';
  hotOutcomes.add(1, { group: String(group), outcome, status: String(r.status) });
  if (outcome === 'winner') hotWinners.add(1);
  if (outcome === 'unexpected') errors.add(1, { kind: 'hotspot_status', status: String(r.status) });
  // Bounded ordinal timing, never account/session credentials or seat identifiers as tags.
  console.log(JSON.stringify({ type: 'phase19-hot-timing', ordinal: exec.vu.idInTest, group, startEpochMs: began, endEpochMs: Date.now(), status: r.status, outcome }));
}

export function setup() { return { waveEpochMs: Date.now() + 5000 }; }

export function hotspot(data) {
  guarded('hotspot', () => {
    identity(); hotWinners.add(0);
    sleep(Math.max(0, data.waveEpochMs - Date.now()) / 1000);
    contend(users[4000 + exec.vu.idInTest - 1], 'wave', 'phase19-ss-001-003-004000');
  });
}

export function journey() {
  const index = exec.scenario.iterationInTest;
  const part = index % 100;
  const kind = part < 75 ? 'browse' : part < 90 ? 'hold' : part < 98 ? 'order_cancel' : 'hotspot';
  guarded('journey_' + kind, () => {
    identity();
    const user = users[index % users.length];
    const session = cfg.journeySession;
    const seat = `phase19-ss-001-005-${String(index % 5000 + 1).padStart(6, '0')}`;
    if (kind === 'browse') {
      request('GET', '/events', user, 'GET events');
      request('GET', '/events/phase19-event-001/sessions', user, 'GET sessions');
      request('GET', `/sessions/${session}/seat-layout`, user, 'GET layout');
      const zone = cfg.zones[index % cfg.zones.length];
      let body = validateSync(request('GET', `/sessions/${session}/seat-availability?zone=${encodeURIComponent(zone)}`, user, 'GET journey snapshot'), session, zone);
      do {
        body = validateSync(request('GET', `/sessions/${session}/seat-availability?zone=${encodeURIComponent(zone)}&generation=${encodeURIComponent(body.generation)}&since=${encodeURIComponent(body.cursor)}`, user, 'GET journey delta'), session, zone);
        if (body.hasMore) sleep(.001);
      } while (body.hasMore);
    } else if (kind === 'hotspot') {
      const group = Math.floor(index / 100) % 50;
      contend(user, group, `phase19-ss-001-003-${String(group + 1).padStart(6, '0')}`);
    } else {
      const checkout = request('POST', '/checkout-sessions', user, 'POST journey checkout', { sessionId: session, seatIds: [seat] });
      if (kind === 'hold') {
        request('POST', `/checkout-sessions/${checkout.id}/abandon`, user, 'POST journey abandon');
      } else {
        const result = request('POST', `/checkout-sessions/${checkout.id}/confirm`, user, 'POST journey confirm');
        const order = result.checkoutSession?.order;
        if (!order) throw new Error('Journey confirmation');
        request('GET', `/orders/${order.id}`, user, 'GET journey order');
        const cancelled = request('POST', `/orders/${order.id}/cancel`, user, 'POST journey cancel');
        if (cancelled.order?.status !== 'CANCELLED') throw new Error('Journey cancellation');
      }
    }
    flows.add(1, { kind: 'journey_' + kind, phase: phase() });
  });
}

export function handleSummary(data) {
  return { '/output/k6-summary.json': JSON.stringify({ mode, duration, warmup, vus, readerVus, writerVus, rate, transitions, data }, null, 2) };
}
