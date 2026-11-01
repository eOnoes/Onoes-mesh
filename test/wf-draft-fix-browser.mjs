// Disposable actual Chromium/API/native execution proof; no owner store or services.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { chromium } from 'file:///C:/Users/eMitchell109/AppData/Local/hermes/hermes-agent/node_modules/playwright-core/index.mjs';
import { startApp, ROOT } from '../server.mjs';

const dataDir = process.argv[2];
assert.match(dataDir, /^test\/app03-draft-proof-[a-zA-Z0-9_-]+$/);
assert.equal(process.env.MESH_STANDALONE, '1'); assert.equal(process.env.MESH_RELAY, '0');
const directory = path.join(ROOT, dataDir);
const hash = b => createHash('sha256').update(b).digest('hex');
const files = ['public/app.js', 'public/index.html', 'server.mjs', 'lib/command-execution.mjs', 'lib/slow-command.mjs',
  'lib/owned-command.py', 'test/wf-draft-preservation.test.mjs', 'test/wf-draft-fix-browser.mjs', 'test/wf-draft-fix-supervise.py'];
const evidence = { started: new Date().toISOString(), dataDir, cases: [], hashes: {}, cleanup: {}, errors: [] };
let server, browser, app; const pending = [];
const fields = ['title', 'description', 'label'];
const extract = s => Object.fromEntries(fields.map(f => [f, s[f]]));
function rows(store) {
  const db = new DatabaseSync(path.join(ROOT, store, 'tasks.sqlite'), { readOnly: true });
  try { return { tasks: db.prepare('SELECT * FROM tasks').all(), decisions: db.prepare('SELECT * FROM task_proposal_decisions').all(),
    executions: db.prepare('SELECT * FROM task_executions').all().map(r => ({ ...r, argv: JSON.parse(r.argv), result: r.result && JSON.parse(r.result) })) }; }
  finally { db.close(); }
}
try {
  for (const file of files) evidence.hashes[file] = hash(await readFile(path.join(ROOT, file)));
  server = await chromium.launchServer({ headless: true, executablePath: 'C:/Users/eMitchell109/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe' });
  evidence.browserPid = server.process().pid;
  server.process().on('exit', (code, signal) => { evidence.cleanup.browserNativeExit = { code, signal }; });
  browser = await chromium.connect(server.wsEndpoint());
  for (const viewport of [{ width: 390, height: 844 }, { width: 1440, height: 1000 }]) {
    const store = `${dataDir}-${viewport.width}`;
    const result = { viewport, store, requests: [], responses: [], freshness: {}, stages: [] }; evidence.cases.push(result);
    let heldRequest;
    app = await startApp({ port: 0, dataDir: store, relayEnabled: false }); result.url = app.url; result.mode = app.mode;
    assert.equal(app.mode, 'standalone');
    const context = await browser.newContext({ viewport, isMobile: viewport.width === 390, hasTouch: viewport.width === 390, serviceWorkers: 'block' });
    await context.addInitScript(() => {
      const $ = id => document.getElementById(id);
      window.__wfSnapshot = () => ({ title: $('edit-title')?.value, description: $('edit-description')?.value, label: $('edit-label')?.value,
        identity: $('task-identity')?.textContent, state: $('proposal-state')?.textContent, result: $('execution-result')?.textContent,
        cancelDisabled: $('cancel-command')?.disabled });
      window.__wfPolls = []; const original = window.fetch;
      window.fetch = async function (...args) {
        const route = new URL(typeof args[0] === 'string' ? args[0] : args[0].url, location.href).pathname;
        if (!/^\/api\/tasks\/[^/]+$/.test(route) || (args[1]?.method && args[1].method !== 'GET')) return original.apply(this, args);
        const row = { route, before: window.__wfSnapshot(), requested: Date.now() }; window.__wfPolls.push(row);
        const response = await original.apply(this, args); row.status = response.status;
        const text = response.text.bind(response);
        response.text = async () => {
          const raw = await text(); row.body = JSON.parse(raw); row.consumed = Date.now();
          // The application's body continuation renders before the next animation frame.
          // Acceptance also waits for the actual DOM state and checks the next request's before snapshot.
          requestAnimationFrame(() => { row.rendered = window.__wfSnapshot(); row.observed = Date.now(); });
          return raw;
        };
        return response;
      };
    });
    const page = await context.newPage(); page.setDefaultTimeout(6000);
    page.on('pageerror', e => evidence.errors.push(e.stack));
    page.on('request', r => { if (new URL(r.url()).pathname.startsWith('/api/')) result.requests.push({ method: r.method(), route: new URL(r.url()).pathname, body: r.postData(), at: Date.now() }); });
    page.on('response', r => {
      const route = new URL(r.url()).pathname;
      if (route.startsWith('/api/tasks')) pending.push(r.text().then(raw => result.responses.push({ route, method: r.request().method(), status: r.status(), raw })).catch(e => {
        // The privacy test deliberately invalidates this exact held request. Its
        // authenticated backend bytes are retained separately before release.
        if (r.request() === heldRequest && result.heldResponse) result.heldBrowserBodyUnavailable = String(e);
        else evidence.errors.push(String(e));
      }));
      if (['/', '/app.js'].includes(route)) pending.push(r.body().then(b => {
        const file = route === '/' ? 'public/index.html' : 'public/app.js';
        result.freshness[route] = { sha256: hash(b), localHash: evidence.hashes[file], fromServiceWorker: r.fromServiceWorker() };
        assert.equal(hash(b), evidence.hashes[file]);
      }).catch(e => evidence.errors.push(e.stack)));
    });
    const snapshot = () => page.evaluate(() => window.__wfSnapshot());
    const ready = () => page.waitForFunction(() => !document.getElementById('edit-title').disabled);
    const type = values => page.evaluate(values => {
      for (const [f, value] of Object.entries(values)) { const el = document.getElementById('edit-' + f); el.focus(); el.value = value; el.dispatchEvent(new Event('input', { bubbles: true })); }
      return { ...window.__wfSnapshot(), at: Date.now() };
    }, values);
    await page.goto(app.url); await page.locator('#demo-start').click();
    await page.waitForFunction(() => !document.getElementById('create-title').disabled); await page.locator('#tab-workroom').click();
    const saved = { title: `WF saved ${viewport.width}`, description: 'Saved description', label: 'Saved assignment' };
    for (const [f, value] of Object.entries(saved)) await page.locator('#create-' + f).fill(value);
    const creation = page.waitForResponse(r => new URL(r.url()).pathname === '/api/tasks' && r.request().method() === 'POST');
    await page.locator('#create-form button').click(); result.created = await (await creation).json();
    await page.waitForFunction(() => document.getElementById('message').textContent.includes('Task created'));
    await page.locator('#proposal-command').selectOption('m3-slow'); await page.locator('#propose-command').click();
    await page.waitForFunction(() => document.getElementById('proposal-state').textContent.startsWith('Pending'));
    const approval = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/approve') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Approve', exact: true }).click(); result.approved = await (await approval).json();
    await ready(); await page.waitForFunction(() => document.getElementById('proposal-state').textContent.startsWith('Running'));
    const draft = { title: `WF unsaved ${viewport.width}`, description: 'Unsaved description exact', label: 'Unsaved assignment exact' };
    result.draftBefore = await type(draft);
    await page.waitForFunction(at => window.__wfPolls.filter(r => r.requested > at && r.rendered).length >= 2, result.draftBefore.at);
    result.actualTwoPolls = (await page.evaluate(() => window.__wfPolls)).filter(r => r.requested > result.draftBefore.at && r.rendered).slice(0, 2);
    result.afterTwo = await snapshot(); assert.deepEqual(extract(result.afterTwo), draft);
    for (const poll of result.actualTwoPolls) {
      assert.equal(poll.status, 200); assert.equal(poll.body.task.id, result.approved.task.id);
      assert.equal(poll.body.task.execution.id, result.approved.task.execution.id); assert.equal(poll.body.task.execution.state, 'running');
      assert.deepEqual(extract(poll.before), draft); assert.deepEqual(extract(poll.rendered), draft); assert.equal(poll.rendered.cancelDisabled, false);
    }
    await page.screenshot({ path: path.join(directory, `polls-${viewport.width}.png`) });
    await page.waitForFunction(() => document.getElementById('proposal-state').textContent.startsWith('Completed'), null, { timeout: 18000 });
    // Terminal watch awaits its actual list body before publishing the result message.
    await page.waitForFunction(() => document.getElementById('message').textContent.startsWith('Completed'));
    result.terminal = await snapshot(); assert.deepEqual(extract(result.terminal), draft);
    assert.match(result.terminal.result, /Exit code: 0.*Cleanup verified: true/s); assert.match(result.terminal.result, /M3 slow root completed after 10 seconds/);
    assert.equal(result.terminal.cancelDisabled, true); result.beforeSaveRows = rows(store);
    assert.equal(result.beforeSaveRows.executions.length, 1); assert.equal(result.beforeSaveRows.decisions.length, 1);
    const patch = page.waitForResponse(r => new URL(r.url()).pathname === `/api/tasks/${result.created.task.id}` && r.request().method() === 'PATCH');
    await page.locator('#edit-form button[type=submit]').click(); const patchResponse = await patch;
    result.save = { status: patchResponse.status(), body: await patchResponse.json() }; assert.equal(result.save.status, 200);
    await page.waitForFunction(() => document.getElementById('message').textContent.includes('Task saved'));
    assert.deepEqual(extract(result.save.body.task), draft);
    const writes = result.requests.filter(r => r.method === 'PATCH'); assert.equal(writes.length, 1);
    assert.equal(JSON.parse(writes[0].body).revision, result.beforeSaveRows.tasks[0].revision);
    result.authenticatedReread = await page.evaluate(async id => {
      const proof = JSON.parse(sessionStorage.getItem('mesh.synthetic-demo.proof.v1'));
      const r = await fetch(`/api/tasks/${id}`, { headers: { 'X-Trial-CSRF': proof.csrfToken }, credentials: 'same-origin', cache: 'no-store' });
      return { status: r.status, body: await r.json() };
    }, result.created.task.id);
    assert.equal(result.authenticatedReread.status, 200); assert.deepEqual(extract(result.authenticatedReread.body.task), draft);
    result.afterSaveRows = rows(store); assert.equal(result.afterSaveRows.tasks[0].revision, result.beforeSaveRows.tasks[0].revision + 1);
    await type({ title: 'Discard Reload', description: 'Discard Reload', label: 'Discard Reload' });
    await page.locator('#reload-task').click(); await page.waitForFunction(() => document.getElementById('message').textContent.includes('Current revision loaded'));
    result.reloaded = await snapshot(); assert.deepEqual(extract(result.reloaded), draft);
    await type({ title: 'Discard selection', description: 'Discard selection', label: 'Discard selection' });
    await page.locator('#tasks button').click(); result.reselected = await snapshot(); assert.deepEqual(extract(result.reselected), draft);
    // Hold a real authenticated body across an actual browser offline privacy event.
    await type({ title: 'Private title', description: 'Private description', label: 'Private label' });
    let release, arrived, fulfilled;
    const gate = new Promise(resolve => { release = resolve; }); const held = new Promise(resolve => { arrived = resolve; });
    const completedRoute = new Promise(resolve => { fulfilled = resolve; });
    await page.route('**/api/tasks', async route => {
      if (route.request().method() !== 'GET') return route.continue();
      heldRequest = route.request();
      const response = await route.fetch(); result.heldResponse = { status: response.status(), raw: await response.text() }; arrived();
      await gate; await route.fulfill({ response }); fulfilled();
    });
    await page.evaluate(() => { document.getElementById('refresh').click(); }); await held;
    await context.setOffline(true);
    await page.waitForFunction(() => document.getElementById('edit-form').hidden && document.getElementById('edit-title').value === '');
    result.cleared = await snapshot(); assert.deepEqual(extract(result.cleared), { title: '', description: '', label: '' });
    release(); await completedRoute; await context.setOffline(false);
    await page.waitForFunction(() => !document.getElementById('demo-start').disabled);
    result.afterDelayedBody = await snapshot(); assert.deepEqual(extract(result.afterDelayedBody), { title: '', description: '', label: '' });
    assert.equal(result.afterDelayedBody.result, ''); assert.equal(result.afterDelayedBody.identity, '');
    await page.unroute('**/api/tasks'); await page.locator('#demo-start').click();
    await page.waitForFunction(() => !document.getElementById('create-title').disabled);
    await page.locator('#tasks button').click(); await type({ title: 'Logout draft', description: 'Logout draft', label: 'Logout draft' });
    await page.locator('#demo-end').click();
    await page.waitForFunction(() => document.getElementById('demo-state').textContent.includes('ended locally'));
    result.logoutCleared = await snapshot(); assert.deepEqual(extract(result.logoutCleared), { title: '', description: '', label: '' });
    assert.equal(result.logoutCleared.result, '');
    result.polls = await page.evaluate(() => window.__wfPolls);
    assert.equal(result.requests.filter(r => r.method === 'POST' && r.route.endsWith('/approve')).length, 1);
    result.pass = true; await page.screenshot({ path: path.join(directory, `cleared-${viewport.width}.png`) });
    await context.close(); await app.close(); app = undefined;
  }
  await Promise.all(pending); assert.equal(evidence.errors.length, 0); evidence.pass = true;
} catch (e) { evidence.failure = { message: e.message, stack: e.stack }; process.exitCode = 1; }
finally {
  for (const [name, close] of [['browser', () => browser?.close()], ['browserServer', () => server?.close()], ['app', () => app?.close()]]) {
    try { await close(); evidence.cleanup[name] = true; } catch (e) { evidence.cleanup[name] = e.stack; process.exitCode = 1; }
  }
  await Promise.allSettled(pending);
  evidence.hashesAfter = {}; for (const file of files) evidence.hashesAfter[file] = hash(await readFile(path.join(ROOT, file)));
  if (JSON.stringify(evidence.hashesAfter) !== JSON.stringify(evidence.hashes)) { evidence.hashMismatch = true; process.exitCode = 1; }
  evidence.finished = new Date().toISOString(); await writeFile(path.join(directory, 'browser-proof.json'), JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify({ pass: evidence.pass ?? false, dataDir, cases: evidence.cases.map(c => ({ width: c.viewport.width, pass: c.pass ?? false })), failure: evidence.failure?.message }));
}
