import http from 'k6/http';

import { loadConfig, SYSTEM_TAGS } from '../lib/config.js';
import { classifyRead, recordResult } from '../lib/metrics.js';
import { correctnessThresholds, scenarioFor } from '../lib/scenarios.js';
import { summaryHandler } from '../lib/summary.js';

const config = loadConfig('public-read');

export const options = {
    systemTags: SYSTEM_TAGS,
    discardResponseBodies: true,
    scenarios: scenarioFor(config.mode),
    thresholds: correctnessThresholds(config.mode),
};

http.setResponseCallback(http.expectedStatuses(200));

export function setup() {
    const response = http.get(`${config.baseUrl}/events`, {
        responseType: 'text',
        tags: {name: 'GET /events'},
    });
    let valid = false;
    try {
        const payload = response.json();
        valid = response.status === 200 && Array.isArray(payload);
    } catch (_) {
        valid = false;
    }
    if (!valid) {
        throw new Error(`GET /events contract smoke failed: HTTP ${response.status}`);
    }
}

export default function () {
    const response = http.get(`${config.baseUrl}/events`, {
        responseType: 'none',
        tags: {name: 'GET /events'},
    });
    recordResult(classifyRead(response, 200, () => true), 'public_read');
}

export const handleSummary = summaryHandler(config);
