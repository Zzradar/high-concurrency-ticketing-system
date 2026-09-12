import { createRequire } from 'node:module';
import { writeFile } from 'node:fs/promises';
import path from 'node:path';
const [root, output] = process.argv.slice(2);
const require = createRequire(path.join(root, 'frontend/package.json'));
const { chromium } = require('@playwright/test');
const browser = await chromium.launch({ headless: false, channel: 'msedge' });
const context = await browser.newContext();
const page = await context.newPage();
const started = Date.now();
const records = [], errors = [];
page.on('pageerror', e => errors.push(e.message));
page.on('response', async r => {
 if (!r.url().includes('seat-availability')) return;
 try { const body = await r.json(); records.push({ atMs: Date.now()-started, url: r.url(), status: r.status(), mode: body.mode, changes: body.changes?.length, hasMore: body.hasMore }); }
 catch(e) { errors.push(String(e)); }
});
const phases=[];
try {
 await page.goto('http://127.0.0.1:18181/sessions/p18-s-5000/seats');
 await page.waitForResponse(r=>r.url().includes('seat-availability') && r.status()===200);
 phases.push({state:'visible',atMs:Date.now()-started});
 await page.waitForTimeout(60000);
 const cover = await context.newPage(); await cover.goto('about:blank'); await cover.bringToFront();
 const hidden = await page.evaluate(()=>document.hidden);
 phases.push({state:'hidden',confirmed:hidden,atMs:Date.now()-started});
 await page.waitForTimeout(10000);
 await page.bringToFront();
 phases.push({state:'foreground',atMs:Date.now()-started});
 await page.waitForTimeout(10000);
 if(!hidden)throw new Error('Real browser did not enter document.hidden; visibility evidence invalid');
 if(errors.length)throw new Error('Page or response errors occurred');
} finally {
 await writeFile(output,JSON.stringify({durationMs:Date.now()-started,phases,records,errors},null,2));
 await browser.close();
}
