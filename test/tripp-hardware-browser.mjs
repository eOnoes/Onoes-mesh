// Run with the Playwright and Chromium settings used by m5-nodes-browser.mjs.
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
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
let ollamaModels = [];
let connectionDenied = false;
let firstGpuTemperature = null;
// Both remote machines share the fixture's network clock, but have distinct sensors.
function withBox(view) {
  return {...view, nodes: [...view.nodes, {...view.nodes[1], id:'ai-box', label:'AI box',
    dnsName:'fixture.tail8c4a75.ts.net', tailscaleIp:'100.64.0.23'}],
    trippDesktop:connectionDenied ? {state:'unknown',source:'lan_ssh',reason:'connection_denied',ageMs:0} :
      {source:'lan_ssh',ollamaModels,strataHealth:'ready',strataLoaded:true,strataModel:'inkling',state:'online', ageMs:0, cpuTempC:51, gpuTempC:73, ramPct:31, cpuPct:0, gpuPct:77,
      gpus:[{index:0,name:'RTX 3060',tempC:firstGpuTemperature,usagePct:77},{index:1,name:'RTX 4080 SUPER',tempC:73,usagePct:0}]}};
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
  let candidateServed = false;
  if (process.env.M5_NODES_APP) {
    const body = readFileSync(process.env.M5_NODES_APP);
    await page.route(origin + '/app.js*', route => {
      candidateServed = true;
      return route.fulfill({contentType:'text/javascript', body});
    });
  }
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
  const tripp = page.locator('[data-node-id="tripp-pc"]');
  const box = page.locator('[data-node-id="ai-box"]');
  const boxMeters = box.locator('.pixel-readings');
  await check.tap();
  await boxMeters.waitFor({state:'visible'});
  for (const value of ['65%', '24%', '87%', '70 °C', '44 °C']) assert.ok((await boxMeters.innerText()).includes(value));
  await tripp.getByText('Ollama: No models loaded', {exact:true}).waitFor();
  await tripp.getByText('Strata IK2: Model loaded · inkling', {exact:true}).waitFor();
  await tripp.getByRole('heading',{name:'TEMP',exact:true}).waitFor();
  const gpuDetails = tripp.locator('details').filter({hasText:'Individual GPUs'});
  const firstGpu = gpuDetails.locator('.pixel-reading').filter({hasText:'GPU 0 · RTX 3060'});
  assert.equal(await firstGpu.isVisible(),false);
  await gpuDetails.locator('summary').tap();
  await firstGpu.waitFor();
  await firstGpu.getByText('77%', {exact:true}).waitFor();
  await firstGpu.getByText('Temperature unavailable', {exact:true}).waitFor();
  assert.equal(await firstGpu.locator('.thermal-gauge').getAttribute('class'), 'thermal-gauge');
  const secondGpu = gpuDetails.locator('.pixel-reading').filter({hasText:'GPU 1 · RTX 4080 SUPER'});
  await secondGpu.getByText('0%', {exact:true}).waitFor();
  await secondGpu.getByText('73 °C', {exact:true}).waitFor();
  assert.equal(await secondGpu.locator('.thermal-6').count(), 1);
  const overview = tripp.locator(':scope > .pixel-readings');
  for (const reading of ['31%', '0%', '77%', '51 °C', '73 °C', 'GPU peaks'])
    await overview.getByText(reading,{exact:true}).waitFor();
  assert.equal(await tripp.locator('.thermal-gauge').count(),4);
  assert.equal(await page.locator('[data-node-id="laptop"]').count(),0);
  assert.doesNotMatch(await tripp.innerText(), /Hermes|ChatGPT|Claude|42%|58 °C/);
  ollamaModels = [
    'hf.co/example/Qwen3.8-Flash-Next-GGUF:IQ3_S',
    'local/Qwen3.8-Flash-Next-Q4_K_M.gguf:latest',
    'registry.ollama.ai/library/gemma3:12b',
  ];
  firstGpuTemperature = 49;
  await check.tap();
  const modelSummary = tripp.locator('summary').filter({hasText:'Ollama:'});
  await modelSummary.waitFor();
  await firstGpu.getByText('49 °C', {exact:true}).waitFor();
  assert.equal(await firstGpu.locator('.thermal-4').count(), 1);
  assert.equal(await firstGpu.isVisible(), true);
  assert.equal(await modelSummary.innerText(), 'Ollama: Qwen3.8-Flash-Next (2), gemma3:12b');
  assert.equal(await tripp.getByText(ollamaModels[0], {exact:true}).isVisible(), false);
  await modelSummary.tap();
  for (const tag of ollamaModels) await tripp.getByText(tag, {exact:true}).waitFor();
  await page.clock.fastForward(2000);
  assert.equal(await tripp.getByText(ollamaModels[0], {exact:true}).isVisible(), true);
  await page.setViewportSize({width:320, height:640});
  for (let theme = 0; theme < 2; theme++) {
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), true);
    assert.equal(await gpuDetails.evaluate(el => el.scrollWidth <= el.clientWidth + 1), true);
    await page.locator('#theme-toggle').tap();
  }
  await page.setViewportSize({width:390, height:844});
  await page.clock.fastForward(31000);
  await box.getByText('Hardware readings unavailable').waitFor();
  await tripp.getByText('LAN · Check expired. Tap Check machine status to refresh.', {exact:true}).waitFor();
  await tripp.getByText('Strata IK2: Status unavailable', {exact:true}).waitFor();
  assert.doesNotMatch(await tripp.innerText(), /inkling/i);
  assert.equal(await firstGpu.count(),0);
  assert.equal(await gpuDetails.isVisible(),false);
  assert.equal(await tripp.getByText(ollamaModels[0], {exact:true}).count(), 0);
  assert.doesNotMatch(await tripp.innerText(),/31%|77%|51 °C/);
  assert.equal(await boxMeters.count(),0);
  connectionDenied = true;
  boxSensorsAvailable = false;
  await Promise.all([page.waitForResponse(origin + '/api/node-probes/refresh'), check.tap()]);
  assert.equal(await boxMeters.count(),0);
  await tripp.getByText('LAN · Connection denied', {exact:true}).waitFor();
  await tripp.getByText('Ollama: Status unavailable', {exact:true}).waitFor();
  assert.doesNotMatch(await tripp.innerText(), /Offline|Qwen|31%|77%/);
  connectionDenied = false;
  fixture.offline();
  fixture.advance(61000);
  await check.tap();
  await box.getByText('Offline', {exact:true}).waitFor();
  assert.doesNotMatch(await tripp.innerText(),/Offline/);

  holdRefresh = true;
  await Promise.all([page.waitForRequest(origin + '/api/node-probes/refresh'), check.tap()]);
  await page.clock.fastForward(16000);
  await page.getByText(/Machine check timed out/).first().waitFor();
  assert.equal(await check.isEnabled(), true);
  assert.equal(await page.locator('#demo-end').isEnabled(), true);
  assert.equal(requests, 5);
  await menu.tap();
  await page.locator('#tab-workroom').tap();
  await page.getByRole('button', { name: '+ New task', exact: true }).tap();
  await page.locator('#create-title').waitFor({ state: 'visible' });
  if (process.env.M5_NODES_APP) assert.equal(candidateServed, true);
  console.log('PASS: per-GPU readings, both phone themes, Tripp data separate from laptop data, expiry, and Workroom after timeout.');
} finally {
  await browser?.close();
  await app.close();
}
