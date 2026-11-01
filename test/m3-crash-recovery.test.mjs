import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { spawn, execFileSync } from 'node:child_process';
import { once } from 'node:events';
import { randomUUID } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { DatabaseSync } from 'node:sqlite';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { ROOT } from '../server.mjs';

const proposal = { command: 'node --version', cwd: '.' };
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
function identity(pid) {
  assert.ok(Number.isSafeInteger(pid) && pid > 0);
  return JSON.parse(execFileSync('powershell.exe', ['-NoProfile', '-Command',
    `$ownedProcess = Get-Process -Id ${pid} -ErrorAction Stop; [pscustomobject]@{pid=$ownedProcess.Id; createdAt=$ownedProcess.StartTime.ToUniversalTime().ToString('o'); executable=$ownedProcess.Path} | ConvertTo-Json -Compress`],
  { windowsHide: true, encoding: 'utf8' }));
}
async function fixture(t) {
  const dataDir = `test/app03-m3-crash-recovery-${randomUUID()}`;
  const directory = path.join(ROOT, dataDir); await mkdir(directory, { recursive: true });
  const filename = path.join(directory, 'tasks.sqlite');
  const gate = path.join(directory, 'hold-result'); const native = path.join(directory, 'native-result.json');
  const children = [];
  async function stop(app) {
    if (app.child.exitCode !== null || app.child.signalCode !== null) return;
    assert.deepEqual(identity(app.child.pid), app.identity, 'Only the exact test-created server may be terminated');
    const exit = once(app.child, 'exit'); assert.equal(app.child.kill('SIGKILL'), true); await exit;
    await writeFile(path.join(directory, `server-${app.child.pid}.log`), app.output() + '\n' + app.errors());
  }
  t.after(async () => { for (const app of children) await stop(app); });
  async function boot(port = 0, allowed = 0) {
    // Launch the unchanged native bridge and command. Hold only delivery of its
    // real close event, after capturing its actual output, to reproduce a server
    // crash before result persistence. This is not the 10-second crash/cancel test.
    const preload = `import cp from 'node:child_process'; import fs from 'node:fs';
      import {syncBuiltinESMExports} from 'node:module';
      let remaining = ${allowed}; const spawn = cp.spawn;
      cp.spawn = (...args) => {
        if (remaining-- <= 0) { console.error('RECOVERY_SPAWN_TRIPWIRE'); throw new Error('Unexpected replay spawn'); }
        const child = spawn(...args); console.error('RECOVERY_NATIVE_SPAWN ' + child.pid);
        let stdout = ''; child.stdout.on('data', chunk => { stdout += chunk; });
        const emit = child.emit;
        child.emit = function(name, ...values) {
          if (name === 'close' && fs.existsSync(${JSON.stringify(gate)}) && fs.readFileSync(${JSON.stringify(gate)}, 'utf8') === 'hold') {
            fs.writeFileSync(${JSON.stringify(native)}, JSON.stringify({bridgePid: child.pid, bridgeExit: values[0], result: JSON.parse(stdout)}));
            const timer = setInterval(() => {
              if (fs.readFileSync(${JSON.stringify(gate)}, 'utf8') !== 'hold') { clearInterval(timer); emit.call(child, name, ...values); }
            }, 10); return true;
          }
          return emit.call(this, name, ...values);
        }; return child;
      }; syncBuiltinESMExports();`;
    const preloadPath = path.join(directory, `preload-${children.length}.mjs`); await writeFile(preloadPath, preload);
    const child = spawn(process.execPath, ['--import', pathToFileURL(preloadPath).href, 'server.mjs'], {
      cwd: ROOT, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, MESH_PORT: String(port), MESH_DATA_DIR: dataDir }
    });
    let output = ''; let errors = ''; const app = { child, output: () => output, errors: () => errors }; children.push(app);
    child.stderr.on('data', chunk => { errors += chunk; });
    const info = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Startup timed out: ' + errors)), 5000);
      child.once('error', error => { clearTimeout(timer); reject(error); });
      child.once('exit', code => { clearTimeout(timer); reject(new Error('Unexpected server exit: ' + code)); });
      child.stdout.on('data', chunk => {
        output += chunk;
        const line = output.split('\n').find(line => line.startsWith('{') && line.endsWith('}'));
        if (line) { clearTimeout(timer); resolve(JSON.parse(line)); }
      });
    });
    assert.equal(info.event, 'mesh_listening'); assert.equal(info.pid, child.pid); assert.equal(info.dataDir, dataDir);
    app.identity = identity(child.pid); app.url = info.url;
    await writeFile(path.join(directory, `server-${child.pid}-identity.json`), JSON.stringify(app.identity, null, 2));
    return app;
  }
  return { boot, stop, dataDir, directory, filename, gate, native };
}
function request(app, route, { method = 'GET', headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request(app.url + route, { method, headers }, res => {
      const chunks = []; res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers,
        text: Buffer.concat(chunks).toString(), json() { return JSON.parse(this.text); } }));
    }); req.on('error', reject); req.end(body);
  });
}
async function admit(app) {
  const res = await request(app, '/api/trial-session/bootstrap', { method: 'POST',
    headers: { Origin: app.url, 'Content-Type': 'application/json' }, body: '{}' });
  assert.equal(res.status, 201);
  return { Cookie: res.headers['set-cookie'][0].split(';')[0], 'X-Trial-CSRF': res.json().csrfToken };
}
const mutate = (app, proof, route, body) => request(app, route, { method: 'POST',
  headers: { ...proof, Origin: app.url, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
async function create(app, proof, title) {
  const res = await mutate(app, proof, '/api/tasks', { title }); assert.equal(res.status, 201); return res.json().task;
}
async function propose(app, proof, task) {
  const res = await mutate(app, proof, `/api/tasks/${task.id}/proposal`, { proposal, revision: task.revision });
  assert.equal(res.status, 200, res.text); return res.json().task;
}
async function get(app, proof, id) {
  const res = await request(app, `/api/tasks/${id}`, { headers: proof }); assert.equal(res.status, 200, res.text); return res.json().task;
}
async function finished(app, proof, id) {
  for (let i = 0; i < 200; i++) {
    const task = await get(app, proof, id);
    if (['completed','failed'].includes(task.proposalStatus)) return task;
    await delay(25);
  }
  throw new Error('Native command did not finish');
}
function inspect(filename) {
  const db = new DatabaseSync(filename, { readOnly: true });
  try { return Object.fromEntries(['tasks','task_proposals','task_executions','task_proposal_decisions']
    .map(table => [table, db.prepare(`SELECT * FROM ${table} ORDER BY rowid`).all()])); }
  finally { db.close(); }
}

test('M3 real server restart recovers an interrupted persisted run as unknown, preserves data and never replays execution', async t => {
  assert.equal(process.platform, 'win32', 'Native Windows required; no skips');
  const f = await fixture(t); const first = await f.boot(0, 2); const proof = await admit(first);
  const completedProposal = await propose(first, proof, await create(first, proof, 'Preserve actual completed run'));
  assert.equal((await mutate(first, proof, `/api/tasks/${completedProposal.id}/approve`, { revision: completedProposal.revision })).status, 202);
  const completed = await finished(first, proof, completedProposal.id);
  assert.equal(completed.proposalStatus, 'completed'); assert.equal(completed.execution.result.stdout, process.version + '\r\n');
  const pending = await propose(first, proof, await create(first, proof, 'Preserve unapproved pending proposal'));
  const denialProposal = await propose(first, proof, await create(first, proof, 'Preserve denial'));
  const denied = (await mutate(first, proof, `/api/tasks/${denialProposal.id}/deny`, { revision: denialProposal.revision })).json().task;
  const saved = await propose(first, proof, await create(first, proof, 'Interrupted execution'));
  const route = `/api/tasks/${saved.id}`; await writeFile(f.gate, 'hold');
  const approval = await mutate(first, proof, route + '/approve', { revision: saved.revision });
  assert.equal(approval.status, 202); const running = approval.json().task;
  assert.equal(running.proposalStatus, 'running'); assert.equal(running.execution.result, null);
  let actual;
  for (let i = 0; i < 200; i++) {
    try { actual = JSON.parse(await readFile(f.native, 'utf8')); break; }
    catch (error) { if (error.code !== 'ENOENT') throw error; await delay(25); }
  }
  assert.ok(actual, 'Real command result reached held persistence boundary');
  assert.equal(actual.bridgeExit, 0); assert.equal(actual.result.status, 'PASS');
  assert.equal(actual.result.stdout, process.version + '\r\n'); assert.ok(actual.result.rootPid > 0);
  assert.deepEqual(await get(first, proof, saved.id), running);
  const before = inspect(f.filename);
  assert.equal(before.task_executions.find(row => row.id === running.execution.id).state, 'running');
  assert.equal(before.task_executions.find(row => row.id === running.execution.id).result, null);
  await writeFile(path.join(f.directory, 'before-restart.json'), JSON.stringify({ running, completed, pending, denied, before, actual }, null, 2));
  await f.stop(first); const port = Number(new URL(first.url).port);
  const second = await f.boot(port); assert.equal(second.url, first.url);
  assert.notEqual(second.child.pid, first.child.pid);
  assert.equal((await request(second, route, { headers: proof })).status, 401);
  const current = await admit(second); const recovered = await get(second, current, saved.id);
  await writeFile(path.join(f.directory, 'observed-restart.json'), JSON.stringify(recovered, null, 2));
  assert.equal(recovered.proposalStatus, 'failed'); assert.equal(recovered.status, 'open');
  assert.equal(recovered.execution.id, running.execution.id); assert.equal(recovered.execution.state, 'failed');
  assert.deepEqual(recovered.proposal, saved.proposal);
  for (const key of ['taskId','proposalRevision','approvalRevision','command','cwd','actualCwd','argv','startedAt'])
    assert.deepEqual(recovered.execution[key], running.execution[key]);
  assert.equal(recovered.revision, running.revision + 1);
  assert.equal(recovered.execution.result.status, 'UNKNOWN'); assert.equal(recovered.execution.result.outcome, 'unknown');
  assert.equal(recovered.execution.result.reason, 'server_restart');
  for (const field of ['rootPid','rootExitCode','stdout','stderr','cleanupVerified','timedOut']) assert.equal(recovered.execution.result[field], null);
  assert.match(recovered.execution.result.error, /interrupted.*unknown/i);
  for (const task of [completed, pending, denied]) assert.deepEqual(await get(second, current, task.id), task);
  const after = inspect(f.filename);
  for (const task of [completed, pending, denied]) {
    for (const table of Object.keys(before)) {
      const belongsToTask = row => (table === 'tasks' ? row.id : row.taskId) === task.id;
      assert.deepEqual(after[table].filter(belongsToTask), before[table].filter(belongsToTask));
    }
  }
  for (const revision of [saved.revision, running.revision, recovered.revision]) {
    const replay = await mutate(second, current, route + '/approve', { revision });
    assert.equal(replay.status, 200); assert.deepEqual(replay.json().task, recovered);
  }
  assert.deepEqual(inspect(f.filename), after);
  assert.doesNotMatch(second.errors(), /RECOVERY_NATIVE_SPAWN|RECOVERY_SPAWN_TRIPWIRE/);
  await f.stop(second); const third = await f.boot(port, 1); const thirdProof = await admit(third);
  assert.equal(third.url, first.url); assert.deepEqual(await get(third, thirdProof, saved.id), recovered);
  assert.deepEqual(inspect(f.filename), after);
  assert.deepEqual((await mutate(third, thirdProof, route + '/approve', { revision: saved.revision })).json().task, recovered);
  assert.doesNotMatch(third.errors(), /RECOVERY_NATIVE_SPAWN|RECOVERY_SPAWN_TRIPWIRE/);
  const replacement = await propose(third, thirdProof, recovered);
  assert.equal(replacement.execution, null); assert.equal(replacement.proposalStatus, 'pending');
  assert.equal((await mutate(third, thirdProof, route + '/approve', { revision: recovered.revision })).status, 409);
  await writeFile(f.gate, 'release');
  assert.equal((await mutate(third, thirdProof, route + '/approve', { revision: replacement.revision })).status, 202);
  const newDone = await finished(third, thirdProof, saved.id);
  assert.equal(newDone.proposalStatus, 'completed'); assert.notEqual(newDone.execution.id, recovered.execution.id);
  const final = inspect(f.filename);
  assert.equal(final.task_executions.length, 3);
  for (const run of after.task_executions) assert.deepEqual(final.task_executions.find(row => row.id === run.id), run);
  for (const task of [completed, pending, denied]) assert.deepEqual(await get(third, thirdProof, task.id), task);
  assert.equal(third.errors().split('RECOVERY_NATIVE_SPAWN').length - 1, 1);
  assert.doesNotMatch(first.errors() + second.errors() + third.errors(), /RECOVERY_SPAWN_TRIPWIRE/);
  const evidence = { scope: 'Real command, held native close delivery before persistence; final 10-second crash/cancel awaits bridge integration',
    dataDir: f.dataDir, url: first.url, servers: [first, second, third].map(app => app.identity),
    running, recovered, completed, pending, denied, replacement: newDone, actualUndurableResult: actual,
    repeatedRestartRowsUnchanged: true, noReplaySpawn: true };
  await writeFile(path.join(f.directory, 'proof.json'), JSON.stringify(evidence, null, 2));
  console.log('M3 RECOVERY PROOF: ' + JSON.stringify({ dataDir: f.dataDir, taskId: saved.id, runId: recovered.execution.id,
    url: first.url, servers: evidence.servers, recovered: recovered.execution.result }));
});
