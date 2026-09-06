import exec from 'k6/execution';
import http from 'k6/http';
import { sleep } from 'k6';

import { loadConfig, positiveInteger, SYSTEM_TAGS } from '../lib/config.js';
import { loadDataset, loadSessions } from '../lib/data.js';
import { reservationHeaders } from '../lib/http.js';
import {
    classifyRead,
    recordResult,
    waveConflict,
    waveStartOffset,
    waveSuccess,
} from '../lib/metrics.js';
import { correctnessThresholds } from '../lib/scenarios.js';
import { summaryHandler } from '../lib/summary.js';

const config = loadConfig('formal-hot-seat-wave');
const dataset = loadDataset();
const sessions = loadSessions();
const contenders = positiveInteger('WAVE_CONTENDERS');
const controlRate = positiveInteger('CONTROL_RATE', '2');
const controlVUs = positiveInteger('CONTROL_VUS', '10');
const controlDuration = __ENV.WAVE_CONTROL_DURATION || '12s';
if (config.mode !== 'wave' || ![100, 500, 1000].includes(contenders)) {
    throw new Error('formal hot-seat wave requires MODE=wave and 100/500/1000 contenders');
}
if (sessions.length < contenders) throw new Error('formal wave Session pool exhausted');

const thresholds = correctnessThresholds(config.mode);
thresholds.ticketing_wave_success_total = ['count==1'];
thresholds.ticketing_wave_conflict_total = [`count==${contenders - 1}`];

export const options = {
    systemTags: SYSTEM_TAGS,
    scenarios: {
        wave: {
            executor: 'shared-iterations', exec: 'wave', vus: contenders,
            iterations: contenders, maxDuration: '30s', gracefulStop: '20s',
        },
        control_public: {
            executor: 'constant-arrival-rate', exec: 'controlPublic', rate: controlRate,
            timeUnit: '1s', duration: controlDuration, preAllocatedVUs: controlVUs,
        },
        control_auth: {
            executor: 'constant-arrival-rate', exec: 'controlAuth', rate: controlRate,
            timeUnit: '1s', duration: controlDuration, preAllocatedVUs: controlVUs,
        },
    },
    thresholds,
};

http.setResponseCallback(http.expectedStatuses(200, 201, 409));

export function setup() {
    return {releaseAt: Date.now() + 3000};
}

export function wave(state) {
    const delay = state.releaseAt - Date.now();
    if (delay > 0) sleep(delay / 1000);
    waveStartOffset.add(Date.now() - state.releaseAt, {step: 'formal_wave'});
    const index = exec.scenario.iterationInTest;
    if (index >= contenders || index >= sessions.length) throw new Error(`formal wave pool exhausted at ${index}`);
    const response = http.post(
        `${config.baseUrl}/reservations`,
        JSON.stringify({sessionId: dataset.hotSessionId, seatIds: [dataset.hotSessionSeatId]}),
        {
            headers: reservationHeaders(sessions[index], `phase10b-${config.shortRunToken}-wave-${index}`),
            tags: {name: 'POST /reservations'},
        },
    );
    let result = 'unexpected';
    if (response.status === 201 && response.json('reservation.id') && response.json('order.id')) {
        result = 'success'; waveSuccess.add(1, {step: 'formal_wave'});
    } else if (response.status === 409 && response.json('code') === 'SEAT_CONFLICT') {
        result = 'business_conflict'; waveConflict.add(1, {step: 'formal_wave'});
    } else if (response.status === 0 || response.status >= 500) result = 'system_error';
    recordResult(result, 'formal_wave');
}

export function controlPublic() {
    const response = http.get(`${config.baseUrl}/events`, {responseType: 'none', tags: {name: 'GET /events [wave control]'}});
    recordResult(classifyRead(response, 200, () => true), 'wave_control_public');
}

export function controlAuth() {
    const session = sessions[exec.scenario.iterationInTest % Math.min(sessions.length, 100)];
    const response = http.get(`${config.baseUrl}/auth/me`, {
        headers: {Cookie: `ticketing_session=${session.sessionToken}`},
        responseType: 'none', tags: {name: 'GET /auth/me [wave control]'},
    });
    recordResult(classifyRead(response, 200, () => true), 'wave_control_auth');
}

export const handleSummary = summaryHandler(config);
