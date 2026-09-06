// Fixed 4/16 characterization, independent scenarios; no business mutations.
import exec from 'k6/execution';
import http from 'k6/http';
import {Counter, Trend} from 'k6/metrics';
import {loadConfig, SYSTEM_TAGS} from '../lib/config.js';
import {loadDataset, loadSessions} from '../lib/data.js';
import {authCookie} from '../lib/http.js';
import {classifyRead, recordResult} from '../lib/metrics.js';
import {correctnessThresholds} from '../lib/scenarios.js';
import {summaryHandler} from '../lib/summary.js';

const config = loadConfig('post-offload-capacity');
const dataset = loadDataset();
const sessions = loadSessions();
const mixed = __ENV.CAPACITY_KIND === 'mixed';
const encoding = __ENV.SEAT_MAP_ENCODING;
const expectedHeld = Number(__ENV.EXPECTED_HELD);
if (!['gzip', 'identity'].includes(encoding) || ![0, 4500].includes(expectedHeld))
    throw new Error('explicit encoding and fixture required');
const exact = new Counter('ticketing_display_exact_total');
const degraded = new Counter('ticketing_display_degraded_total');
const invalid = new Counter('ticketing_display_invalid_total');
const busy = new Counter('ticketing_seat_map_503_total');
const measurements = {};
for (const kind of ['public', 'auth', 'seat']) measurements[kind] = {
    completed: new Counter(`ticketing_capacity_${kind}_completed_total`),
    success: new Counter(`ticketing_capacity_${kind}_success_total`),
    duration: new Trend(`ticketing_capacity_${kind}_duration_ms`, true),
    waiting: new Trend(`ticketing_capacity_${kind}_waiting_ms`, true),
    receiving: new Trend(`ticketing_capacity_${kind}_receiving_ms`, true),
};
function scenario(name, rate) {
    return {executor: 'constant-arrival-rate', exec: name, rate: Number(rate),
        timeUnit: '1s', duration: config.duration, preAllocatedVUs: 700, gracefulStop: '30s'};
}
export const options = {discardResponseBodies: true, systemTags: SYSTEM_TAGS,
    scenarios: mixed ? {
        public_read: scenario('publicRead', __ENV.PUBLIC_RATE),
        auth_warm: scenario('authWarm', __ENV.AUTH_RATE),
        seat_map: scenario('seatMap', __ENV.RATE),
    } : {seat_map: scenario('seatMap', __ENV.RATE)},
    thresholds: {...correctnessThresholds(config.mode),
        ticketing_display_invalid_total: ['count==0'],
        ticketing_display_degraded_total: ['count==0'],
        ticketing_seat_map_503_total: ['count==0']},
};
http.setResponseCallback(http.expectedStatuses(200));
function seatRequest(preflight = false) {
    return http.get(`${config.baseUrl}/sessions/${dataset.seatMapSessionId}/seats`, {
        headers: {'Accept-Encoding': encoding}, responseType: 'text',
        tags: {name: preflight ? 'seat-map preflight' : 'GET /sessions/{sessionId}/seats'},
    });
}
function display(response) {
    const seats = response.json();
    if (!Array.isArray(seats) || seats.length !== 5000) return 'invalid';
    const counts = {HELD: 0, AVAILABLE: 0, SOLD: 0};
    for (const seat of seats) {
        if (!seat.id || seat.sessionId !== dataset.seatMapSessionId || !(seat.status in counts)) return 'invalid';
        counts[seat.status]++;
    }
    if (counts.HELD === expectedHeld && counts.AVAILABLE === 5000 - expectedHeld && counts.SOLD === 0) return 'exact';
    if (expectedHeld > 0 && counts.HELD === 0 && counts.AVAILABLE === 5000 && counts.SOLD === 0) return 'degraded';
    return 'invalid';
}
export function setup() {
    if (mixed && sessions.length < 100) throw new Error('warm pool requires 100 sessions');
    const response = seatRequest(true);
    if (response.status !== 200 || display(response) !== 'exact' ||
        (response.headers['Content-Encoding'] === 'gzip') !== (encoding === 'gzip'))
        throw new Error('capacity fixture/encoding preflight failed');
}
function record(kind, response, result) {
    const metric = measurements[kind];
    metric.completed.add(1); metric.success.add(result === 'success' ? 1 : 0);
    metric.duration.add(response.timings.duration);
    metric.waiting.add(response.timings.waiting); metric.receiving.add(response.timings.receiving);
    recordResult(result, `capacity_${kind}`);
}
export function seatMap() {
    const response = seatRequest();
    let result = classifyRead(response, 200, () => true);
    let state = 'not_200';
    if (response.status === 200) {
        try { state = display(response); } catch (_) { state = 'invalid'; }
        if (state === 'invalid') result = 'unexpected';
    }
    exact.add(state === 'exact' ? 1 : 0); degraded.add(state === 'degraded' ? 1 : 0);
    invalid.add(state === 'invalid' ? 1 : 0); busy.add(response.status === 503 ? 1 : 0);
    // A 503 remains a system error as well as a separately counted rejection.
    record('seat', response, result);
}
export function publicRead() {
    const response = http.get(`${config.baseUrl}/events`, {tags: {name: 'GET /events'}});
    record('public', response, classifyRead(response, 200, () => true));
}
export function authWarm() {
    const session = sessions[exec.scenario.iterationInTest % 100];
    const response = http.get(`${config.baseUrl}/auth/me`, {
        headers: {Cookie: authCookie(session)}, tags: {name: 'GET /auth/me'},
    });
    record('auth', response, classifyRead(response, 200, () => true));
}
export const handleSummary = summaryHandler(config);
