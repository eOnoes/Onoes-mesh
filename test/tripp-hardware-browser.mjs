// Run with the Playwright and Chromium settings used by m5-nodes-browser.mjs.
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import { pathToFileURL } from 'node:url';
import { startApp } from '../server.mjs';
import { createNodeProbeReader } from '../lib/node-probes.mjs';
import { withRemoteHardware } from '../lib/tripp-hardware.mjs';
import { controlledProbe } from './m5-nodes-fixture.mjs';

const { chromium } = await import(process.env.M5_NODES_PLAYWRIGHT
  ? pathToFileURL(process.env.M5_NODES_PLAYWRIGHT).href : 'playwright');
const fixture = controlledProbe();
const network = createNodeProbeReader(fixture.options);
// Both remote machines share the fixture's network clock, but have distinct sensors.
function withBox(view) {
  return {...view, nodes: [...view.nodes, {...view.nodes[1], id:'ai-box', label:'AI box',
    dnsName:'fixture.tail8c4a75.ts.net', tailscaleIp:'100.64.0.23'}]};
}
let boxSensorsAvailable = true;
const reader = withRemoteHardware({
  snapshot: () => withBox(network.snapshot()),
  refresh: async () => withBox(await network.refresh()),
}, {
  laptop: true, aiBoxHost:'PRINT-HOST',
  clock: fixture.options.clock,
  sample: async node => {
    if (node.id === 'ai-box') {
      if (!boxSensorsAvailable) throw Error('Fixture sensor unavailable');
      return {ramPct:65, cpuPct:24, gpuPct:87, gpuTempC:70, cpuTempC:44};
    }
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
  const box = page.locator('[data-node-id="ai-box"]');
  await check.tap();
  await meters.waitFor({ state: 'visible' });
  for (const value of ['36%', '17%', '42%']) assert.ok((await meters.innerText()).includes(value));
  assert.match(await laptop.innerText(), /Model loaded: Unknown/);
  const boxMeters = box.locator('.pixel-readings');
  for (const value of ['65%', '24%', '87%', '70 °C', '44 °C']) assert.ok((await boxMeters.innerText()).includes(value));
  assert.match(await box.innerText(), /Model loaded: Unknown/);
  boxSensorsAvailable = false;
  await check.tap();
  await box.getByText('Hardware readings unavailable').waitFor();
  assert.equal(await boxMeters.count(), 0);
  assert.ok((await meters.innerText()).includes('42%'));
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
  assert.equal(requests, 4);
  await menu.tap();
  await page.locator('#tab-workroom').tap();
  await page.getByRole('button', { name: '+ New task', exact: true }).tap();
  await page.locator('#create-title').waitFor({ state: 'visible' });
  console.log('PASS: distinct remote readings, isolated sensor failure, expiry, offline and Workroom after timeout.');
} finally {
  await browser?.close();
  await app.close();
}
