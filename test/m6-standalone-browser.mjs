// Actual npm entry point, actual mobile Chromium and original native processes.
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { DatabaseSync } from 'node:sqlite';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { fixture } from './m6-standalone-fixture.mjs';

const { chromium } = await import(process.env.M6_STANDALONE_PLAYWRIGHT
  ? pathToFileURL(process.env.M6_STANDALONE_PLAYWRIGHT).href : 'playwright');
const f = await fixture('browser');
const evidence = { viewport: { width: 390, height: 844 }, dataDir: f.dataDir, provenance: await f.provenance(),
  serviceRootsPresent: await readFile(new URL('../service_roots/relay/SOURCE.md', import.meta.url), 'utf8'), stages: [], errors: [] };
let browserServer, browser, app, page;
const delay = ms => new Promise(r => setTimeout(r, ms));
function rows() {
  const db = new DatabaseSync(path.join(f.directory, 'tasks.sqlite'), { readOnly: true });
  try { return Object.fromEntries(['tasks','task_proposals','task_executions','task_proposal_decisions']
    .map(table => [table, db.prepare(`SELECT * FROM ${table} ORDER BY rowid`).all()])); }
  finally { db.close(); }
}
async function api(route, body) {
  return page.evaluate(async ({ route, body }) => {
    const proof = JSON.parse(sessionStorage.getItem('mesh.synthetic-demo.proof.v1'));
    const response = await fetch(route, { ...(body === undefined ? {} : { method: 'POST', body: JSON.stringify(body) }),
      headers: { 'X-Trial-CSRF': proof.csrfToken, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) } });
    const text = await response.text(); return { status: response.status, noStore: response.headers.get('cache-control'),
      value: text ? JSON.parse(text) : null };
  }, { route, body });
}
const waitText = (id, text) => page.waitForFunction(({ id, text }) => document.getElementById(id).textContent.includes(text), { id, text });
async function create(title) {
  await page.locator('#create-title').fill(title); await page.locator('#create-form button').click();
  await waitText('message', 'Task created');
  const value = (await api('/api/tasks')).value.tasks.find(t => t.title === title); assert.ok(value); return value;
}
async function propose(command) {
  await page.locator('#proposal-command').selectOption(command); await page.locator('#propose-command').click();
  await waitText('proposal-state', 'Pending');
}
async function approve() {
  const response = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/approve'));
  await page.locator('#approve-command').click(); const reply = await response;
  assert.equal(reply.status(), 202); return (await reply.json()).task;
}
async function nativeTree() {
  for (let n = 0; n < 80; n++) {
    const identities = await f.monitor.call('snapshot');
    const bridge = identities.find(i => !i.exitSignaled && i.parentPid === app.pid && /owned-command.py/.test(i.commandLine));
    const root = identities.find(i => !i.exitSignaled && i.parentPid === bridge?.pid && /slow-command.mjs/.test(i.commandLine));
    const descendant = identities.find(i => !i.exitSignaled && i.parentPid === root?.pid && /--owned-child/.test(i.commandLine));
    if (bridge && root && descendant) return [bridge, root, descendant];
    await delay(20);
  }
  throw Error('Actual native bridge/root/descendant not observed');
}
async function exited(identities) {
  for (let n = 0; n < 80; n++) {
    const current = await f.monitor.call('snapshot');
    const selected = identities.map(i => current.find(p => p.pid === i.pid && p.creationTime100ns === i.creationTime100ns));
    if (selected.every(i => i?.exitSignaled)) return selected;
    await delay(25);
  }
  throw Error('Original native process handles did not signal exit');
}
async function inspectResult() {
  await page.locator('#view-result').click();
  const position = await page.evaluate(() => {
    const heading = document.getElementById('result-heading').getBoundingClientRect();
    return { focus: document.activeElement.id, top: heading.top,
      bannerBottom: document.querySelector('.preview-banner').getBoundingClientRect().bottom };
  });
  assert.equal(position.focus, 'result-heading');
  assert.ok(position.top >= Math.max(0, position.bannerBottom) && position.top < 844);
  return position;
}
async function absent() {
  const health = await api('/api/health'); assert.equal(health.value.mode, 'standalone');
  const services = await api('/api/service-connections');
  for (const s of services.value.services) { assert.equal(s.status, 'not_configured'); assert.equal(s.source, 'none'); }
  const inference = await api('/api/inference-observation'); assert.equal(inference.value.status, 'not_configured'); assert.deepEqual(inference.value.nodes, []);
  const nodes = await api('/api/node-probes/refresh', {}); assert.equal(nodes.value.status, 'not_configured'); assert.deepEqual(nodes.value.nodes, []);
  const relay = await api('/api/relay'); assert.equal(relay.value.status, 'not_configured');
  for (const r of [health, services, inference, nodes, relay]) assert.equal(r.noStore, 'no-store');
  await page.locator('#tab-inference').click();
  assert.equal(await page.locator('#node-probes-refresh').isDisabled(), true);
  assert.match(await page.locator('#tailnet-nodes').innerText(), /not configured in standalone/);
  assert.equal(await page.locator('#tailnet-nodes article').count(), 0);
  await page.locator('#tab-relay').click(); assert.equal(await page.locator('#relay-send').isDisabled(), true);
  await page.locator('#tab-mind').click(); assert.match(await page.locator('#panel-mind').innerText(), /not_configured/);
  await page.locator('#tab-workroom').click();
  const launches = await f.launches();
  assert.equal(launches.some(i => /tailscale|mesh_runtime|inference/i.test(JSON.stringify(i))), false);
  return { health, services, inference, nodes, relay, launches };
}
try {
  app = await f.boot(); evidence.initial = { url: app.previewUrl, backend: app.url, app: app.identity, mode: app.mode };
  browserServer = await chromium.launchServer({ headless: true, host: '127.0.0.1',
    ...(process.env.M6_STANDALONE_CHROMIUM ? { executablePath: process.env.M6_STANDALONE_CHROMIUM } : {}) });
  evidence.browser = { pid: browserServer.process().pid, executable: browserServer.process().spawnfile, argv: browserServer.process().spawnargs };
  browser = await chromium.connect(browserServer.wsEndpoint());
  const context = await browser.newContext({ viewport: evidence.viewport, isMobile: true, hasTouch: true, serviceWorkers: 'block' });
  page = await context.newPage(); page.setDefaultTimeout(15000); page.on('pageerror', e => evidence.errors.push(e.message));
  await page.goto(app.previewUrl); await page.locator('#demo-start').click();
  await page.waitForFunction(() => !document.getElementById('create-title').disabled);
  evidence.absent = await absent();
  const task = await create('M6 actual standalone node version'); await propose('node-version');
  const running = await approve(); await waitText('execution-result', 'Cleanup verified: true');
  const done = (await api(`/api/tasks/${task.id}`)).value.task;
  assert.equal(done.execution.id, running.execution.id); assert.equal(done.proposalStatus, 'completed');
  assert.equal(done.execution.result.rootExitCode, 0); assert.match(done.execution.result.stdout, /^v\d+\.\d+\.\d+\r?\n$/);
  assert.equal(done.execution.result.cleanupVerified, true);
  const beforeReplay = rows(); const launchesBeforeReplay = (await f.launches()).length;
  const replay = await api(`/api/tasks/${task.id}/approve`, { revision: running.execution.approvalRevision });
  assert.equal(replay.status, 200); assert.deepEqual(replay.value.task, done);
  assert.deepEqual(rows(), beforeReplay); assert.equal((await f.launches()).length, launchesBeforeReplay);
  evidence.stages.push({ stage: 'approve actual version and replay once', running, done, replay, rows: beforeReplay, inspection: await inspectResult(),
    rendered: await page.locator('#execution-result').innerText() });
  await page.screenshot({ path: path.join(f.directory, 'node-version-390x844.png') });
  await propose('node-version'); const launchesBeforeDeny = (await f.launches()).length;
  await page.locator('#deny-command').click(); await waitText('proposal-state', 'Denied');
  const denied = (await api(`/api/tasks/${task.id}`)).value.task;
  assert.equal(denied.proposalStatus, 'denied'); assert.equal(denied.execution, null);
  assert.equal(rows().task_executions.length, 1); assert.equal((await f.launches()).length, launchesBeforeDeny);
  evidence.stages.push({ stage: 're-propose and deny without execution', denied, rows: rows() });
  const cancelTask = await create('M6 actual standalone cancellation'); await propose('m3-slow');
  const cancelling = await approve(); const cancelTree = await nativeTree();
  await page.locator('#cancel-command').click(); await waitText('execution-result', 'Cleanup verified: true');
  const cancelled = (await api(`/api/tasks/${cancelTask.id}`)).value.task;
  assert.equal(cancelled.execution.id, cancelling.execution.id); assert.equal(cancelled.execution.result.cancelled, true);
  assert.equal(cancelled.execution.result.cleanupVerified, true); assert.equal(cancelled.execution.result.rootPid, cancelTree[1].pid);
  assert.notEqual(cancelled.execution.result.rootExitCode, 0);
  // Cancel may precede the descendant's first stdout flush. The retained native
  // handles prove both identities; require the real root's start output rather
  // than delaying cancellation or requiring output that has not occurred.
  assert.match(cancelled.execution.result.stdout,
    new RegExp(`M3 slow root ${cancelTree[1].pid}; descendant ${cancelTree[2].pid}; started`));
  assert.doesNotMatch(cancelled.execution.result.stdout, /completed/);
  evidence.stages.push({ stage: 'actual slow-command Cancel', cancelling, cancelled, nativeExits: await exited(cancelTree), rows: rows(), inspection: await inspectResult(),
    rendered: await page.locator('#execution-result').innerText() });
  await page.screenshot({ path: path.join(f.directory, 'cancel-390x844.png') });
  const crashTask = await create('M6 actual standalone crash recovery'); await propose('m3-slow');
  const crashing = await approve(); const crashTree = await nativeTree(); const beforeCrash = rows();
  const old = app; await f.monitor.call('kill', old.identity); await old.closed; await f.stop(old);
  const crashExits = await exited([old.identity, ...crashTree]);
  app = await f.boot(Number(new URL(old.previewUrl).port)); assert.equal(app.previewUrl, old.previewUrl);
  await page.reload(); await page.waitForFunction(() => !document.getElementById('demo-start').disabled);
  await page.locator('#demo-start').click(); await page.waitForFunction(() => !document.getElementById('create-title').disabled);
  await page.locator('#tab-workroom').click(); await page.locator('#tasks button').filter({ hasText: crashTask.title }).click();
  const recovered = (await api(`/api/tasks/${crashTask.id}`)).value.task;
  assert.equal(recovered.proposalStatus, 'failed'); assert.equal(recovered.execution.state, 'failed');
  assert.equal(recovered.execution.id, crashing.execution.id); assert.equal(recovered.execution.result.status, 'UNKNOWN');
  assert.equal(recovered.execution.result.reason, 'server_restart'); assert.equal(recovered.status, 'open');
  for (const field of ['rootPid','rootExitCode','stdout','stderr','cleanupVerified','timedOut']) assert.equal(recovered.execution.result[field], null);
  await waitText('execution-result', 'State: failed'); assert.match(await page.locator('#execution-result').innerText(), /unknown/i);
  const afterCrash = rows(); const launchesBeforeCrashReplay = (await f.launches()).length;
  const crashReplay = await api(`/api/tasks/${crashTask.id}/approve`, { revision: crashing.execution.approvalRevision });
  assert.equal(crashReplay.status, 200); assert.deepEqual(crashReplay.value.task, recovered);
  assert.deepEqual(rows(), afterCrash); assert.equal((await f.launches()).length, launchesBeforeCrashReplay);
  evidence.stages.push({ stage: 'exact server kill, same store and URL, UNKNOWN replay without spawn',
    crashing, beforeCrash, recovered, afterCrash, crashReplay, crashExits, restarted: app.identity, inspection: await inspectResult(),
    rendered: await page.locator('#execution-result').innerText() });
  await page.screenshot({ path: path.join(f.directory, 'crash-recovery-390x844.png') });
  evidence.afterRestartAbsent = await absent();
  assert.deepEqual(evidence.errors, []);
  const identities = await f.monitor.call('snapshot');
  const version = identities.find(i => i.pid === done.execution.result.rootPid);
  assert.ok(version, 'Native version root identity captured'); assert.match(version.commandLine, /--version/);
  assert.equal(version.exitSignaled, true); assert.equal(version.exitCode, 0); evidence.versionNative = version;
  const serviceChildren = identities.filter(i => /tailscale.exe|mesh_runtime|inference-observation/i.test(i.commandLine ?? ''));
  assert.deepEqual(serviceChildren, []); evidence.status = 'PASS';
} catch (error) { evidence.status = 'FAIL'; evidence.failure = error.stack; throw error; }
finally {
  await browser?.close(); await browserServer?.close();
  if (browserServer) { evidence.browser.exitCode = browserServer.process().exitCode; evidence.browser.signalCode = browserServer.process().signalCode; }
  for (const launched of f.apps) await f.stop(launched);
  for (let n = 0; n < 80; n++) {
    const ids = await f.monitor.call('snapshot');
    evidence.cleanup = ids;
    if (ids.filter(i => ![process.pid, f.monitor.child.pid].includes(i.pid)).every(i => i.exitSignaled)) break;
    await delay(25);
  }
  evidence.launches = await f.launches(); await f.save('browser-proof.json', evidence); await f.monitor.finish();
  assert.ok(evidence.cleanup.filter(i => ![process.pid, f.monitor.child.pid].includes(i.pid)).every(i => i.exitSignaled), 'All original owned child handles exited');
}
console.log(JSON.stringify({ status: evidence.status, dataDir: f.dataDir, url: app.previewUrl, stages: evidence.stages.map(s => s.stage) }));
