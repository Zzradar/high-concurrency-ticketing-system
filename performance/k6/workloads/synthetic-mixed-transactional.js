import exec from 'k6/execution'; import http from 'k6/http'; import { sleep } from 'k6';
import { loadConfig, positiveInteger, SYSTEM_TAGS } from '../lib/config.js'; import { loadPaymentOrders, loadSessions, loadWorkloadSeats } from '../lib/data.js';
import { mutationHeaders } from '../lib/http.js'; import { recordResult } from '../lib/metrics.js'; import { correctnessThresholds } from '../lib/scenarios.js'; import { summaryHandler } from '../lib/summary.js';
const config = loadConfig('synthetic-mixed-transactional'); const sessions = loadSessions(); const seats = loadWorkloadSeats(); const orders = loadPaymentOrders();
const duration = __ENV.DURATION || '30s'; const vus = positiveInteger('PREALLOCATED_VUS'); const checkoutOffset = Number(__ENV.CHECKOUT_POOL_OFFSET || 0);
function mixedScenario(execName, baseVariable, targetVariable, gracefulStop) {
    if (config.mode !== 'spike') return {executor: 'constant-arrival-rate', exec: execName, rate: positiveInteger(baseVariable), timeUnit: '1s', duration, preAllocatedVUs: vus, gracefulStop};
    return {executor: 'ramping-arrival-rate', exec: execName, startRate: positiveInteger(baseVariable), timeUnit: '1s', preAllocatedVUs: vus, gracefulStop, stages: [
        {target: positiveInteger(baseVariable), duration: __ENV.BASE_DURATION || '5s'},
        {target: positiveInteger(targetVariable), duration: __ENV.RAMP_DURATION || '5s'},
        {target: positiveInteger(targetVariable), duration: __ENV.HOLD_DURATION || '5s'},
        {target: positiveInteger(baseVariable), duration: __ENV.RECOVERY_DURATION || '5s'},
        {target: 0, duration: __ENV.RAMP_DOWN_DURATION || '5s'},
    ]};
}
export const options = {systemTags: SYSTEM_TAGS, thresholds: correctnessThresholds(config.mode), scenarios: {
    checkout: mixedScenario('checkoutFlow', 'CHECKOUT_RATE', 'CHECKOUT_TARGET_RATE', '20s'),
    payment: mixedScenario('paymentFlow', 'PAYMENT_RATE', 'PAYMENT_TARGET_RATE', '20s'),
}};
http.setResponseCallback(http.expectedStatuses(200, 201, 202));
export function checkoutFlow() { const index = checkoutOffset + exec.scenario.iterationInTest; if (index >= sessions.length || index >= seats.length) throw new Error(`mixed checkout pool exhausted at ${index}`); const session = sessions[index]; const seat = seats[index]; const headers = mutationHeaders(session); const created = http.post(`${config.baseUrl}/checkout-sessions`, JSON.stringify({sessionId: seat.sessionId, seatIds: [seat.sessionSeatId]}), {headers, tags: {name: 'POST /checkout-sessions'}}); if (created.status !== 201 || !created.json('id')) { recordResult(created.status >= 500 || created.status === 0 ? 'system_error' : 'unexpected', 'mixed_checkout_create'); return; } const confirmed = http.post(`${config.baseUrl}/checkout-sessions/${created.json('id')}/confirm`, null, {headers, tags: {name: 'POST /checkout-sessions/{id}/confirm'}}); recordResult(confirmed.status === 200 && confirmed.json('checkoutSession.status') === 'RESERVED' ? 'success' : confirmed.status >= 500 || confirmed.status === 0 ? 'system_error' : 'unexpected', 'mixed_checkout_confirm'); }
export function paymentFlow() { const index = exec.scenario.iterationInTest; if (index >= orders.length) throw new Error(`mixed payment pool exhausted at ${index}`); const item = orders[index]; const session = sessions[item.sessionIndex]; const started = http.post(`${config.baseUrl}/orders/${item.orderId}/pay`, null, {headers: mutationHeaders(session), tags: {name: 'POST /orders/{orderId}/pay'}}); if (started.status !== 202 || started.json('disposition') !== 'STARTED_NEW') { recordResult(started.status >= 500 || started.status === 0 ? 'system_error' : 'unexpected', 'mixed_payment_start'); return; } const attemptId = started.json('paymentAttempt.id'); let success = false; for (let poll = 0; poll < 20; poll += 1) { sleep(1); const response = http.get(`${config.baseUrl}/payment-attempts/${attemptId}`, {headers: {Cookie: `ticketing_session=${session.sessionToken}`}, tags: {name: 'GET /payment-attempts/{id}'}}); if (response.status === 200 && response.json('status') === 'SUCCEEDED') { success = true; break; } if (response.status !== 200 || ['FAILED', 'TIMED_OUT'].includes(response.json('status'))) break; } recordResult(success ? 'success' : 'unexpected', 'mixed_payment_lifecycle'); }
export const handleSummary = summaryHandler(config);
