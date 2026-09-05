import exec from 'k6/execution';
import http from 'k6/http';

import { loadConfig, positiveInteger, SYSTEM_TAGS } from '../lib/config.js';
import { loadSessions, loadWorkloadSeats } from '../lib/data.js';
import { mutationHeaders } from '../lib/http.js';
import { invalidWorkloadGroups, recordResult, workloadGroups } from '../lib/metrics.js';
import { correctnessThresholds, scenarioFor } from '../lib/scenarios.js';
import { summaryHandler } from '../lib/summary.js';

const config = loadConfig('temporary-hold-contention');
const sessions = loadSessions();
const seats = loadWorkloadSeats();
const contenders = positiveInteger('CONTENDERS_PER_SEAT', '4');
if (contenders < 2 || contenders > 20 || sessions.length < contenders) {
    throw new Error('temporary hold contenders require 2..20 distinct users');
}
export const options = {
    systemTags: SYSTEM_TAGS,
    scenarios: scenarioFor(config.mode, 'GROUP_RATE'),
    thresholds: correctnessThresholds(config.mode, true),
    batch: contenders, batchPerHost: contenders,
};
http.setResponseCallback(http.expectedStatuses(201, 409));

export default function () {
    const groupIndex = exec.scenario.iterationInTest;
    if (groupIndex >= seats.length) throw new Error(`temporary hold Seat pool exhausted: required index=${groupIndex}, available count=${seats.length}`);
    const seat = seats[groupIndex];
    const requests = [];
    for (let contender = 0; contender < contenders; contender += 1) {
        const sessionIndex = groupIndex * contenders + contender;
        if (sessionIndex >= sessions.length) throw new Error(`temporary hold Session pool exhausted: required index=${sessionIndex}, available count=${sessions.length}`);
        requests.push({
            method: 'POST', url: `${config.baseUrl}/checkout-sessions`,
            body: JSON.stringify({sessionId: seat.sessionId, seatIds: [seat.sessionSeatId]}),
            params: {headers: mutationHeaders(sessions[sessionIndex]), tags: {name: 'POST /checkout-sessions'}},
        });
    }
    const responses = http.batch(requests);
    let created = 0; let conflicts = 0;
    for (const response of responses) {
        let result = 'unexpected';
        if (!response || response.status === 0 || response.status >= 500) result = 'system_error';
        else if (response.status === 201 && response.json('id')) { result = 'success'; created += 1; }
        else if (response.status === 409 && response.json('code') === 'SEAT_TEMPORARILY_HELD') { result = 'business_conflict'; conflicts += 1; }
        recordResult(result, 'temporary_hold');
    }
    const valid = created === 1 && conflicts === contenders - 1;
    workloadGroups.add(1, {step: 'temporary_hold_group'});
    invalidWorkloadGroups.add(valid ? 0 : 1, {step: 'temporary_hold_group'});
    if (!valid) recordResult('unexpected', 'temporary_hold_group');
}

export const handleSummary = summaryHandler(config);
