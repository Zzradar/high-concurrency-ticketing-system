import exec from 'k6/execution';
import http from 'k6/http';

import { loadConfig, positiveInteger, SYSTEM_TAGS } from '../lib/config.js';
import { loadSessions, loadWorkloadSeats } from '../lib/data.js';
import { reservationHeaders } from '../lib/http.js';
import {
    contentionGroups,
    invalidContentionGroups,
    invalidWorkloadGroups,
    recordResult,
    reservationAttempts,
    workloadGroups,
} from '../lib/metrics.js';
import { correctnessThresholds, scenarioFor } from '../lib/scenarios.js';
import { summaryHandler } from '../lib/summary.js';

const config = loadConfig('formal-seat-contention');
const sessions = loadSessions();
const seats = loadWorkloadSeats();
const contenders = positiveInteger('CONTENDERS_PER_SEAT', '4');
if (contenders < 2 || contenders > 20) {
    throw new Error('CONTENDERS_PER_SEAT must be between 2 and 20');
}
if (sessions.length < contenders) {
    throw new Error('not enough distinct users for a contention group');
}

export const options = {
    systemTags: SYSTEM_TAGS,
    scenarios: scenarioFor(config.mode, 'GROUP_RATE'),
    thresholds: correctnessThresholds(config.mode, true),
    batch: contenders,
    batchPerHost: contenders,
};

http.setResponseCallback(http.expectedStatuses(201, 409));

function classify(response) {
    if (!response || response.status === 0 || response.status >= 500) {
        return 'system_error';
    }
    if (response.status === 201) {
        try {
            return response.json('reservation.id') && response.json('order.id')
                ? 'success'
                : 'system_error';
        } catch (_) {
            return 'system_error';
        }
    }
    if (response.status === 409) {
        try {
            return response.json('code') === 'SEAT_CONFLICT'
                ? 'business_conflict'
                : 'unexpected';
        } catch (_) {
            return 'system_error';
        }
    }
    return 'unexpected';
}

export default function () {
    const groupIndex = exec.scenario.iterationInTest;
    if (groupIndex >= seats.length) {
        throw new Error(
            `formal Seat pool exhausted: required index=${groupIndex}, available count=${seats.length}`,
        );
    }
    const seat = seats[groupIndex];
    const requests = [];
    for (let contender = 0; contender < contenders; contender += 1) {
        const session = sessions[(groupIndex * contenders + contender) % sessions.length];
        const key = `phase10a-${config.shortRunToken}-g${groupIndex}-c${contender}`;
        requests.push({
            method: 'POST',
            url: `${config.baseUrl}/reservations`,
            body: JSON.stringify({sessionId: seat.sessionId, seatIds: [seat.sessionSeatId]}),
            params: {
                headers: reservationHeaders(session, key),
                tags: {name: 'POST /reservations'},
            },
        });
    }
    const responses = http.batch(requests);
    let successes = 0;
    let conflicts = 0;
    for (const response of responses) {
        const result = classify(response);
        recordResult(result, 'formal_reservation');
        if (result === 'success') successes += 1;
        if (result === 'business_conflict') conflicts += 1;
    }
    contentionGroups.add(1, {step: 'formal_group'});
    reservationAttempts.add(responses.length, {step: 'formal_reservation'});
    const validGroup = successes === 1 && conflicts === contenders - 1;
    invalidContentionGroups.add(validGroup ? 0 : 1, {step: 'formal_group'});
    workloadGroups.add(1, {step: 'formal_group'});
    invalidWorkloadGroups.add(validGroup ? 0 : 1, {step: 'formal_group'});
    if (!validGroup) {
        recordResult('unexpected', 'formal_group');
    }
}

export const handleSummary = summaryHandler(config);
