// Run using the existing E2E Chromium dependency; does not modify frontend.
import { chromium } from '../../e2e/node_modules/playwright/index.mjs';

const browser = await chromium.launch();
try {
    const page = await browser.newPage();
    const url = 'http://127.0.0.1:18080/sessions/perf-session-001-001/seats';
    const response = await page.goto(url);
    const requestHeaders = await response.request().allHeaders();
    const responseHeaders = await response.allHeaders();
    const body = await response.json();
    const result = {
        browser: browser.version(), status: response.status(),
        acceptEncoding: requestHeaders['accept-encoding'] ?? null,
        contentEncoding: responseHeaders['content-encoding'] ?? null,
        contentLength: responseHeaders['content-length'] ?? null,
        seatCount: body.length,
        scope: 'real Chromium default network request; frontend functionality separately covered by E2E',
    };
    console.log(JSON.stringify(result, null, 2));
    if (result.status !== 200 || !Array.isArray(body) || !body.length ||
        !result.acceptEncoding?.includes('gzip') || result.contentEncoding !== 'gzip')
        throw new Error('browser Seat Map encoding/contract check failed');
} finally {
    await browser.close();
}
