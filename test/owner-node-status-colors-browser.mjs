// Actual Chromium/DOM/CSS on disposable loopback only; controlled probe data,
// never owner-origin or native Tailscale evidence. Busy is a synthetic mapping check.
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { writeFile } from 'node:fs/promises';
import { once } from 'node:events';
import { startApp, ROOT } from '../server.mjs';
import { controlledProbe } from './m5-nodes-fixture.mjs';

const { chromium } = await import('file:///C:/Users/eMitchell109/AppData/Local/hermes/hermes-agent/node_modules/playwright-core/index.mjs');
const dataDir = `test/app03-owner-node-status-colors-${randomUUID()}`;
const tx = controlledProbe();
const app = await startApp({ dataDir, relayEnabled: false, nodeProbeTestOptions: tx.options });
const proof = { provenance: 'Actual disposable loopback Chromium; controlled probe stream/clock, no live tailnet or busy telemetry',
  dataDir, url: app.url, cases: [], errors: [], busyContract: 'No runtime busy telemetry established' };
let browserServer, browser, browserProcess, browserClosed;
try {
  browserServer = await chromium.launchServer({ headless: true, host: '127.0.0.1',
    executablePath: 'C:/Users/eMitchell109/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe' });
  browserProcess = browserServer.process();
  browserClosed = once(browserProcess, 'close');
  proof.browser = { pid: browserProcess.pid, executable: browserProcess.spawnfile, argv: browserProcess.spawnargs };
  browser = await chromium.connect(browserServer.wsEndpoint());
  for (const viewport of [{ width: 390, height: 844 }, { width: 1440, height: 1000 }]) {
    const context = await browser.newContext({ viewport, isMobile: viewport.width === 390,
      hasTouch: viewport.width === 390, serviceWorkers: 'block' });
    const page = await context.newPage();
    page.setDefaultTimeout(10000);
    page.on('pageerror', error => proof.errors.push(error.message));
    await page.goto(app.url);
    assert.equal(await page.locator('#node-probes-refresh').isDisabled(), true);
    await page.locator('#demo-start').click();
    await page.waitForFunction(() => !document.getElementById('refresh').disabled);
    assert.match(await page.locator('#demo-state').innerText(), /Local task access verified by server/);
    proof.cases.push({ viewport, stage: 'explicit local Start', banner: await page.locator('#demo-state').innerText() });
    await page.locator('#tab-inference').click();
    const response = page.waitForResponse(r => new URL(r.url()).pathname === '/api/node-probes/refresh');
    await page.locator('#node-probes-refresh').click();
    const reply = await response; assert.equal(reply.status(), 200);
    const snapshot = await reply.json();
    assert.equal(snapshot.source, 'disposable_transport');
    await page.waitForFunction(() => document.querySelector('.node-status')?.textContent === 'Online');
    const inspect = async (stage, label, color, state) => {
      const rows = await page.locator('#tailnet-nodes article').evaluateAll(cards => cards.map(card => {
        const word = card.querySelector('.node-status');
        return { id: card.dataset.nodeId, text: card.innerText, word: word.textContent, classes: word.className,
          color: getComputedStyle(word).color, paragraphColor: getComputedStyle(word.parentElement).color,
          paragraphClass: word.parentElement.className, inlineStyles: card.querySelectorAll('[style]').length };
      }));
      assert.equal(rows.length, 2);
      rows.forEach(row => {
        assert.equal(row.word, label); assert.equal(row.color, color);
        assert.equal(row.classes, 'node-status node-status--' + state);
        assert.equal(row.paragraphColor, 'rgb(176, 176, 182)');
        assert.equal(row.paragraphClass, ''); assert.equal(row.inlineStyles, 0);
        assert.match(row.text, /Packet reachability: unknown · Inference readiness: unknown · Model readiness: unknown/);
        assert.match(row.text, /TEST ONLY: controlled transport; no native tailnet claim/);
      });
      proof.cases.push({ viewport, stage, rows });
    };
    await inspect('API ready => Online', 'Online', 'rgb(57, 255, 20)', 'online');
    // Only local presentation time is advanced; retain original API timestamps/fields.
    const render = async (value, age = 0) => page.evaluate(async ({ value, age }) => {
      const { renderNodeProbes } = await import('/app.js');
      renderNodeProbes(value, performance.now() - age);
    }, { value, age });
    await render(structuredClone(snapshot), snapshot.limits.freshMs + 1);
    await inspect('local aging => Stale', 'Stale', 'rgb(255, 191, 105)', 'stale');
    await render(structuredClone(snapshot), snapshot.limits.staleGraceMs + 1);
    await inspect('local aging => Offline', 'Offline', 'rgb(255, 107, 107)', 'offline');
    await page.screenshot({ path: `${ROOT}/${dataDir}/offline-${viewport.width}.png`, fullPage: true });
    for (const [status, label, color, state] of [['busy', 'Busy', 'rgb(255, 209, 102)', 'busy'],
      ['unknown', 'unknown', 'rgb(176, 176, 182)', 'neutral'],
      ['unavailable', 'Unavailable', 'rgb(176, 176, 182)', 'neutral'],
      ['not_configured', 'not_configured', 'rgb(176, 176, 182)', 'neutral']]) {
      const supplied = structuredClone(snapshot); supplied.nodes.forEach(n => { n.status = status; });
      await render(supplied);
      await inspect('synthetic explicit status mapping: ' + status, label, color, state);
    }
    const unavailable = structuredClone(snapshot);
    unavailable.nodes.forEach(n => { n.observationAvailability = 'unavailable'; });
    await render(unavailable);
    await inspect('unavailable cached Online stays neutral', 'Online', 'rgb(176, 176, 182)', 'neutral');
    assert.match(await page.locator('#tailnet-nodes').innerText(), /Observation unavailable · cached status: Online · offline not established by this read/);
    await render(structuredClone(unavailable), snapshot.limits.staleGraceMs + 1);
    await inspect('unavailable cached Offline stays neutral', 'Offline', 'rgb(176, 176, 182)', 'neutral');
    await page.locator('#demo-end').click();
    await page.waitForFunction(() => document.querySelectorAll('#tailnet-nodes article').length === 0);
    assert.equal(await page.locator('#node-probes-refresh').isDisabled(), true);
    await context.close();
  }
  assert.equal(tx.calls.length, 2, 'only two explicit refreshes; presentation and aging never probe');
  assert.equal(proof.errors.length, 0);
  proof.result = 'PASS';
} catch (error) {
  proof.result = 'FAIL'; proof.failure = error.stack; throw error;
} finally {
  if (browser) await browser.close();
  if (browserServer) await browserServer.close();
  if (browserClosed) await browserClosed;
  await app.close();
  proof.cleanup = { listenerClosed: true, disposableDataRetained: true, browserPid: browserProcess?.pid,
    originalBrowserExitCode: browserProcess?.exitCode, originalBrowserSignalCode: browserProcess?.signalCode };
  if (browserProcess) assert.ok(browserProcess.exitCode !== null || browserProcess.signalCode !== null);
  await writeFile(`${ROOT}/${dataDir}/browser-proof.json`, JSON.stringify(proof, null, 2));
  console.log(JSON.stringify({ evidence: `${dataDir}/browser-proof.json`, result: proof.result, cleanup: proof.cleanup }));
}
