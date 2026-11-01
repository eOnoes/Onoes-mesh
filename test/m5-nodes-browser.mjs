// Real Chromium at phone dimensions, disposable stores, fixed native CLI only.
// M5_NODES_PLAYWRIGHT points to an installed playwright-core/index.mjs;
// M5_NODES_CHROMIUM optionally selects its installed Chromium executable.
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { writeFile } from 'node:fs/promises';
import { ChildProcess, execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';
import { startApp, ROOT } from '../server.mjs';
import { controlledProbe } from './m5-nodes-fixture.mjs';
import { TAILSCALE_EXECUTABLE } from '../lib/node-probes.mjs';

const { chromium } = await import(process.env.M5_NODES_PLAYWRIGHT
  ? pathToFileURL(process.env.M5_NODES_PLAYWRIGHT).href : 'playwright');
const dataDir = `test/app03-m5-nodes-browser-${randomUUID()}`;
const native = await startApp({ dataDir, relayEnabled: false });
const evidence = { viewport: { width: 390, height: 844 }, dataDir, nativeUrl: native.url, native: [], controlled: [], processes: [], errors: [] };
let browserServer, browser, controlled;
let browserProcess;
const nativeChildren = [];
const originalSpawn = ChildProcess.prototype.spawn;
// Observe the original fixed native children for custody only. No substituted
// transport, argv, environment, timing or module changes; native provenance stays.
ChildProcess.prototype.spawn = function (options) {
  const result = originalSpawn.call(this, options);
  if (this.spawnfile === TAILSCALE_EXECUTABLE) nativeChildren.push(this);
  return result;
};
const receipts = () => {
  // Query only known owned PIDs. WMI inventory is sandbox-denied here;
  // retained ChildProcess handles supply the browser executable/argv and exit.
  const ids = [process.pid, browserProcess?.pid, ...nativeChildren.map(c => c.pid)].filter(Boolean);
  const script = '@(' + ids.join(',') + ") | ForEach-Object { $p = Get-Process -Id $_ -ErrorAction SilentlyContinue; if ($p) { [pscustomobject]@{pid=$p.Id;created=$p.StartTime.ToUniversalTime().ToString('o')} } } | ConvertTo-Json -Compress";
  const raw = execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], { windowsHide: true, encoding: 'utf8' }).trim();
  const times = raw ? JSON.parse(raw) : [];
  return { nativeCreationTimes: times, identities: [
    { pid: process.pid, executable: process.execPath, argv: process.argv, purpose: 'M5 disposable API servers and browser test' },
    ...(browserProcess ? [{ pid: browserProcess.pid, executable: browserProcess.spawnfile, argv: browserProcess.spawnargs,
      purpose: 'Owned 390x844 Chromium regression browser', exitCode: browserProcess.exitCode, signalCode: browserProcess.signalCode }] : []),
    ...nativeChildren.map(c => ({ pid: c.pid, executable: c.spawnfile, argv: c.spawnargs,
      purpose: 'Original fixed read-only Tailscale status child', exitCode: c.exitCode, signalCode: c.signalCode }))
  ], limitation: 'WMI process inventory denied; no shared process inspection/termination' };
};
const save = () => writeFile(`${ROOT}/${dataDir}/browser-proof.json`, JSON.stringify(evidence, null, 2));
const card = (page, id) => page.locator(`#tailnet-nodes [data-node-id="${id}"]`);
async function matches(page, snapshot) {
  for (const n of snapshot.nodes) {
    const text = await card(page, n.id).innerText();
    for (const value of [n.label, n.id, n.dnsName, n.tailscaleIp, n.lastProbeAt ?? 'never', n.lastSuccessAt ?? 'never']) assert.ok(text.includes(value), value);
    assert.ok(text.includes(n.observationAvailability)); assert.ok(text.includes(snapshot.source));
    assert.ok(text.includes(({ ready: 'Online', offline: 'Offline', stale: 'Stale' })[n.status] ?? n.status));
    if (n.observationAvailability === 'unavailable') assert.ok(text.includes('offline not established'));
    else assert.ok(text.includes('cached Tailscale Online: ' + n.tailscaleOnline));
    assert.ok(text.includes('Packet reachability: unknown')); assert.ok(text.includes('Inference readiness: unknown')); assert.ok(text.includes('Model readiness: unknown'));
    assert.equal(n.capabilities.control, false); assert.equal(n.capabilities.inference, false);
  }
  assert.equal(await page.locator('#panel-inference button').count(), 1, 'only the read-only refresh action');
}
async function start(page, url) {
  await page.goto(url); assert.equal(await page.locator('#node-probes-refresh').isDisabled(), true);
  await page.locator('#demo-start').click(); await page.waitForFunction(() => !document.getElementById('refresh').disabled);
  await page.locator('#tab-inference').click();
}
async function refresh(page) {
  const reply = page.waitForResponse(r => new URL(r.url()).pathname === '/api/node-probes/refresh');
  await page.locator('#node-probes-refresh').click(); const response = await reply;
  assert.equal(response.status(), 200); assert.equal(response.headers()['cache-control'], 'no-store');
  const snapshot = await response.json();
  await page.waitForFunction(at => document.getElementById('tailnet-nodes').textContent.includes(at), snapshot.nodes[0].lastProbeAt);
  await matches(page, snapshot); return snapshot;
}
try {
  browserServer = await chromium.launchServer({ headless: true, host: '127.0.0.1',
    ...(process.env.M5_NODES_CHROMIUM ? { executablePath: process.env.M5_NODES_CHROMIUM } : {}) });
  browserProcess = browserServer.process();
  browser = await chromium.connect(browserServer.wsEndpoint());
  const context = await browser.newContext({ viewport: evidence.viewport, isMobile: true, hasTouch: true, serviceWorkers: 'block' });
  const page = await context.newPage(); page.setDefaultTimeout(10000); page.on('pageerror', e => evidence.errors.push(e.message));
  await start(page, native.url);
  evidence.processes.push({ stage: 'browser running', identities: receipts() });
  const requests = []; page.on('request', r => { if (r.url().includes('/api/node-probes')) requests.push({ url: r.url(), method: r.method(), body: r.postData() }); });
  const read = refresh(page);
  for (let n = 0; n < 100 && !nativeChildren.length; n++) await page.waitForTimeout(5);
  assert.equal(nativeChildren.length, 1, 'one original fixed CLI child');
  // Capture any still-running fixed status child, including a sandbox timeout.
  evidence.processes.push({ stage: 'fixed native probe in flight', identities: receipts() });
  const actual = await read; assert.equal(actual.source, 'native_tailscale_cli'); evidence.native.push(actual);
  await page.screenshot({ path: `${ROOT}/${dataDir}/native-390x844.png`, fullPage: true });
  const nativeRequests = requests.length;
  await page.waitForTimeout(1100); assert.equal(requests.length, nativeRequests, 'local aging makes no request');
  await page.locator('#demo-end').click(); await page.waitForFunction(() => document.querySelectorAll('#tailnet-nodes article').length === 0);
  assert.equal(await page.locator('#node-probes-refresh').isDisabled(), true);
  assert.ok(!(await page.locator('#tailnet-nodes').innerText()).includes(actual.nodes[0].dnsName));
  await context.close();

  const tx = controlledProbe();
  const controlledDir = `test/app03-m5-nodes-controlled-${randomUUID()}`;
  controlled = await startApp({ dataDir: controlledDir, relayEnabled: false, nodeProbeTestOptions: tx.options });
  evidence.controlledDir = controlledDir;
  const ctx = await browser.newContext({ viewport: evidence.viewport, isMobile: true, hasTouch: true, serviceWorkers: 'block' });
  const p = await ctx.newPage(); p.setDefaultTimeout(10000); p.on('pageerror', e => evidence.errors.push(e.message));
  await start(p, controlled.url);
  const ready = await refresh(p); evidence.controlled.push(ready);
  tx.advance(1000); tx.offline(); const stale = await refresh(p); evidence.controlled.push(stale);
  assert.equal(stale.nodes[1].lastSuccessAt, ready.nodes[1].lastSuccessAt);
  tx.advance(59000);
  await p.locator('#refresh').click(); await p.waitForFunction(() => !document.getElementById('refresh').disabled);
  assert.match(await card(p, 'laptop').innerText(), /Status: Offline/);
  assert.equal(tx.calls.length, 2, 'global cache refresh does not probe');
  tx.fail(); const unavailable = await refresh(p); evidence.controlled.push(unavailable);
  assert.equal(unavailable.nodes[1].lastSuccessAt, ready.nodes[1].lastSuccessAt);
  assert.match(await card(p, 'laptop').innerText(), /Observation unavailable.*offline not established/);

  // Clock advancement exercises only the local display timer, never the CLI.
  await p.evaluate(async snapshot => {
    window.m5Module = await import('/app.js'); window.m5Module.renderNodeProbes(snapshot, performance.now() - 30001);
  }, ready);
  assert.match(await card(p, 'pc').innerText(), /Status: Stale/);
  await p.evaluate(snapshot => window.m5Module.renderNodeProbes(structuredClone(snapshot), performance.now() - 60001), ready);
  assert.match(await card(p, 'pc').innerText(), /Status: Offline/);
  await p.waitForTimeout(1100); assert.equal(tx.calls.length, 3);
  assert.ok((await card(p, 'pc').innerText()).includes(ready.nodes[0].lastSuccessAt));
  await p.screenshot({ path: `${ROOT}/${dataDir}/controlled-aging-390x844.png`, fullPage: true });

  // Hold a real API response in the browser while the page clears its proof.
  let release, intercepted;
  const hold = new Promise(r => { release = r; }); const started = new Promise(r => { intercepted = r; });
  await p.route('**/api/node-probes/refresh', async route => {
    const response = await route.fetch(); intercepted(); await hold; await route.fulfill({ response });
  });
  await p.locator('#node-probes-refresh').click(); await started;
  await p.evaluate(() => window.dispatchEvent(new Event('offline')));
  assert.equal(await p.locator('#tailnet-nodes article').count(), 0);
  await p.waitForTimeout(20); release(); await p.waitForTimeout(200);
  assert.equal(await p.locator('#tailnet-nodes article').count(), 0, 'late reply cannot restore private nodes');
  await p.unroute('**/api/node-probes/refresh');
  await ctx.close();
  evidence.requests = requests; assert.equal(evidence.errors.length, 0);
  evidence.result = 'PASS: native API-to-DOM equality; controlled aging and delayed private clearance';
} finally {
  if (browser) await browser.close();
  if (browserServer) await browserServer.close();
  if (controlled) await controlled.close(); await native.close();
  ChildProcess.prototype.spawn = originalSpawn;
  evidence.cleanup = { browserPid: browserProcess?.pid, originalBrowserExitCode: browserProcess?.exitCode,
    originalBrowserSignal: browserProcess?.signalCode, appListenersClosed: true, disposableDataRetained: true,
    nativeChildren: nativeChildren.map(c => ({ pid: c.pid, executable: c.spawnfile, argv: c.spawnargs,
      exitCode: c.exitCode, signalCode: c.signalCode })) };
  evidence.processes.push({ stage: 'after close', identities: receipts() });
  if (browserProcess) assert.ok(browserProcess.exitCode !== null || browserProcess.signalCode !== null, 'original browser process exited');
  for (const c of nativeChildren) assert.ok(c.exitCode !== null || c.signalCode !== null, 'original fixed CLI child exited');
  await save(); console.log(JSON.stringify({ evidence: `${dataDir}/browser-proof.json`, result: evidence.result, native: evidence.native, cleanup: evidence.cleanup }));
}
