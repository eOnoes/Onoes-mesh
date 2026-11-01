import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { randomUUID } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { DatabaseSync } from 'node:sqlite';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { ROOT } from '../server.mjs';

const proposal = { command: 'node --version', cwd: '.' };
async function fixture(t) {
  const dataDir = `test/app03-m3-idempotent-${randomUUID()}`;
  const filename = path.join(ROOT, dataDir, 'tasks.sqlite'); const children = [];
  await mkdir(path.dirname(filename), { recursive: true });
  const gate = path.join(ROOT, dataDir, 'preparation-gate.json');
  const entered = path.join(ROOT, dataDir, 'preparation-entered.txt');
  async function stop(app) {
    if (app.child.exitCode !== null || app.child.signalCode !== null) return;
    const exit = once(app.child, 'exit'); app.child.kill(); await exit;
    assert.doesNotMatch(app.errors(), /M3_TRIPWIRE/);
  }
  t.after(async () => { for (const app of children) await stop(app); });
  async function boot(port = 0, allowed = 1) {
    const preload = `import cp from 'node:child_process'; import fs from 'node:fs';
      import {syncBuiltinESMExports} from 'node:module';
      let remaining = ${allowed}; const spawn = cp.spawn;
      cp.spawn = (...args) => {
        if (remaining-- <= 0) { console.error('M3_TRIPWIRE'); throw new Error('replay executor tripwire'); }
        console.error('M3_EXECUTOR_SPAWN'); return spawn(...args);
      };
      for (const name of ['spawnSync','exec','execSync','execFile','execFileSync','fork'])
        cp[name] = () => { console.error('M3_TRIPWIRE'); throw new Error('replay executor tripwire'); };
      const access = fs.promises.access;
      fs.promises.access = async (...args) => {
        if (String(args[0]).endsWith('owned-command.py') && fs.existsSync(${JSON.stringify(gate)})) {
          fs.writeFileSync(${JSON.stringify(entered)}, 'entered');
          while (JSON.parse(fs.readFileSync(${JSON.stringify(gate)}, 'utf8')).hold)
            await new Promise(resolve => setTimeout(resolve, 10));
        }
        return access(...args);
      }; syncBuiltinESMExports();`;
    const preloadPath = path.join(ROOT, dataDir, `spawn-tripwire-${children.length}.mjs`);
    await writeFile(preloadPath, preload);
    const child = spawn(process.execPath, ['--import', pathToFileURL(preloadPath).href, 'server.mjs'], {
      cwd: ROOT, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, MESH_PORT: String(port), MESH_DATA_DIR: dataDir }
    });
    let output = ''; let errors = ''; const app = { child, errors: () => errors }; children.push(app);
    child.stderr.on('data', chunk => { errors += chunk; });
    const info = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Server startup timed out: ' + errors)), 5000);
      child.once('error', e => { clearTimeout(timer); reject(e); });
      child.once('exit', code => { clearTimeout(timer); reject(new Error(`Server exit ${code}: ${errors}`)); });
      child.stdout.on('data', chunk => {
        output += chunk;
        const line = output.split('\n').find(line => line.startsWith('{') && line.endsWith('}'));
        if (!line) return;
        clearTimeout(timer); resolve(JSON.parse(line));
      });
    });
    assert.equal(info.event, 'mesh_listening'); assert.equal(info.dataDir, dataDir); app.url = info.url; return app;
  }
  return { boot, stop, dataDir, filename, gate, entered };
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
const mutate = (app, proof, route, body, method = 'POST') => request(app, route, { method,
  headers: { ...proof, Origin: app.url, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
async function create(app, proof, title = 'M3 idempotent task') {
  const res = await mutate(app, proof, '/api/tasks', { title }); assert.equal(res.status, 201); return res.json().task;
}
async function propose(app, proof, task, value = proposal) {
  const res = await mutate(app, proof, `/api/tasks/${task.id}/proposal`, { proposal: value, revision: task.revision });
  assert.equal(res.status, 200, res.text); return res.json().task;
}
const get = async (app, proof, id) => {
  const res = await request(app, `/api/tasks/${id}`, { headers: proof }); assert.equal(res.status, 200, res.text); return res.json().task;
};
async function finished(app, proof, id) {
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    const task = await get(app, proof, id);
    if (['completed','failed'].includes(task.proposalStatus)) return task;
    await new Promise(resolve => setTimeout(resolve, 25));
  }
  throw new Error('Owned execution did not finish');
}
function inspect(filename, operation, readOnly = true) {
  const db = new DatabaseSync(filename, { readOnly });
  try { return operation(db); } finally { db.close(); }
}
function denied(res, status) { assert.equal(res.status, status); assert.equal(res.text, ''); assert.equal(res.headers['cache-control'], 'no-store'); }

test('M3 actual concurrent approval/replay/restart: one native result, no replay spawn, replacement fenced', async t => {
  assert.equal(process.platform, 'win32', 'Native Windows required; no skips');
  const f = await fixture(t); const first = await f.boot(); const proof = await admit(first);
  const saved = await propose(first, proof, await create(first, proof)); const route = `/api/tasks/${saved.id}`;
  // The approval request revision can differ from the saved proposal identity.
  const edited = await mutate(first, proof, route, { title: saved.title, description: 'Edited pending task',
    label: '', status: 'open', revision: saved.revision }, 'PATCH');
  assert.equal(edited.status, 200); const pending = edited.json().task;
  assert.equal((await mutate(first, proof, route + '/approve', { revision: saved.revision })).status, 409);
  const replies = await Promise.all(Array.from({ length: 8 }, () => mutate(first, proof, route + '/approve', { revision: pending.revision })));
  assert.equal(replies.filter(r => r.status === 202).length, 1);
  assert.equal(replies.filter(r => r.status === 200).length, 7);
  const done = await finished(first, proof, saved.id); const run = done.execution;
  for (const reply of replies) assert.equal(reply.json().task.execution.id, run.id);
  assert.equal(run.proposalRevision, saved.revision); assert.equal(run.approvalRevision, pending.revision);
  assert.equal(done.proposalStatus, 'completed'); assert.equal(done.status, 'open');
  assert.deepEqual(run.argv, [process.execPath, '--version']); assert.equal(run.actualCwd, ROOT);
  assert.deepEqual(run.result, { status: 'PASS', rootPid: run.result.rootPid, rootExitCode: 0, timedOut: false,
    cleanupVerified: true, error: null, stdout: process.version + '\r\n', stderr: '' });
  assert.ok(run.result.rootPid > 0);
  const originalRows = inspect(f.filename, db => ({ tasks: db.prepare('SELECT * FROM tasks').all(),
    runs: db.prepare('SELECT * FROM task_executions').all(), decisions: db.prepare('SELECT * FROM task_proposal_decisions').all() }));
  async function replay(app, session) {
    for (const revision of [pending.revision, pending.revision + 1, done.revision]) {
      const res = await mutate(app, session, route + '/approve', { revision });
      assert.equal(res.status, 200, res.text); assert.deepEqual(res.json().task, done);
      assert.equal(res.headers['cache-control'], 'no-store');
    }
    assert.deepEqual(await get(app, session, saved.id), done);
    inspect(f.filename, db => {
      assert.equal(db.prepare('SELECT count(*) AS n FROM task_executions').get().n, 1);
      assert.deepEqual({ tasks: db.prepare('SELECT * FROM tasks').all(), runs: db.prepare('SELECT * FROM task_executions').all(),
        decisions: db.prepare('SELECT * FROM task_proposal_decisions').all() }, originalRows);
    });
  }
  await replay(first, proof);
  assert.equal(first.errors().split('M3_EXECUTOR_SPAWN').length - 1, 1);
  await f.stop(first);
  const second = await f.boot(Number(new URL(first.url).port), 0);
  assert.notEqual(first.child.pid, second.child.pid); assert.equal(second.url, first.url);
  denied(await mutate(second, proof, route + '/approve', { revision: pending.revision }), 401);
  const current = await admit(second); await replay(second, current);
  // The replay branch must still pass all admission/origin/CSRF/field guards.
  const body = JSON.stringify({ revision: pending.revision });
  const headers = { ...current, Origin: second.url, 'Content-Type': 'application/json' };
  denied(await request(second, route + '/approve', { method: 'POST', headers: { Origin: second.url, 'Content-Type': 'application/json' }, body }), 401);
  for (const changes of [{ 'X-Trial-CSRF': 'wrong' }, { Origin: 'null' }, { Origin: 'https://evil.example' }, { Host: 'localhost' }])
    denied(await request(second, route + '/approve', { method: 'POST', headers: { ...headers, ...changes }, body }), 403);
  for (const field of ['Origin','X-Trial-CSRF']) {
    const missing = { ...headers }; delete missing[field];
    denied(await request(second, route + '/approve', { method: 'POST', headers: missing, body }), 403);
  }
  for (const invalid of [{}, { revision: 0 }, { revision: String(pending.revision) }, { revision: pending.revision, proposal },
    { revision: pending.revision, argv: ['evil'] }])
    assert.equal((await mutate(second, current, route + '/approve', invalid)).status, 400);
  denied(await mutate(second, current, route + '/approve', { revision: pending.revision, actor: 'Eddie' }), 403);
  assert.equal((await request(second, route + '/approve', { headers: current })).status, 405);
  assert.equal((await mutate(second, current, route + '/approve', { revision: saved.revision })).status, 409);
  await replay(second, current);
  // An identical command saved again is a distinct proposal, never a replay.
  const replacement = await propose(second, current, done);
  assert.equal(replacement.execution, null); assert.equal(replacement.proposalStatus, 'pending');
  for (const revision of [saved.revision, pending.revision, done.revision])
    assert.equal((await mutate(second, current, route + '/approve', { revision })).status, 409);
  assert.deepEqual(await get(second, current, saved.id), replacement);
  assert.doesNotMatch(second.errors(), /M3_EXECUTOR_SPAWN|M3_TRIPWIRE/);
  await f.stop(second);
  const third = await f.boot(Number(new URL(first.url).port)); const thirdProof = await admit(third);
  const next = await mutate(third, thirdProof, route + '/approve', { revision: replacement.revision });
  assert.equal(next.status, 202); const newDone = await finished(third, thirdProof, saved.id);
  assert.notEqual(newDone.execution.id, run.id); assert.equal(newDone.execution.proposalRevision, replacement.revision);
  assert.equal(newDone.proposalStatus, 'completed'); assert.equal(newDone.execution.result.stdout, process.version + '\r\n');
  assert.deepEqual((await mutate(third, thirdProof, route + '/approve', { revision: replacement.revision })).json().task, newDone);
  assert.equal((await mutate(third, thirdProof, route + '/approve', { revision: pending.revision })).status, 409);
  inspect(f.filename, db => {
    assert.equal(db.prepare('SELECT count(*) AS n FROM task_executions').get().n, 2);
    for (const revision of [saved.revision, replacement.revision])
      assert.equal(db.prepare('SELECT count(*) AS n FROM task_executions WHERE taskId=? AND proposalRevision=?').get(saved.id, revision).n, 1);
    assert.deepEqual(db.prepare('SELECT * FROM task_executions WHERE id=?').get(run.id), originalRows.runs[0]);
  });
  assert.equal(third.errors().split('M3_EXECUTOR_SPAWN').length - 1, 1);
  const evidence = { taskId: saved.id, firstRun: run, firstResultTaskRevision: done.revision,
    serverPids: [first.child.pid, second.child.pid, third.child.pid], url: first.url, countAfterRestart: 1,
    countAfterDeliberateReplacement: 2, replacementRun: newDone.execution, tripwireUntouched: true, dataDir: f.dataDir };
  await writeFile(path.join(ROOT, f.dataDir, 'proof.json'), JSON.stringify(evidence, null, 2));
  console.log('M3 IDEMPOTENT PROOF: ' + JSON.stringify(evidence));
});

test('M3 pending approval held in preparation rejects replacement and task-edit races without spawning', async t => {
  const f = await fixture(t); const app = await f.boot(0, 0); const proof = await admit(app);
  let pending = await propose(app, proof, await create(app, proof, 'M3 pending race'));
  const route = `/api/tasks/${pending.id}`;
  for (const replacement of [true, false]) {
    await writeFile(f.gate, JSON.stringify({ hold: true }));
    const approval = mutate(app, proof, route + '/approve', { revision: pending.revision });
    const deadline = Date.now() + 3000;
    while (true) {
      try { if ((await readFile(f.entered, 'utf8')) === 'entered') break; } catch (error) { if (error.code !== 'ENOENT') throw error; }
      assert.ok(Date.now() < deadline, 'Preparation gate not reached');
      await new Promise(resolve => setTimeout(resolve, 10));
    }
    if (replacement) pending = await propose(app, proof, pending, { command: 'git status', cwd: '.' });
    else {
      const edit = await mutate(app, proof, route, { title: 'Changed while pending', description: '', label: '',
        status: 'open', revision: pending.revision }, 'PATCH');
      assert.equal(edit.status, 200); pending = edit.json().task;
    }
    await writeFile(f.gate, JSON.stringify({ hold: false }));
    assert.equal((await approval).status, 409);
    assert.deepEqual(await get(app, proof, pending.id), pending);
    // Retain the signal file, but reset its content for the next preparation.
    await writeFile(f.entered, '');
  }
  inspect(f.filename, db => assert.equal(db.prepare('SELECT count(*) AS n FROM task_executions').get().n, 0));
  assert.doesNotMatch(app.errors(), /M3_EXECUTOR_SPAWN|M3_TRIPWIRE/);
  const deniedTask = (await mutate(app, proof, route + '/deny', { revision: pending.revision })).json().task;
  for (const revision of [pending.revision, deniedTask.revision])
    assert.equal((await mutate(app, proof, route + '/approve', { revision })).status, 409);
});

test('M3 additive v3 migration preserves an actual captured result and replays without execution or revision churn', async t => {
  const source = await fixture(t); const app = await source.boot(); const proof = await admit(app);
  const pending = await propose(app, proof, await create(app, proof, 'Legacy M2 completed run'));
  const route = `/api/tasks/${pending.id}/approve`;
  assert.equal((await mutate(app, proof, route, { revision: pending.revision })).status, 202);
  const done = await finished(app, proof, pending.id); assert.equal(done.proposalStatus, 'completed');
  await source.stop(app);
  const legacy = await fixture(t);
  // Materialize a separate disposable v3 database, retaining the original v4
  // source intact. Seed the exact real captured result, not a synthetic PASS.
  const tables = ['tasks','task_proposals','task_executions','task_proposal_decisions'];
  const snapshot = inspect(source.filename, db => tables.map(name => ({ name,
    sql: db.prepare('SELECT sql FROM sqlite_master WHERE name=?').get(name).sql,
    rows: db.prepare(`SELECT * FROM ${name}`).all() })));
  inspect(legacy.filename, db => {
    for (const table of snapshot) {
      db.exec(table.sql.replace(/,\s*approvalRevision INTEGER NOT NULL DEFAULT 1/, ''));
      for (const row of table.rows) {
        const { approvalRevision, ...v3 } = row;
        const values = Object.values(v3);
        db.prepare(`INSERT INTO ${table.name} VALUES (${values.map(() => '?').join(',')})`).run(...values);
      }
    }
    db.exec('PRAGMA user_version=3;');
  }, false);
  const migrated = await legacy.boot(0, 0); const current = await admit(migrated);
  for (const revision of [pending.revision, done.revision]) {
    const replay = await mutate(migrated, current, route, { revision });
    assert.equal(replay.status, 200); assert.deepEqual(replay.json().task, done);
  }
  inspect(legacy.filename, db => {
    assert.equal(db.prepare('PRAGMA user_version').get().user_version, 5);
    for (const table of snapshot) assert.deepEqual(db.prepare(`SELECT * FROM ${table.name}`).all(), table.rows);
  });
  await legacy.stop(migrated); const restarted = await legacy.boot(0, 0); const restartedProof = await admit(restarted);
  const replay = await mutate(restarted, restartedProof, route, { revision: pending.revision });
  assert.equal(replay.status, 200); assert.deepEqual(replay.json().task, done);
  assert.doesNotMatch(migrated.errors() + restarted.errors(), /M3_EXECUTOR_SPAWN|M3_TRIPWIRE/);
});
