// Actual Chromium, UI admission and native whitelist execution; no owner store.
// Set OWNER_INSPECT_PLAYWRIGHT to an installed playwright-core index.mjs.
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { startApp, ROOT } from '../server.mjs';

const { chromium } = await import(process.env.OWNER_INSPECT_PLAYWRIGHT
  ? pathToFileURL(process.env.OWNER_INSPECT_PLAYWRIGHT).href : 'playwright');
const reproduce = process.argv.includes('--reproduce');
const dataDir = `test/app03-owner-inspect-${reproduce ? 'before' : 'after'}-${randomUUID()}`;
const app = await startApp({ dataDir });
const directory = path.join(ROOT, dataDir);
let browser;
try {
  browser = await chromium.launch({ headless: true,
    ...(process.env.OWNER_INSPECT_CHROMIUM ? { executablePath: process.env.OWNER_INSPECT_CHROMIUM } : {}) });
} catch (error) { await app.close(); throw error; }
const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
const page = await context.newPage();
page.setDefaultTimeout(15000);
const consoleErrors = []; const responses = [];
page.on('pageerror', e => consoleErrors.push(e.message));
page.on('console', e => { if (e.type() === 'error') consoleErrors.push(e.text()); });
page.on('response', r => { if (new URL(r.url()).pathname.startsWith('/api/')) responses.push({ route: new URL(r.url()).pathname, status: r.status() }); });
const evidence = { viewport: { width: 390, height: 844 }, url: app.url, dataDir, consoleErrors, responses, stages: [] };
const hash = value => createHash('sha256').update(value).digest('hex');
async function measure(label, target) {
  const value = await page.evaluate(id => {
    const el = document.getElementById(id); const r = el.getBoundingClientRect();
    const banner = document.querySelector('.preview-banner').getBoundingClientRect();
    const bounds = id => {
      const r = document.getElementById(id).getBoundingClientRect(); return { top: r.top, bottom: r.bottom };
    };
    return { target: id, scrollY, top: r.top, bottom: r.bottom, height: r.height,
      focus: document.activeElement.id, text: el.textContent, bannerBottom: banner.bottom,
      title: document.getElementById('edit-title').value, description: document.getElementById('edit-description').value,
      identity: document.getElementById('task-identity').textContent,
      titleBounds: bounds('edit-title'), descriptionBounds: bounds('edit-description'),
      resultBounds: bounds('execution-result'), proposal: document.getElementById('proposal-value').textContent,
      state: document.getElementById('proposal-state').textContent };
  }, target);
  evidence.stages.push({ label, ...value }); return value;
}
async function visible(label, target) {
  const value = await measure(label, target);
  assert.equal(value.focus, target, label + ': semantic inspection focus');
  assert.ok(value.top >= Math.max(0, value.bannerBottom) && value.top < 844, label + ': visible below sticky banner');
  return value;
}
const waitText = (id, text) => page.waitForFunction(({ id, text }) => document.getElementById(id).textContent.includes(text), { id, text });
async function create(title, description = '') {
  await page.locator('#create-title').fill(title); await page.locator('#create-description').fill(description);
  await page.locator('#create-form button').click(); await waitText('message', 'Task created');
}
async function choose(title) {
  await page.locator('#tasks button').filter({ hasText: title }).click();
  await page.waitForFunction(title => document.getElementById('edit-title').value === title, title);
}
async function propose(command) {
  await page.locator('#proposal-command').selectOption(command); await page.locator('#propose-command').click();
  await waitText('proposal-state', 'Pending');
}
try {
  const shellResponses = new Map();
  page.on('response', async r => {
    const route = new URL(r.url()).pathname;
    if (['/', '/app.js'].includes(route)) shellResponses.set(route, { status: r.status(), fromServiceWorker: r.fromServiceWorker(), sha256: hash(await r.body()) });
  });
  await page.goto(app.url); await page.locator('#demo-start').click();
  await page.waitForFunction(() => !document.getElementById('create-title').disabled);
  await page.locator('#tab-workroom').click();
  await create('Phone inspection check', 'Stored description from disposable UI');
  if (!reproduce) await visible('created inspection', 'inspection-heading');
  if (reproduce) {
    await propose('node-version'); await page.locator('#approve-command').click();
    await waitText('execution-result', 'Cleanup verified: true');
  }
  await create('Second task');
  await page.reload(); await page.waitForFunction(() => !document.getElementById('create-title').disabled);
  await page.locator('#tab-workroom').click();
  await page.locator('#tasks button').filter({ hasText: 'Phone inspection check' }).scrollIntoViewIfNeeded();
  await measure('before selecting saved task', 'execution-result');
  await choose('Phone inspection check');
  if (reproduce) {
    const after = await measure('old selection leaves result outside viewport', 'execution-result');
    assert.ok(after.top < 0 || after.top >= 844, 'Reproduce result outside viewport');
    assert.notEqual(after.focus, 'inspection-heading');
    await page.screenshot({ path: path.join(directory, 'before-selection.png') });
  } else {
    const selection = await visible('selected task inspection', 'inspection-heading');
    assert.match(selection.text, /Phone inspection check/);
    assert.equal(selection.description, 'Stored description from disposable UI');
    assert.match(selection.identity, /Task .*revision 1/);
    for (const r of [selection.titleBounds, selection.descriptionBounds]) {
      assert.ok(r.top >= selection.bannerBottom && r.bottom <= 844, 'Saved editable title/description visibly in viewport');
    }
    await page.screenshot({ path: path.join(directory, 'selected-task.png') });
    await page.locator('#view-result').click(); await visible('not run details', 'result-heading');
    await waitText('execution-result', 'Not run');
    await propose('node-version');
    await waitText('execution-result', 'Pending');
    await page.locator('#approve-command').click();
    await waitText('execution-result', 'Cleanup verified: true');
    await waitText('proposal-state', 'Completed');
    const output = await page.locator('#execution-result').textContent();
    evidence.completedResult = output;
    assert.match(output, /Exit code: 0/); assert.match(output, /stdout:\n[vV]\d+\.\d+\.\d+/);
    assert.match(output, /Cancelled: false/); assert.match(output, /stderr:/);
    await choose('Phone inspection check'); await visible('completed task selection', 'inspection-heading');
    await page.locator('#view-result').click();
    const completedView = await visible('actual completed result', 'result-heading');
    assert.ok(completedView.resultBounds.top < 844 && completedView.resultBounds.bottom <= 844, 'Actual version stdout/stderr visible');
    assert.match(completedView.text, /Phone inspection check/);
    assert.match(completedView.proposal, /node --version/);
    await page.screenshot({ path: path.join(directory, 'completed-result.png') });
    await page.locator('#back-to-details').click(); await visible('return to editable details', 'inspection-heading');
    await page.locator('#edit-description').fill('Edited and saved on phone viewport');
    await page.locator('#edit-form button[type=submit]').click(); await waitText('message', 'Task saved');
    await page.locator('#toggle-status').click(); await waitText('task-status', 'done');
    await page.locator('#toggle-status').click(); await waitText('task-status', 'open');
    await propose('node-version'); await page.locator('#deny-command').click(); await waitText('proposal-state', 'Denied');
    await waitText('execution-result', 'Not run');
    await propose('m3-slow'); await page.locator('#approve-command').click();
    await page.waitForFunction(() => !document.getElementById('cancel-command').disabled);
    const pollScroll = await page.evaluate(() => { document.getElementById('cancel-command').focus(); return { y: scrollY, focus: document.activeElement.id }; });
    await page.waitForTimeout(450);
    assert.deepEqual(await page.evaluate(() => ({ y: scrollY, focus: document.activeElement.id })), pollScroll, 'Background polling must not move focus/scroll');
    await page.locator('#cancel-command').click(); await waitText('execution-result', 'Cancelled: true');
    await waitText('execution-result', 'Cleanup verified: true');
    await choose('Phone inspection check'); await visible('cancelled task selection', 'inspection-heading');
    await page.locator('#view-result').click(); await visible('actual cancellation details', 'result-heading');
    const cancelled = await page.locator('#execution-result').textContent();
    assert.match(cancelled, /M3 slow .*started/); assert.match(cancelled, /stderr:/);
    await page.screenshot({ path: path.join(directory, 'cancelled-result.png') });
    evidence.cancelledResult = cancelled;
    await page.reload(); await page.waitForFunction(() => !document.getElementById('create-title').disabled);
    await page.locator('#tab-workroom').click(); await choose('Phone inspection check');
    await visible('stored task after reload', 'inspection-heading');
    assert.equal(await page.locator('#edit-description').inputValue(), 'Edited and saved on phone viewport');
    await page.locator('#view-result').click(); await visible('stored cancellation after reload', 'result-heading');
    assert.equal(await page.locator('#execution-result').textContent(), cancelled);
    await page.locator('#reload-task').click(); await waitText('message', 'Current revision loaded');
    await page.locator('#refresh').click(); await waitText('message', 'refreshed');
    assert.equal(await page.locator('#execution-result').textContent(), cancelled);
    // Produce a real stale revision refusal using a second admitted UI action.
    // A PATCH from the same browser's existing proof preserves normal auth/CSRF.
    await page.evaluate(async () => {
      const proof = JSON.parse(sessionStorage.getItem('mesh.synthetic-demo.proof.v1'));
      const tasks = await fetch('/api/tasks', { headers: { 'X-Trial-CSRF': proof.csrfToken } }).then(r => r.json());
      const task = tasks.tasks.find(t => t.title === 'Phone inspection check');
      const r = await fetch('/api/tasks/' + task.id, { method: 'PATCH', headers: { 'Content-Type': 'application/json', 'X-Trial-CSRF': proof.csrfToken },
        body: JSON.stringify({ title: task.title, description: task.description, label: task.label, status: task.status, revision: task.revision }) });
      if (!r.ok) throw new Error('Stale revision fixture failed: ' + r.status);
    });
    await page.locator('#edit-form button[type=submit]').click();
    await page.waitForFunction(() => document.getElementById('message').className === 'error');
    await visible('actual stale-save error', 'message');
    assert.ok(responses.some(r => r.status === 409));
    // The sole console error is Chromium reporting this deliberately refused request.
    assert.equal(consoleErrors.filter(e => !e.includes('409 (Conflict)')).length, 0, consoleErrors.join('\n'));
    await page.locator('#reload-task').click(); await waitText('message', 'Current revision loaded');
  }
  evidence.freshness = {};
  for (const [route, file] of [['/', 'index.html'], ['/app.js', 'app.js']]) {
    const localHash = hash(await readFile(path.join(ROOT, 'public', file)));
    const served = shellResponses.get(route); assert.equal(served?.sha256, localHash, 'Browser loaded current bytes: ' + route);
    evidence.freshness[route] = { ...served, localHash };
  }
  evidence.serviceWorker = await page.evaluate(() => ({ controlled: !!navigator.serviceWorker.controller, script: navigator.serviceWorker.controller?.scriptURL ?? null }));
  await page.locator('#demo-end').click(); await waitText('demo-state', 'ended');
  assert.equal(await page.locator('#execution-result').textContent(), '');
  if (!reproduce) assert.equal(await page.locator('#inspection-heading').textContent(), 'Inspect and edit');
  if (!reproduce) assert.equal(await page.locator('#result-heading').textContent(), 'Command proposal and execution result');
  evidence.pass = true;
} finally {
  await writeFile(path.join(directory, 'browser-proof.json'), JSON.stringify(evidence, null, 2));
  await browser.close(); await app.close();
  console.log(JSON.stringify({ pass: evidence.pass ?? false, dataDir, stages: evidence.stages.map(s => ({ label: s.label, top: s.top, focus: s.focus })) }));
}
