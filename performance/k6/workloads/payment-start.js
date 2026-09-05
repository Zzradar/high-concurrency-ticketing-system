import exec from 'k6/execution'; import http from 'k6/http';
import { loadConfig, SYSTEM_TAGS } from '../lib/config.js'; import { loadPaymentOrders, loadSessions } from '../lib/data.js';
import { mutationHeaders } from '../lib/http.js'; import { recordResult } from '../lib/metrics.js';
import { correctnessThresholds, scenarioFor } from '../lib/scenarios.js'; import { summaryHandler } from '../lib/summary.js';
const config = loadConfig('payment-start'); const orders = loadPaymentOrders(); const sessions = loadSessions();
export const options = {systemTags: SYSTEM_TAGS, scenarios: scenarioFor(config.mode), thresholds: correctnessThresholds(config.mode)};
http.setResponseCallback(http.expectedStatuses(202));
export default function () { const index = exec.scenario.iterationInTest; if (index >= orders.length) throw new Error(`payment order pool exhausted: required index=${index}, available count=${orders.length}`); const item = orders[index]; const response = http.post(`${config.baseUrl}/orders/${item.orderId}/pay`, null, {headers: mutationHeaders(sessions[item.sessionIndex]), tags: {name: 'POST /orders/{orderId}/pay'}}); const valid = response.status === 202 && response.json('disposition') === 'STARTED_NEW' && response.json('paymentAttempt.status') === 'PROCESSING'; recordResult(valid ? 'success' : response.status >= 500 || response.status === 0 ? 'system_error' : 'unexpected', 'payment_start'); }
export const handleSummary = summaryHandler(config);
