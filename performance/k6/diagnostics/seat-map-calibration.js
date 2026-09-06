// Production-equivalent HTTP request; no backend serialization probe in load.
import http from 'k6/http';
import { Counter, Trend } from 'k6/metrics';
import { loadConfig, SYSTEM_TAGS } from '../lib/config.js';
import { loadDataset } from '../lib/data.js';
import { classifyRead, recordResult } from '../lib/metrics.js';
import { correctnessThresholds, scenarioFor } from '../lib/scenarios.js';
import { summaryHandler } from '../lib/summary.js';

const config = loadConfig('seat-map-calibration');
const dataset = loadDataset();
const encoding = __ENV.SEAT_MAP_ENCODING;
if (!['identity', 'gzip'].includes(encoding)) throw new Error('explicit encoding required');
const expectedHeld = Number(__ENV.EXPECTED_HELD);
const validateDisplay = expectedHeld > 0;
const heldCount = new Trend('ticketing_display_held_count');
const availableCount = new Trend('ticketing_display_available_count');
const soldCount = new Trend('ticketing_display_sold_count');
const exact = new Counter('ticketing_display_exact_total');
const degraded = new Counter('ticketing_display_degraded_total');
const invalid = new Counter('ticketing_display_invalid_total');
export const options = {
    discardResponseBodies: true, systemTags: SYSTEM_TAGS,
    scenarios: scenarioFor(config.mode),
    thresholds: {...correctnessThresholds(config.mode), ticketing_display_invalid_total: ['count==0']},
};
http.setResponseCallback(http.expectedStatuses(200));
function request(body, preflight = false) {
    return http.get(`${config.baseUrl}/sessions/${dataset.seatMapSessionId}/seats`, {
        headers: {'Accept-Encoding': encoding}, responseType: body ? 'text' : 'none',
        tags: {name: preflight ? 'GET /sessions/{sessionId}/seats preflight' : 'GET /sessions/{sessionId}/seats'},
    });
}
function counts(response) {
    const seats = response.json();
    if (!Array.isArray(seats) || seats.length !== 5000) throw new Error('seat count mismatch');
    const count = {HELD: 0, AVAILABLE: 0, SOLD: 0};
    for (const seat of seats) {
        if (!seat.id || seat.sessionId !== dataset.seatMapSessionId || !(seat.status in count))
            throw new Error('Seat Map contract mismatch');
        count[seat.status]++;
    }
    return count;
}
export function setup() {
    const response = request(true, true);
    const value = counts(response);
    if (response.status !== 200 || value.HELD !== expectedHeld || value.SOLD !== 0)
        throw new Error('seat-map calibration preflight failed');
    if ((response.headers['Content-Encoding'] === 'gzip') !== (encoding === 'gzip'))
        throw new Error('encoding mismatch');
}
export default function () {
    const response = request(validateDisplay);
    let result = classifyRead(response, 200, () => true);
    invalid.add(0);
    if (validateDisplay && response.status === 200) {
        try {
            const value = counts(response);
            heldCount.add(value.HELD); availableCount.add(value.AVAILABLE); soldCount.add(value.SOLD);
            const matches = value.HELD === expectedHeld && value.SOLD === 0;
            // A complete formal-state fallback is a display degradation, NOT
            // a successful temporary-state read and NOT proof of overselling.
            const fallback = value.HELD === 0 && value.AVAILABLE === 5000 && value.SOLD === 0;
            exact.add(matches ? 1 : 0); degraded.add(fallback ? 1 : 0);
            if (!matches && !fallback) { invalid.add(1); result = 'unexpected'; }
        } catch (_) { invalid.add(1); result = 'system_error'; }
    }
    recordResult(result, 'seat_map_read');
}
export const handleSummary = summaryHandler(config);
