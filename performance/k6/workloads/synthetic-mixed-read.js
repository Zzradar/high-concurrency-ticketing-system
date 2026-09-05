import exec from 'k6/execution'; import http from 'k6/http';
import { loadConfig, positiveInteger, SYSTEM_TAGS } from '../lib/config.js';
import { loadDataset, loadSessions } from '../lib/data.js'; import { authCookie } from '../lib/http.js';
import { classifyRead, recordResult } from '../lib/metrics.js'; import { correctnessThresholds } from '../lib/scenarios.js'; import { summaryHandler } from '../lib/summary.js';
const config = loadConfig('synthetic-mixed-read'); const dataset = loadDataset(); const sessions = loadSessions();
const duration = __ENV.DURATION || '60s'; const vus = positiveInteger('PREALLOCATED_VUS');
export const options = {discardResponseBodies: true, systemTags: SYSTEM_TAGS, thresholds: correctnessThresholds(config.mode), scenarios: {
    public_read: {executor: 'constant-arrival-rate', exec: 'publicRead', rate: positiveInteger('PUBLIC_RATE'), timeUnit: '1s', duration, preAllocatedVUs: vus},
    auth_warm: {executor: 'constant-arrival-rate', exec: 'authWarm', rate: positiveInteger('AUTH_RATE'), timeUnit: '1s', duration, preAllocatedVUs: vus},
    seat_map: {executor: 'constant-arrival-rate', exec: 'seatMap', rate: positiveInteger('SEAT_MAP_RATE'), timeUnit: '1s', duration, preAllocatedVUs: vus},
}};
http.setResponseCallback(http.expectedStatuses(200));
export function publicRead() { const response = http.get(`${config.baseUrl}/events`, {responseType: 'none', tags: {name: 'GET /events'}}); recordResult(classifyRead(response, 200, () => true), 'mixed_public_read'); }
export function authWarm() { const session = sessions[exec.scenario.iterationInTest % sessions.length]; const response = http.get(`${config.baseUrl}/auth/me`, {headers: {Cookie: authCookie(session)}, responseType: 'none', tags: {name: 'GET /auth/me'}}); recordResult(classifyRead(response, 200, () => true), 'mixed_auth_warm'); }
export function seatMap() { const response = http.get(`${config.baseUrl}/sessions/${dataset.seatMapSessionId}/seats`, {responseType: 'none', tags: {name: 'GET /sessions/{sessionId}/seats'}}); recordResult(classifyRead(response, 200, () => true), 'mixed_seat_map'); }
export const handleSummary = summaryHandler(config);
