import exec from 'k6/execution'; import http from 'k6/http';
import { loadConfig, SYSTEM_TAGS } from '../lib/config.js'; import { loadWorkloadUsers } from '../lib/data.js';
import { jsonHeaders } from '../lib/http.js'; import { recordResult } from '../lib/metrics.js';
import { correctnessThresholds, scenarioFor } from '../lib/scenarios.js'; import { summaryHandler } from '../lib/summary.js';
const config = loadConfig('login'); const users = loadWorkloadUsers(); const password = __ENV.LOGIN_PASSWORD;
if (!password) throw new Error('LOGIN_PASSWORD is required');
export const options = {systemTags: SYSTEM_TAGS, scenarios: scenarioFor(config.mode), thresholds: correctnessThresholds(config.mode)};
http.setResponseCallback(http.expectedStatuses(200, 503));
export default function () { const index = exec.scenario.iterationInTest; if (index >= users.length) throw new Error(`login user pool exhausted: required index=${index}, available count=${users.length}`); const response = http.post(`${config.baseUrl}/auth/login`, JSON.stringify({username: users[index].username, password}), {headers: jsonHeaders({Origin: 'http://performance.local'}), tags: {name: 'POST /auth/login'}}); let result = 'unexpected'; if (response.status === 200 && response.json('id') === users[index].userId) result = 'success'; else if (response.status === 503 && response.json('code') === 'AUTH_BUSY') result = 'capacity_rejection'; else if (response.status === 0 || response.status >= 500) result = 'system_error'; recordResult(result, 'login'); }
export const handleSummary = summaryHandler(config);
