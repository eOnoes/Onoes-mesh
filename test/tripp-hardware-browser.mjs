// Run with the Playwright and Chromium settings used by m5-nodes-browser.mjs.
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import { pathToFileURL } from 'node:url';
import { startApp } from '../server.mjs';
import { createNodeProbeReader } from '../lib/node-probes.mjs';
import { withTrippHardware } from '../lib/tripp-hardware.mjs';
import { controlledProbe } from './m5-nodes-fixture.mjs';

const { chromium } = await import(process.env.M5_NODES_PLAYWRIGHT
  ? pathToFileURL(process.env.M5_NODES_PLAYWRIGHT).href : 'playwright');
const fixture = controlledProbe();
const reader = withTrippHardware(createNodeProbeReader(fixture.options), {
  clock: fixture.options.clock,
  sample: async () => {
    await delay(3100);
    return { ramPct: 36, cpuPct: 17, gpuPct: 42, gpuTempC: 58, cpuTempC: null };
  },
});
const app = await startApp({ dataDir: 'data/tripp-phone-' + randomUUID(), standalone: true, relayEnabled: false });
let browser;
try {
  browser = await chromium.launch({ executablePath: process.env.M5_NODES_CHROMIUM });
  const page = await browser.newPage({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  page.setDefaultTimeout(6500);
  await page.clock.install();
  const origin = new URL(app.url).origin;
  await page.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort());
  await page.route(origin + '/api/node-probes', route => route.fulfill({ json: reader.snapshot() }));
  let holdRefresh = false, requests = 0;
  await page.route(origin + '/api/node-probes/refresh', async route => {
    requests++;
    if (!holdRefresh) await route.fulfill({ json: await reader.refresh() });
  });
  await page.goto(origin + '/#inference');
  const menu = page.locator('#rail-menu');
  await menu.tap();
  await page.locator('#demo-start').tap();
  await page.waitForFunction(() => !document.getElementById('refresh').disabled);
  await page.locator('#tab-inference').tap();
  const check = page.locator('#node-probes-refresh');
  await page.getByText('Other machines', { exact: true }).tap();
  const laptop = page.locator('[data-node-id="laptop"]');
  const meters = laptop.locator('.pixel-readings');
  await check.tap();
  await meters.waitFor({ state: 'visible' });
  for (const value of ['36%', '17%', '42%']) assert.ok((await meters.innerText()).includes(value));
  assert.match(await laptop.innerText(), /Model loaded: Unknown/);
  await page.clock.fastForward(31000);
  await laptop.getByText('Hardware readings unavailable').waitFor();
  assert.equal(await meters.count(), 0);
  fixture.offline();
  fixture.advance(61000);
  await check.tap();
  await laptop.getByText('Offline', { exact: true }).waitFor();
  assert.equal(await meters.count(), 0);

  holdRefresh = true;
  await Promise.all([page.waitForRequest(origin + '/api/node-probes/refresh'), check.tap()]);
  await page.clock.fastForward(16000);
  await page.getByText(/Machine check timed out/).first().waitFor();
  assert.equal(await check.isEnabled(), true);
  assert.equal(await page.locator('#demo-end').isEnabled(), true);
  assert.equal(requests, 3);
  await menu.tap();
  await page.locator('#tab-workroom').tap();
  await page.getByRole('button', { name: '+ New task', exact: true }).tap();
  await page.locator('#create-title').waitFor({ state: 'visible' });
  console.log('PASS: slow sample displayed, stale and offline meters cleared, Workroom opened after timeout.');
} finally {
  await browser?.close();
  await app.close();
}
