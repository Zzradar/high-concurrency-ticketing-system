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
const kind = __ENV.CAPACITY_KIND || 'seat';
const mixed = kind === 'mixed';
const encoding = __ENV.SEAT_MAP_ENCODING;
const expectedHeld = Number(__ENV.EXPECTED_HELD);
if (!['gzip', 'identity'].includes(encoding) || ![0, 4500].includes(expectedHeld))
    throw new Error('explicit encoding and fixture required');
const exact = new Counter('ticketing_display_exact_total');
const degraded = new Counter('ticketing_display_degraded_total');
const invalid = new Counter('ticketing_display_invalid_total');
const busy = new Counter('ticketing_seat_map_503_total');
const measurements = {};
for (const kind of ['public', 'auth', 'seat', 'page', 'session', 'event', 'layout', 'availability']) measurements[kind] = {
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
        page_entry: scenario('pageEntry', __ENV.PAGE_ENTRY_RATE),
        availability_refresh: scenario('seatMap', __ENV.REFRESH_RATE),
    } : {seat_map: scenario(kind === 'layout' ? 'seatLayout' :
                             kind === 'page-entry' ? 'pageEntry' : 'seatMap', __ENV.RATE)},
    thresholds: {...correctnessThresholds(config.mode),
        ticketing_display_invalid_total: ['count==0'],
        ticketing_display_degraded_total: ['count==0'],
        ticketing_seat_map_503_total: ['count==0']},
};
http.setResponseCallback(http.expectedStatuses(200));
function seatRequest(preflight = false) {
    const endpoint = kind === 'seat' ? 'seats' : 'seat-availability';
    return http.get(`${config.baseUrl}/sessions/${dataset.seatMapSessionId}/${endpoint}`, {
        headers: {'Accept-Encoding': encoding}, responseType: 'text',
        tags: {name: preflight ? 'seat-map preflight' : `GET /sessions/{sessionId}/${endpoint}`},
    });
}
function display(response) {
    const payload = response.json();
    const seats = kind === 'seat' ? payload : payload.seats;
    if (!Array.isArray(seats) || seats.length !== 5000) return 'invalid';
    if (kind !== 'seat' && payload.sessionId !== dataset.seatMapSessionId) return 'invalid';
    const counts = {HELD: 0, AVAILABLE: 0, SOLD: 0};
    for (const seat of seats) {
        if (!seat.id || (kind === 'seat' && seat.sessionId !== dataset.seatMapSessionId) ||
            !(seat.status in counts)) return 'invalid';
        counts[seat.status]++;
    }
    if (counts.HELD === expectedHeld && counts.AVAILABLE === 5000 - expectedHeld && counts.SOLD === 0) return 'exact';
    if (expectedHeld > 0 && counts.HELD === 0 && counts.AVAILABLE === 5000 && counts.SOLD === 0) return 'degraded';
    return 'invalid';
}
export function setup() {
    if (mixed && sessions.length < 100) throw new Error('warm pool requires 100 sessions');
    if (mixed) {
        const page = requestPageEntry(true);
        const availability = seatRequest(true);
        if (page.state !== 'exact' || availability.status !== 200 || display(availability) !== 'exact')
            throw new Error('mixed page/availability fixture preflight failed');
        return;
    }
    if (kind === 'layout') {
        const layout = layoutRequest(true);
        if (layout.status !== 200 || layoutState(layout) !== 'exact')
            throw new Error('layout fixture/encoding preflight failed');
        return;
    }
    if (kind === 'page-entry') {
        const state = requestPageEntry(true);
        if (state.state !== 'exact')
            throw new Error('page-entry fixture/encoding preflight failed');
        return;
    }
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
function recordEndpoint(kind, response, success) {
    const metric = measurements[kind];
    metric.completed.add(1); metric.success.add(success ? 1 : 0);
    metric.duration.add(response.timings.duration);
    metric.waiting.add(response.timings.waiting); metric.receiving.add(response.timings.receiving);
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
function layoutRequest(preflight = false) {
    return http.get(`${config.baseUrl}/sessions/${dataset.seatMapSessionId}/seat-layout`, {
        headers: {'Accept-Encoding': encoding}, responseType: 'text',
        tags: {name: preflight ? 'layout preflight' : 'GET /sessions/{sessionId}/seat-layout'},
    });
}
function layoutState(response) {
    const payload = response.json();
    if (payload.sessionId !== dataset.seatMapSessionId || !Array.isArray(payload.seats) ||
        payload.seats.length !== 5000) return 'invalid';
    const ids = new Set();
    for (const seat of payload.seats) {
        if (Object.keys(seat).sort().join(',') !== 'id,label,number,price,row,zone' || ids.has(seat.id))
            return 'invalid';
        ids.add(seat.id);
    }
    return 'exact';
}
export function seatLayout() {
    const response = layoutRequest();
    let state = 'not_200';
    if (response.status === 200) {
        try { state = layoutState(response); } catch (_) { state = 'invalid'; }
    }
    exact.add(state === 'exact' ? 1 : 0); degraded.add(0);
    invalid.add(state === 'invalid' ? 1 : 0); busy.add(response.status === 503 ? 1 : 0);
    record('seat', response, state === 'exact' ? 'success' :
        response.status === 503 ? 'system_error' : 'unexpected');
}
function requestPageEntry(preflight = false) {
    const started = Date.now();
    const session = http.get(`${config.baseUrl}/sessions/${dataset.seatMapSessionId}`, {
        responseType: 'text', tags: {name: preflight ? 'session preflight' : 'GET /sessions/{sessionId}'},
    });
    let sessionPayload = null;
    try { sessionPayload = session.json(); } catch (_) { /* invalid below */ }
    const eventId = sessionPayload && sessionPayload.eventId;
    if (session.status !== 200 || !eventId) {
        return {state: 'invalid', started, session, event: null, layout: null, availability: null};
    }
    const [event, layout, availability] = http.batch([
        ['GET', `${config.baseUrl}/events/${eventId}`, null,
            {responseType: 'text', tags: {name: preflight ? 'event preflight' : 'GET /events/{eventId}'}}],
        ['GET', `${config.baseUrl}/sessions/${dataset.seatMapSessionId}/seat-layout`, null,
            {headers: {'Accept-Encoding': encoding}, responseType: 'text', tags: {name: preflight ? 'layout preflight' : 'GET /sessions/{sessionId}/seat-layout'}}],
        ['GET', `${config.baseUrl}/sessions/${dataset.seatMapSessionId}/seat-availability`, null,
            {headers: {'Accept-Encoding': encoding}, responseType: 'text', tags: {name: preflight ? 'availability preflight' : 'GET /sessions/{sessionId}/seat-availability'}}],
    ]);
    let state = 'not_200';
    if (event.status === 200 && layout.status === 200 && availability.status === 200) {
        try {
            const eventPayload = event.json();
            const layoutPayload = layout.json();
            const availabilityPayload = availability.json();
            const layoutIds = new Set(layoutPayload.seats.map(seat => seat.id));
            const availabilityIds = new Set(availabilityPayload.seats.map(seat => seat.id));
            state = eventPayload.id === eventId && sessionPayload.id === dataset.seatMapSessionId &&
                sessionPayload.eventId === eventId && layoutPayload.sessionId === dataset.seatMapSessionId &&
                availabilityPayload.sessionId === dataset.seatMapSessionId &&
                layoutState(layout) === 'exact' && display(availability) === 'exact' &&
                availabilityIds.size === layoutIds.size &&
                availabilityPayload.seats.every(seat => layoutIds.has(seat.id)) ? 'exact' : 'invalid';
        } catch (_) { state = 'invalid'; }
    }
    return {state, started, session, event, layout, availability};
}
export function pageEntry() {
    const result = requestPageEntry(false);
    const responses = [result.session, result.event, result.layout, result.availability];
    const response = {status: responses.find(item => !item || item.status !== 200)?.status || 200,
        timings: {duration: Date.now() - result.started,
            waiting: Math.max(...responses.filter(Boolean).map(item => item.timings.waiting)),
            receiving: Math.max(...responses.filter(Boolean).map(item => item.timings.receiving))}};
    recordEndpoint('session', result.session, result.session?.status === 200);
    recordEndpoint('event', result.event || response, result.event?.status === 200);
    recordEndpoint('layout', result.layout || response, result.layout?.status === 200);
    recordEndpoint('availability', result.availability || response, result.availability?.status === 200);
    exact.add(result.state === 'exact' ? 1 : 0); degraded.add(0);
    invalid.add(result.state === 'invalid' ? 1 : 0);
    for (const item of responses) busy.add(item?.status === 503 ? 1 : 0);
    record('page', response, result.state === 'exact' ? 'success' :
        response.status === 503 ? 'system_error' : 'unexpected');
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
