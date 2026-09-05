import exec from 'k6/execution';
import http from 'k6/http';

import { loadConfig, positiveInteger, SYSTEM_TAGS } from '../lib/config.js';
import { loadSessions } from '../lib/data.js';
import { authCookie } from '../lib/http.js';
import { classifyRead, recordResult } from '../lib/metrics.js';
import { correctnessThresholds, scenarioFor } from '../lib/scenarios.js';
import { summaryHandler } from '../lib/summary.js';

const config = loadConfig('auth-read');
const sessions = loadSessions();
const authMode = __ENV.AUTH_MODE || 'warm';
const authPoolSize = positiveInteger('AUTH_POOL_SIZE', '100');
if (!['warm', 'cold', 'redis-down'].includes(authMode)) {
    throw new Error(`unsupported AUTH_MODE: ${authMode}`);
}
if (authPoolSize > sessions.length) {
    throw new Error('AUTH_POOL_SIZE exceeds sessions.json');
}

export const options = {
    systemTags: SYSTEM_TAGS,
    scenarios: scenarioFor(config.mode),
    thresholds: correctnessThresholds(config.mode),
};

http.setResponseCallback(http.expectedStatuses(200));

export default function () {
    const iteration = exec.scenario.iterationInTest;
    const index = authMode === 'cold' ? iteration : iteration % authPoolSize;
    if (index >= sessions.length) {
        throw new Error(
            `cold auth Session pool exhausted: required index=${index}, available count=${sessions.length}`,
        );
    }
    const session = sessions[index];
    const response = http.get(`${config.baseUrl}/auth/me`, {
        headers: {Accept: 'application/json', Cookie: authCookie(session)},
        tags: {name: 'GET /auth/me'},
    });
    const result = classifyRead(response, 200, (value) => {
        try {
            return value.json('id') === session.userId;
        } catch (_) {
            return false;
        }
    });
    recordResult(result, 'auth_read');
}

export const handleSummary = summaryHandler(config);
