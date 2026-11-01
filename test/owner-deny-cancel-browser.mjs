// Actual Chromium and fixed native command; disposable SQLite, no owner data.
import assert from 'node:assert/strict';
import { createHash, randomUUID } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';
import { startApp, ROOT } from '../server.mjs';

const { chromium } = await import(pathToFileURL(process.env.OWNER_DENY_CANCEL_PLAYWRIGHT ??
  'C:/Users/eMitchell109/AppData/Local/hermes/hermes-agent/node_modules/playwright-core/index.mjs').href);
const dataDir = `test/app03-owner-deny-cancel-browser-${randomUUID()}`;
const app = await startApp({ dataDir, relayEnabled: false });
const directory = path.join(ROOT, dataDir);
const evidence = { dataDir, url: app.url, viewport: { width: 390, height: 844 }, stages: [], requests: [], errors: [], freshness: {} };
let browser;
const hash = b => createHash('sha256').update(b).digest('hex');
function stored(title) {
  const db = new DatabaseSync(path.join(directory, 'tasks.sqlite'), { readOnly: true });
  try {
    const task = db.prepare('SELECT * FROM tasks WHERE title=?').get(title); assert.ok(task);
    const decision = db.prepare('SELECT * FROM task_proposal_decisions WHERE taskId=?').get(task.id);
    const executions = db.prepare('SELECT * FROM task_executions WHERE taskId=?').all(task.id);
    return { task, decision, executions: executions.map(r => ({ ...r, argv: JSON.parse(r.argv), result: r.result && JSON.parse(r.result) })) };
  } finally { db.close(); }
}
try {
  browser = await chromium.launch({ headless: true, executablePath: process.env.OWNER_DENY_CANCEL_CHROMIUM ??
    'C:/Users/eMitchell109/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe' });
  const context = await browser.newContext({ viewport: evidence.viewport, isMobile: true, hasTouch: true });
  const page = await context.newPage(); page.setDefaultTimeout(20000);
  page.on('pageerror', e => evidence.errors.push(e.message));
  page.on('request', r => { if (new URL(r.url()).pathname.startsWith('/api/')) evidence.requests.push({ method: r.method(), route: new URL(r.url()).pathname }); });
  const loaded = new Map();
  page.on('response', r => { const route = new URL(r.url()).pathname;
    if (['/', '/app.js'].includes(route)) loaded.set(route, r); });
  const waitText = (id, text) => page.waitForFunction(({ id, text }) => document.getElementById(id).textContent.includes(text), { id, text });
  const ready = () => page.waitForFunction(() => !document.getElementById('create-title').disabled);
  async function create(title) {
    await page.locator('#create-title').fill(title); await page.locator('#create-form button').click();
    await waitText('message', 'Task created');
  }
  async function propose(choice) {
    await page.locator('#proposal-command').selectOption(choice); await page.locator('#propose-command').click();
    await waitText('proposal-state', 'Pending');
  }
  async function choose(title) {
    await page.locator('#tasks button').filter({ hasText: title }).click();
    await page.waitForFunction(title => document.getElementById('edit-title').value === title, title);
  }
  async function inspect(label) {
    await page.locator('#view-result').click();
    const stage = await page.evaluate(() => {
      const bounds = id => { const r = document.getElementById(id).getBoundingClientRect(); return { top: r.top, bottom: r.bottom }; };
      return { focus: document.activeElement.id, heading: bounds('result-heading'), stateBounds: bounds('proposal-state'),
        bannerBottom: document.querySelector('.preview-banner').getBoundingClientRect().bottom,
        state: document.getElementById('proposal-state').textContent, result: document.getElementById('execution-result').textContent };
    });
    assert.equal(stage.focus, 'result-heading');
    assert.ok(stage.heading.top >= stage.bannerBottom && stage.heading.bottom < 844, label);
    assert.ok(stage.stateBounds.top >= stage.bannerBottom && stage.stateBounds.bottom < 844, label + ': visible summary');
    evidence.stages.push({ label, ...stage });
    await page.screenshot({ path: path.join(directory, label + '.png') });
    return stage;
  }
  await page.goto(app.url); await page.locator('#demo-start').click(); await ready(); await page.locator('#tab-workroom').click();
  const deniedTitle = 'Disposable deny without execution'; const cancelTitle = 'Disposable cancel actual running command';
  await create(deniedTitle); await propose('node-version');
  assert.equal(await page.getByRole('button', { name: 'Cancel running command', exact: true }).isEnabled(), false);
  const denyResponse = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/deny') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Deny proposal (do not run)', exact: true }).click();
  const denied = await (await denyResponse).json();
  assert.equal(denied.task.proposalStatus, 'denied'); assert.equal(denied.task.execution, null);
  await waitText('proposal-state', 'Denied');
  const deniedView = await inspect('denied-no-run');
  assert.match(deniedView.state, /before execution.*not applicable/);
  assert.match(deniedView.result, /Not run.*No process result.*Cancellation and process cleanup: not applicable/);
  evidence.denied = stored(deniedTitle);
  assert.equal(evidence.denied.decision.status, 'denied'); assert.equal(evidence.denied.decision.executionId, null);
  assert.equal(evidence.denied.executions.length, 0);
  assert.equal(evidence.requests.some(r => r.route.endsWith('/approve') || r.route.endsWith('/cancel')), false);
  await page.reload(); await ready(); await page.locator('#tab-workroom').click(); await choose(deniedTitle);
  assert.equal((await inspect('denied-after-reload')).result, deniedView.result);

  await create(cancelTitle); await propose('m3-slow');
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await page.waitForFunction(() => !document.getElementById('cancel-command').disabled);
  // Wait for the actual root/descendant start, allowing retained native custody acquisition before cancel.
  await page.waitForFunction(() => document.getElementById('proposal-state').textContent.startsWith('Running'));
  await new Promise(resolve => setTimeout(resolve, 500));
  assert.equal(await page.getByRole('button', { name: 'Deny proposal (do not run)', exact: true }).isEnabled(), false);
  evidence.active = stored(cancelTitle); assert.equal(evidence.active.executions.length, 1);
  assert.equal(evidence.active.executions[0].state, 'running');
  const cancelResponse = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/cancel') && r.request().method() === 'POST');
  await page.getByRole('button', { name: 'Cancel running command', exact: true }).click();
  evidence.cancelApi = await (await cancelResponse).json();
  await waitText('execution-result', 'Cancelled: true');
  evidence.cancelled = stored(cancelTitle);
  assert.equal(evidence.cancelled.executions.length, 1);
  const run = evidence.cancelled.executions[0]; const result = run.result;
  assert.equal(result.cancelled, true); assert.match(result.stdout, /M3 slow root .*descendant .*started/);
  assert.equal(evidence.cancelApi.task.execution.id, run.id);
  assert.deepEqual(evidence.cancelApi.task.execution.result, result);
  const expectedSummary = `Cancelled — cleanup ${result.cleanupVerified === true ? 'verified' : result.cleanupVerified === false ? 'not verified' : 'unknown'}`;
  const cancelView = await inspect('cancelled-actual-result'); assert.equal(cancelView.state, expectedSummary);
  assert.match(cancelView.result, new RegExp(`Cleanup verified: ${result.cleanupVerified}\\n`));
  assert.match(cancelView.result, /stdout:\nM3 slow root/); assert.match(cancelView.result, /stderr:/);
  assert.equal(await page.getByRole('button', { name: 'Cancel running command', exact: true }).isEnabled(), false);
  await page.reload(); await ready(); await page.locator('#tab-workroom').click(); await choose(cancelTitle);
  const reloaded = await inspect('cancelled-after-reload'); assert.equal(reloaded.state, expectedSummary); assert.equal(reloaded.result, cancelView.result);
  await page.locator('#reload-task').click(); await waitText('message', 'Current revision loaded');
  assert.equal(await page.locator('#proposal-state').textContent(), expectedSummary);
  assert.equal(await page.locator('#execution-result').textContent(), cancelView.result);
  await choose(deniedTitle); const separateDenial = await inspect('denial-after-separate-cancellation');
  assert.equal(separateDenial.result, deniedView.result); assert.doesNotMatch(separateDenial.state, /Cancelled|cleanup verified/);
  assert.equal(stored(deniedTitle).executions.length, 0);
  assert.equal(evidence.requests.filter(r => r.method === 'POST' && r.route.endsWith('/approve')).length, 1);
  assert.equal(evidence.requests.filter(r => r.method === 'POST' && r.route.endsWith('/cancel')).length, 1);
  for (const [route, file] of [['/', 'index.html'], ['/app.js', 'app.js']]) {
    const r = loaded.get(route); const sha256 = hash(await r.body()); const localHash = hash(await readFile(path.join(ROOT, 'public', file)));
    assert.equal(sha256, localHash); evidence.freshness[route] = { sha256, localHash, fromServiceWorker: r.fromServiceWorker() };
  }
  assert.equal(evidence.errors.length, 0);
  await page.locator('#demo-end').click(); await waitText('demo-state', 'ended');
  assert.equal(await page.locator('#execution-result').textContent(), '');
  assert.equal(await page.locator('#proposal-state').textContent(), '');
  evidence.pass = true;
} finally {
  await browser?.close(); await app.close();
  await writeFile(path.join(directory, 'browser-proof.json'), JSON.stringify(evidence, null, 2));
  console.log(JSON.stringify({ pass: evidence.pass ?? false, dataDir, stages: evidence.stages.map(s => ({ label: s.label, state: s.state })), cleanup: evidence.cancelled?.executions[0]?.result.cleanupVerified }));
}
