import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import { pathToFileURL } from 'node:url';
import { startApp } from '../server.mjs';

const { chromium } = await import(process.env.M5_NODES_PLAYWRIGHT
  ? pathToFileURL(process.env.M5_NODES_PLAYWRIGHT).href : 'playwright');
const app = await startApp({ dataDir: 'data/concurrent-tabs-' + randomUUID(), standalone: true, relayEnabled: false });
let browser;
try {
  browser = await chromium.launch({ executablePath: process.env.M5_NODES_CHROMIUM });
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const pages = await Promise.all([context.newPage(), context.newPage()]);
  let bootstraps = 0;
  await context.route('**/api/trial-session/bootstrap', async route => {
    bootstraps++;
    // Model the round trip while both fresh tabs are trying to connect.
    await delay(250);
    await route.continue();
  });
  await Promise.all(pages.map(async page => {
    await page.goto(app.url + '/#workroom');
    await page.locator('#rail-menu').tap();
  }));
  // Native touch actions bring each tab to the foreground in sequence. Dispatch
  // both Start gestures together to exercise an overlapping navigation.
  const started = pages.map(page => page.waitForResponse(r =>
    ['/api/health', '/api/trial-session/bootstrap'].includes(new URL(r.url()).pathname)));
  await Promise.all(pages.map(page => page.locator('#demo-start').evaluate(button => button.click())));
  await Promise.all(started);
  assert.equal(bootstraps, 1, 'Opening two tabs together should create one browser session');
  for (const page of pages) {
    await page.waitForFunction(() => !document.querySelector('#refresh').disabled);
    const [tasks] = await Promise.all([
      page.waitForResponse(r => new URL(r.url()).pathname === '/api/tasks'),
      page.locator('#refresh').tap(),
    ]);
    assert.equal(tasks.status(), 200);
  }
  assert.equal(bootstraps, 1);
  console.log('Two phone-width tabs connected, one bootstrap, both boards refreshed.');
} finally {
  try { await browser?.close(); } finally { await app.close(); }
}
