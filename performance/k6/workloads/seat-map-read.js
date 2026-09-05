import exec from 'k6/execution';
import http from 'k6/http';

import { loadConfig, SYSTEM_TAGS } from '../lib/config.js';
import { loadDataset } from '../lib/data.js';
import { classifyRead, recordResult } from '../lib/metrics.js';
import { correctnessThresholds, scenarioFor } from '../lib/scenarios.js';
import { summaryHandler } from '../lib/summary.js';

const config = loadConfig('seat-map-read');
const dataset = loadDataset();
export const options = {
    discardResponseBodies: true,
    systemTags: SYSTEM_TAGS,
    scenarios: scenarioFor(config.mode),
    thresholds: correctnessThresholds(config.mode),
};

http.setResponseCallback(http.expectedStatuses(200));

export function setup() {
    const response = http.get(`${config.baseUrl}/sessions/${dataset.seatMapSessionId}/seats`, {
        responseType: 'text', tags: {name: 'GET /sessions/{sessionId}/seats preflight'},
    });
    let valid = false;
    try {
        const payload = response.json();
        valid = response.status === 200 && Array.isArray(payload) && payload.length > 0
            && payload.every((seat) => seat.id && seat.sessionId === dataset.seatMapSessionId && seat.status);
    } catch (_) { valid = false; }
    if (!valid) throw new Error('seat-map preflight contract failed');
}

export default function () {
    const response = http.get(`${config.baseUrl}/sessions/${dataset.seatMapSessionId}/seats`, {
        responseType: 'none', tags: {name: 'GET /sessions/{sessionId}/seats'},
    });
    recordResult(classifyRead(response, 200, () => true), 'seat_map_read');
}

export const handleSummary = summaryHandler(config);
