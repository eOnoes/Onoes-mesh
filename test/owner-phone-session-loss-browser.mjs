// Existing native Playwright/Relay fixture lane, always unique disposable stores.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createInterface } from 'node:readline';
import { createHash, randomUUID } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { startApp, ROOT } from '../server.mjs';

if (process.argv.includes('--serve')) {
  const app = await startApp({ dataDir: process.env.MESH_DATA_DIR, sessionTtlMs: 300000, relayEnabled: true });
  console.log(JSON.stringify({ event: 'mesh_listening', pid: process.pid, url: app.url }));
  process.stdin.once('end', async () => { await app.close(); process.exitCode = 0; });
  process.stdin.resume();
} else {
  const desktop = process.argv.includes('--desktop');
  const red = process.argv.includes('--red');
  const mode = (red ? 'red' : 'green') + (desktop ? '-desktop' : '-mobile');
  const dataDir = `test/app03-owner-phone-session-recovery-${mode}-${randomUUID()}`;
  const dir = path.join(ROOT, dataDir); await mkdir(dir, { recursive: true });
  const evidence = { mode, dataDir, stages: [], requests: [], responses: [], errors: [], freshness: {}, limitations: ['Chromium mobile emulation with touch, not Android, in-app browser or physical owner phone.', 'Physical triggering event UNKNOWN; parent private8446 trusted lifecycle trace remains required review input.'] };
  const hash = bytes => createHash('sha256').update(bytes).digest('hex');
  let browserServer, browser, observer, observedExit, child, output = '', errors = '', observerErrors = '';
  const records = [];
  console.log('EVIDENCE ' + dir);
  try {
    child = spawn(process.execPath, [path.join(ROOT, 'test/owner-phone-session-loss-browser.mjs'), '--serve'], { cwd: ROOT, windowsHide: true, env: { ...process.env, MESH_DATA_DIR: dataDir }, stdio: ['pipe', 'pipe', 'pipe'] });
    child.stderr.on('data', b => { errors += b; });
    const info = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(Error('Disposable startup deadline: ' + errors)), 8000);
      child.once('error', e => { clearTimeout(timer); reject(e); });
      child.once('exit', code => { clearTimeout(timer); reject(Error('Disposable startup exit ' + code)); });
      child.stdout.on('data', b => {
        output += b;
        const v = output.split('\n').flatMap(l => { try { return [JSON.parse(l)]; } catch { return []; } }).find(v => v.event === 'mesh_listening');
        if (v) { clearTimeout(timer); resolve(v); }
      });
    });
    evidence.url = info.url;
    const relay = output.split('\n').flatMap(l => { try { return [JSON.parse(l)]; } catch { return []; } }).find(v => v.event === 'mesh_relay_listening');
    assert.ok(relay, 'Hydrated isolated Relay required');
    const { chromium } = await import(pathToFileURL('C:/Users/eMitchell109/AppData/Local/hermes/hermes-agent/node_modules/playwright-core/index.mjs').href);
    browserServer = await chromium.launchServer({ executablePath: 'C:/Users/eMitchell109/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe', headless: true });
    browser = await chromium.connect(browserServer.wsEndpoint());
    // Existing retained-handle observer proves original native exits, including Relay.
    const ids = [child.pid, relay.pid, browserServer.process().pid];
    evidence.owned = ids;
    observer = spawn('C:/Python314/python.exe', ['-I', '-B', path.join(ROOT, 'test/m4-link-process-observer.py'), ...ids.map(String)], { cwd: ROOT, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] });
    observer.stderr.on('data', b => { observerErrors += b; });
    observedExit = once(observer, 'exit');
    const lines = createInterface({ input: observer.stdout });
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(Error('Native handle acquisition deadline: ' + observerErrors)), 3000);
      observer.once('error', e => { clearTimeout(timer); reject(e); });
      lines.on('line', line => { const v = JSON.parse(line); records.push(v); if (v.event === 'held') { clearTimeout(timer); resolve(); } });
    });
    const viewport = desktop ? { width: 1440, height: 1000 } : { width: 390, height: 844 };
    evidence.viewport = viewport;
    const context = await browser.newContext({ viewport, isMobile: !desktop, hasTouch: !desktop });
    const page = await context.newPage(); page.setDefaultTimeout(6000);
    page.on('pageerror', e => evidence.errors.push(e.message));
    page.on('request', r => { const route = new URL(r.url()).pathname; if (route.startsWith('/api/')) { const h = r.headers(); evidence.requests.push({ route, method: r.method(), cookiePresent: Boolean(h.cookie), proofPresent: Boolean(h['x-trial-csrf']) }); } });
    page.on('response', r => { const route = new URL(r.url()).pathname; if (route.startsWith('/api/')) evidence.responses.push({ route, status: r.status(), noStore: r.headers()['cache-control'] === 'no-store' }); });
    const loaded = new Map();
    page.on('response', r => { if (['/', '/app.js'].includes(new URL(r.url()).pathname)) loaded.set(new URL(r.url()).pathname, r); });
    const ready = () => page.waitForFunction(() => !document.getElementById('refresh').disabled);
    const cleared = async () => {
      assert.equal(await page.locator('#tasks button').count(), 0);
      assert.equal(await page.locator('#task-identity').textContent(), '');
      assert.equal(await page.locator('#execution-result').textContent(), '');
      assert.equal(await page.locator('#relay-terminal').getAttribute('srcdoc'), '');
      assert.equal(await page.locator('#relay-text').inputValue(), '');
      assert.ok(await page.locator('#relay-text').isDisabled());
      assert.equal(await page.evaluate(() => sessionStorage.length), 0);
      assert.equal(await page.evaluate(() => localStorage.length), 0);
    };
    await page.goto(info.url);
    await page.locator('#demo-start').click(); await ready();
    await page.locator('#tab-workroom').click();
    const title = 'Disposable session recovery task';
    await page.locator('#create-title').fill(title); await page.locator('#create-form button').click();
    await page.waitForFunction(() => document.getElementById('message').textContent.includes('Task created'));
    assert.equal(await page.locator('#tasks button').count(), 1);
    await page.locator('#tasks button').click();
    assert.equal(await page.locator('#edit-title').inputValue(), title);
    for (const id of ['approve-command','deny-command','cancel-command']) assert.ok(await page.locator('#' + id).isDisabled());
    const expiresAt = await page.evaluate(() => JSON.parse(sessionStorage.getItem('mesh.synthetic-demo.proof.v1')).expiresAt);
    evidence.transport = { cookie: (await context.cookies()).map(({ name, httpOnly, sameSite }) => ({ name, httpOnly, sameSite })), scriptCookieEmpty: await page.evaluate(() => document.cookie === ''), storedProofPresent: await page.evaluate(() => sessionStorage.length === 1) };
    assert.equal(evidence.transport.scriptCookieEmpty, true);
    assert.equal(evidence.transport.cookie[0].httpOnly, true);
    evidence.stages.push({ stage: 'admitted-task-visible-selectable' });
    const identity = await page.locator('#task-identity').textContent();
    const cdp = await context.newCDPSession(page);
    await page.evaluate(() => {
      window.recoveryLifecycle = [];
      for (const type of ['visibilitychange', 'freeze', 'resume']) document.addEventListener(type, event => {
        window.recoveryLifecycle.push({ type, trusted: event.isTrusted, visibility: document.visibilityState });
      });
      for (const type of ['blur', 'focus', 'pagehide', 'pageshow']) window.addEventListener(type, event => {
        window.recoveryLifecycle.push({ type, trusted: event.isTrusted, visibility: document.visibilityState });
      });
    });
    const recover = async (workspace, stage) => {
      const before = evidence.requests.length;
      const oldExpiry = await page.evaluate(() => window.recoveryPreviousExpiry);
      assert.ok(Date.now() < oldExpiry - 60000, 'Immediate recovery must precede original expiry');
      await page.locator('#' + workspace + '-session-start').click(); await ready();
      assert.equal(await page.locator('#tab-' + workspace).getAttribute('aria-selected'), 'true');
      assert.equal(await page.locator('#tasks button').count(), 1);
      const protocol = evidence.responses.slice().filter(r => r.route.includes('/trial-session/'));
      assert.deepEqual(protocol.slice(-3).map(r => [r.route, r.status]), [
        ['/api/trial-session/bootstrap', 403], ['/api/trial-session/recovery-challenge', 200], ['/api/trial-session/recovery-complete', 201]
      ]);
      assert.equal(evidence.requests.slice(before).some(r => /\/(approve|cancel|message)$/.test(r.route)), false);
      assert.ok(Date.now() < oldExpiry - 60000);
      if (workspace === 'workroom') {
        await page.locator('#tasks button').click();
        assert.equal(await page.locator('#task-identity').textContent(), identity);
        assert.equal(await page.locator('#edit-title').inputValue(), title);
      } else assert.ok(await page.locator('#relay-text').isEnabled());
      evidence.stages.push({ stage, beforeOriginalExpiryMs: oldExpiry - Date.now() });
    };
    const markExpiry = () => page.evaluate(() => {
      window.recoveryPreviousExpiry = JSON.parse(sessionStorage.getItem('mesh.synthetic-demo.proof.v1')).expiresAt;
    });
    // Independent actual request failure with still-live HttpOnly cookie.
    await markExpiry();
    await page.route('**/api/tasks', route => route.abort('failed'));
    await page.locator('#refresh').click();
    await page.waitForFunction(() => document.getElementById('demo-state').textContent.includes('unreachable'));
    await page.waitForFunction(() => !document.getElementById('demo-start').disabled);
    await cleared(); await page.unroute('**/api/tasks');
    assert.equal((await context.cookies()).some(c => c.name === 'mesh_trial' && c.httpOnly && c.expires * 1000 > Date.now() + 60000), true);
    let before = evidence.requests.length;
    await page.waitForTimeout(150); assert.equal(evidence.requests.length, before, 'Loss makes no automatic admission or private request');
    evidence.stages.push({ stage: 'actual-request-failure-live-cookie-proof-private-clear' });
    await recover('workroom', 'immediate-deliberate-workroom-recovery-same-id-revision');

    // One bounded actual browser lifecycle attempt; record trusted events,
    // never synthetic JavaScript lifecycle events as native acceptance.
    await markExpiry(); before = evidence.requests.length;
    const other = await context.newPage(); await other.goto('about:blank'); await other.bringToFront();
    await cdp.send('Page.setWebLifecycleState', { state: 'frozen' });
    await cdp.send('Page.setWebLifecycleState', { state: 'active' });
    await page.bringToFront(); await other.close();
    const lifecycle = await page.evaluate(() => window.recoveryLifecycle);
    const established = lifecycle.some(e => e.type === 'visibilitychange' && e.visibility === 'hidden' && e.trusted) &&
      lifecycle.some(e => e.type === 'freeze' && e.trusted) && lifecycle.some(e => e.type === 'resume' && e.trusted);
    evidence.stages.push({ stage: 'native-hidden-freeze-resume', established, lifecycle });
    if (established) {
      await cleared(); assert.equal(evidence.requests.length, before, 'Lifecycle must make no automatic requests');
      await recover('workroom', 'immediate-native-lifecycle-recovery');
    } else {
      evidence.limitations.push('Native hidden/freeze/resume unavailable in this headless context; this is not phone lifecycle acceptance.');
      if (await page.evaluate(() => sessionStorage.length === 0)) {
        await cleared(); await recover('workroom', 'deliberate-recovery-after-partial-native-lifecycle');
      }
    }
    await page.locator('#tab-relay').click();
    assert.ok(await page.locator('#relay-text').isEnabled());
    await page.locator('#relay-text').fill('Disposable unsaved Relay input');
    await page.locator('#relay-open').click();
    await page.waitForFunction(() => !document.getElementById('relay-terminal').hidden);
    await markExpiry();
    await page.route('**/api/tasks', route => route.abort('failed'));
    await page.locator('#refresh').click();
    await page.waitForFunction(() => document.getElementById('demo-state').textContent.includes('unreachable'));
    await page.waitForFunction(() => !document.getElementById('demo-start').disabled);
    await cleared(); await page.unroute('**/api/tasks');
    assert.ok(await page.locator('#relay-session-recovery').isVisible());
    evidence.stages.push({ stage: 'relay-loss-clears-input-and-native-frame' });
    await recover('relay', 'immediate-deliberate-relay-recovery-composer-verified');
    await page.locator('#tab-workroom').click(); await page.locator('#tasks button').click();
    assert.equal(await page.locator('#task-identity').textContent(), identity);
    evidence.stages.push({ stage: 'same-saved-task-current-revision-after-relay-recovery' });
    const db = new DatabaseSync(path.join(dir, 'tasks.sqlite'), { readOnly: true });
    evidence.counts = Object.fromEntries(['tasks','task_executions'].map(name => [name, db.prepare(`SELECT COUNT(*) AS n FROM ${name}`).get().n])); db.close();
    assert.equal(evidence.counts.tasks, 1); assert.equal(evidence.counts.task_executions, 0);
    assert.equal(evidence.requests.some(r => r.route.endsWith('/approve') || r.route.endsWith('/cancel') || r.route.endsWith('/message')), false);
    for (const [route, file] of [['/', 'index.html'], ['/app.js','app.js']]) {
      const response = loaded.get(route); const sha256 = hash(await response.body()); const sourceSha256 = hash(await readFile(path.join(ROOT, 'public', file)));
      assert.equal(sha256, sourceSha256); evidence.freshness[route] = { sha256, sourceSha256, fromServiceWorker: response.fromServiceWorker() };
    }
    assert.equal(evidence.errors.length, 0);
    await page.screenshot({ path: path.join(dir, 'final.png') });
    evidence.passed = true; console.log(mode.toUpperCase() + ' PASS ' + evidence.stages.length + ' stages');
  } catch (e) { evidence.failure = e.stack; process.exitCode = 1; console.error(e.stack); }
  finally {
    await browser?.close(); await browserServer?.close();
    if (child && child.exitCode === null && child.signalCode === null) { const exited = once(child, 'exit'); child.stdin.end(); await exited; }
    if (observer) { observer.stdin.end('\n'); const [code] = await observedExit; evidence.cleanup = { records, observerExit: code, errors: observerErrors }; if (code !== 0 || records.at(-1)?.event !== 'verified' || !records.at(-1).identities.every(v => v.exitSignaled && v.exitCode !== 259)) process.exitCode = 1; }
    evidence.meshExit = child?.exitCode; evidence.meshOutput = output; evidence.meshErrors = errors;
    await writeFile(path.join(dir, 'browser-proof.json'), JSON.stringify(evidence, null, 2));
  }
}
