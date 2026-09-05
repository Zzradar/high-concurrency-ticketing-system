import exec from 'k6/execution';
import http from 'k6/http';
import { loadConfig, SYSTEM_TAGS } from '../lib/config.js';
import { loadSessions, loadWorkloadSeats } from '../lib/data.js';
import { mutationHeaders } from '../lib/http.js';
import { recordResult } from '../lib/metrics.js';
import { correctnessThresholds, scenarioFor } from '../lib/scenarios.js';
import { summaryHandler } from '../lib/summary.js';

const config = loadConfig('checkout'); const sessions = loadSessions(); const seats = loadWorkloadSeats();
export const options = {systemTags: SYSTEM_TAGS, scenarios: scenarioFor(config.mode), thresholds: correctnessThresholds(config.mode)};
http.setResponseCallback(http.expectedStatuses(200, 201));
export default function () {
    const index = exec.scenario.iterationInTest;
    if (index >= seats.length || index >= sessions.length) throw new Error(`checkout pool exhausted: required index=${index}, available sessions=${sessions.length}, seats=${seats.length}`);
    const seat = seats[index]; const session = sessions[index]; const headers = mutationHeaders(session);
    const created = http.post(`${config.baseUrl}/checkout-sessions`, JSON.stringify({sessionId: seat.sessionId, seatIds: [seat.sessionSeatId]}), {headers, tags: {name: 'POST /checkout-sessions'}});
    if (created.status !== 201 || !created.json('id')) { recordResult(created.status >= 500 || created.status === 0 ? 'system_error' : 'unexpected', 'checkout_create'); return; }
    const confirmed = http.post(`${config.baseUrl}/checkout-sessions/${created.json('id')}/confirm`, null, {headers, tags: {name: 'POST /checkout-sessions/{id}/confirm'}});
    const valid = confirmed.status === 200 && confirmed.json('checkoutSession.status') === 'RESERVED' && confirmed.json('checkoutSession.order.id');
    recordResult(valid ? 'success' : confirmed.status >= 500 || confirmed.status === 0 ? 'system_error' : 'unexpected', 'checkout_confirm');
}
export const handleSummary = summaryHandler(config);
