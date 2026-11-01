import assert from 'node:assert/strict';
import { writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { fixture } from './m4-link-fixture.mjs';

// An actual native composer/link regression. Baseline mode must prove the stale
// board against the real canonical API, not merely open the Relay shell.
const baseline = process.argv.includes('--baseline');
const after = [];
const f = await fixture({ after: fn => after.push(fn) }, baseline ? 'saved-baseline' : 'saved-fixed');
const { chromium } = await import(pathToFileURL('C:/Users/eMitchell109/AppData/Local/hermes/hermes-agent/node_modules/playwright-core/index.mjs').href);
let server, browser, app;
const evidence = { baseline, viewport: { width: 390, height: 844 }, stages: [], errors: [], console: [], requests: [] };
const save = async () => writeFile(path.join(f.dir, 'native-proof.json'), JSON.stringify(evidence, null, 2));
console.log('EVIDENCE ' + f.dir);
try {
  app = await f.boot();
  evidence.url = app.url;
  server = await chromium.launchServer({ executablePath: 'C:/Users/eMitchell109/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe', headless: true });
  evidence.browserPid = server.process().pid;
  browser = await chromium.connect(server.wsEndpoint());
  const context = await browser.newContext({ viewport: evidence.viewport });
  const page = await context.newPage();
  page.on('pageerror', e => evidence.errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') evidence.console.push(m.text()); });
  page.on('request', r => evidence.requests.push({ path: new URL(r.url()).pathname, method: r.method() }));
  await page.goto(app.url);
  await page.locator('#demo-start').click();
  await page.waitForFunction(() => !document.getElementById('refresh').disabled);
  assert.equal(await page.locator('#total-count').textContent(), '0');
  assert.equal(await page.locator('#tasks button').count(), 0);
  await page.locator('#tab-relay').click();
  assert.match(await page.locator('#relay-state').textContent(), /Actual isolated Relay connected/);
  await page.locator('#relay-open').click();
  const frame = page.frameLocator('#relay-terminal');
  await frame.locator('#in').fill('Native Relay Saved tasks regression ' + (baseline ? 'baseline' : 'fixed'));
  const sent = page.waitForResponse(r => r.url().endsWith('/api/relay/message') && r.request().method() === 'POST');
  await page.locator('#relay-terminal').scrollIntoViewIfNeeded();
  await frame.locator('#snd').click();
  const reply = await sent;
  assert.equal(reply.status(), 200);
  const ref = await reply.json();
  assert.equal(ref.ok, true);
  evidence.ref = ref;
  await frame.locator('#meshTaskLink').waitFor({ state: 'visible' });
  assert.equal(await frame.locator('#meshTaskLink').getAttribute('data-task-id'), ref.taskId);
  // Read actual admitted list data without invoking UI Refresh.
  const read = route => page.evaluate(async route => {
    const proof = JSON.parse(sessionStorage.getItem('mesh.synthetic-demo.proof.v1'));
    const r = await fetch(route, { headers: { 'X-Trial-CSRF': proof.csrfToken }, cache: 'no-store', credentials: 'same-origin' });
    if (!r.ok) throw Error('Actual read refused: ' + r.status);
    return r.json();
  }, route);
  const canonical = (await read('/api/tasks')).tasks;
  assert.equal(canonical.length, 1);
  assert.equal(canonical[0].id, ref.taskId);
  assert.equal(canonical[0].proposal, undefined);
  evidence.canonical = canonical;
  const beforeLink = evidence.requests.length;
  await frame.locator('#meshTaskLink').click();
  await page.waitForFunction(id => document.getElementById('task-identity').textContent.includes(id) && !document.getElementById('refresh').disabled, ref.taskId);
  const rows = await page.locator('#tasks button').count();
  evidence.stages.push({ stage: 'native-handoff', taskId: ref.taskId, savedRows: rows, requests: evidence.requests.slice(beforeLink) });
  assert.equal(rows, baseline ? 0 : 1, baseline ? 'Baseline must reproduce the stale board' : 'Native handoff must refresh Saved tasks without Refresh');
  assert.equal(await page.locator('#edit-title').inputValue(), canonical[0].title);
  assert.match(await page.locator('#execution-result').textContent(), /Not run/);
  await page.screenshot({ path: path.join(f.dir, 'native-handoff.png'), fullPage: false });
  if (!baseline) {
    assert.equal(await page.locator('#tasks button[aria-pressed=true] b').textContent(), canonical[0].title);
    const heading = await page.locator('#inspection-heading').boundingBox();
    const focused = await page.evaluate(() => document.activeElement.id);
    evidence.inspection = { heading, focused };
    assert.equal(focused, 'inspection-heading');
    assert.ok(heading.y >= 0 && heading.y + heading.height <= 844, 'Inspection title must be in the phone viewport');
    await page.locator('#tab-relay').click();
    await page.locator('#relay-reconnect').click();
    await page.waitForFunction(() => !document.getElementById('relay-open').disabled);
    assert.match(await page.locator('#relay-links').textContent(), new RegExp(ref.taskId));
    await page.locator('#relay-open').click();
    await frame.locator('#meshTaskLink').waitFor({ state: 'visible' });
    assert.equal(await frame.locator('#meshTaskLink').getAttribute('data-task-id'), ref.taskId);
    await page.locator('#relay-terminal').scrollIntoViewIfNeeded();
    await frame.locator('#meshTaskLink').click();
    await page.waitForFunction(id => document.getElementById('task-identity').textContent.includes(id) && !document.getElementById('refresh').disabled, ref.taskId);
    assert.equal(await page.locator('#tasks button').count(), 1);
    evidence.stages.push({ stage: 'native-reconnect-link', taskId: ref.taskId, savedRows: 1 });
    // Saved row selection and edit/save/reload stay on the same task, without proposing.
    await page.locator('#tasks button').click();
    await page.locator('#edit-title').fill(canonical[0].title + ' edited');
    await page.locator('#edit-form button[type=submit]').click();
    await page.waitForFunction(() => !document.getElementById('refresh').disabled);
    await page.locator('#reload-task').click();
    await page.waitForFunction(() => !document.getElementById('refresh').disabled);
    assert.match(await page.locator('#task-identity').textContent(), new RegExp(ref.taskId));
    await page.reload();
    await page.waitForFunction(() => !document.getElementById('refresh').disabled);
    assert.equal(await page.locator('#tasks button').count(), 1);
    await page.locator('#tab-workroom').click();
    await page.locator('#tasks button').click();
    assert.match(await page.locator('#task-identity').textContent(), new RegExp(ref.taskId));
    assert.equal(await page.locator('#edit-title').inputValue(), canonical[0].title + ' edited');
    evidence.stages.push({ stage: 'reload', taskId: ref.taskId, task: (await read('/api/tasks/' + ref.taskId)).task });
  }
  const db = new DatabaseSync(f.filename, { readOnly: true });
  evidence.counts = {};
  for (const name of ['tasks', 'relay_task_links', 'task_proposals', 'task_executions', 'task_proposal_decisions']) {
    evidence.counts[name] = db.prepare(`SELECT COUNT(*) AS n FROM ${name}`).get().n;
    assert.equal(evidence.counts[name], ['tasks', 'relay_task_links'].includes(name) ? 1 : 0);
  }
  db.close();
  const relayDb = new DatabaseSync(f.relayFilename, { readOnly: true });
  evidence.references = relayDb.prepare('SELECT * FROM mesh_task_references').all();
  assert.equal(evidence.references.length, 1);
  assert.equal(evidence.references[0].task_id, ref.taskId);
  assert.equal(relayDb.prepare('SELECT COUNT(*) AS n FROM messages').get().n, 1);
  assert.equal(relayDb.prepare('SELECT COUNT(*) AS n FROM outbox').get().n, 0);
  relayDb.close();
  await page.locator('#demo-end').click();
  await page.waitForFunction(() => document.getElementById('task-identity').textContent === '' && document.getElementById('demo-end').disabled);
  assert.equal(await page.locator('#tasks button').count(), 0);
  assert.equal(await page.locator('#relay-links button').count(), 0);
  assert.equal(await page.locator('#relay-terminal').getAttribute('srcdoc'), '');
  evidence.logoutCleared = true;
  assert.deepEqual(evidence.errors, []);
  evidence.passed = true;
  console.log((baseline ? 'BASELINE REPRODUCED' : 'NATIVE FIX PASS') + ' ' + ref.taskId);
} catch (e) {
  evidence.failure = e.stack;
  throw e;
} finally {
  if (browser) await browser.close();
  if (server) await server.close();
  for (const fn of after) await fn();
  evidence.meshOutput = app?.output();
  evidence.meshErrors = app?.errors();
  await save();
}
