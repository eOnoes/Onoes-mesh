import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { spawn, execFileSync } from 'node:child_process';
import { once } from 'node:events';
import { randomUUID } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { DatabaseSync } from 'node:sqlite';
import path from 'node:path';
import { ROOT } from '../server.mjs';
import { openTaskStore } from '../lib/task-store.mjs';

const proposal = { command: 'node --version', cwd: '.' };
const tripwire = `import cp from 'node:child_process'; import {syncBuiltinESMExports} from 'node:module';
for (const name of ['spawn','spawnSync','exec','execSync','execFile','execFileSync','fork']) {
 cp[name] = () => { console.error('M2_EXECUTOR_INVOKED'); throw new Error('executor tripwire'); };
} syncBuiltinESMExports();`;
async function fixture(t, noExecutor = false) {
  const dataDir = `test/app03-m2-approve-${randomUUID()}`;
  const filename = path.join(ROOT, dataDir, 'tasks.sqlite'); const children = [];
  async function stop(app) {
    if (app.child.exitCode !== null || app.child.signalCode !== null) return;
    const exit = once(app.child, 'exit'); app.child.kill(); await exit;
    if (noExecutor === true) assert.doesNotMatch(app.errors(), /M2_EXECUTOR_INVOKED/);
  }
  t.after(async () => { for (const app of children) await stop(app); });
  async function boot(port = 0) {
    const child = spawn(process.execPath, [...(noExecutor ? ['--import', 'data:text/javascript,' + encodeURIComponent(tripwire)] : []), 'server.mjs'], {
      cwd: ROOT, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, MESH_PORT: String(port), MESH_DATA_DIR: dataDir,
        // Isolated native Python must ignore these ambient runtime claims.
        PYTHONPATH: path.join(ROOT, dataDir, 'hostile-python'), PYTHONHOME: path.join(ROOT, dataDir, 'missing-python') }
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
  return { boot, stop, dataDir, filename };
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
async function create(app, proof, title = 'M2 approval task') {
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

test('M2 approval real HTTP/process/SQLite: exact node result survives server restart; repropose/deny creates no run', async t => {
  assert.equal(process.platform, 'win32', 'Native Windows required; no skips');
  const f = await fixture(t); const first = await f.boot(); const proof = await admit(first);
  const other = await create(first, proof, 'Preserved other task');
  let task = await create(first, proof); const route = `/api/tasks/${task.id}`;
  task = await propose(first, proof, task);
  const replies = await Promise.all([0, 1].map(() => mutate(first, proof, route + '/approve', { revision: task.revision })));
  assert.deepEqual(replies.map(r => r.status).sort(), [200, 202]);
  assert.equal(replies[0].json().task.execution.id, replies[1].json().task.execution.id);
  const running = replies.find(r => r.status === 202).json().task;
  assert.equal(running.proposalStatus, 'running'); assert.equal(running.execution.result, null);
  const expected = await finished(first, proof, task.id);
  assert.equal(expected.proposalStatus, 'completed'); assert.equal(expected.status, 'open');
  assert.deepEqual(expected.proposal, proposal);
  assert.deepEqual(expected.execution.argv, [process.execPath, '--version']);
  assert.equal(expected.execution.actualCwd, ROOT);
  assert.deepEqual(expected.execution.result, { status: 'PASS', rootPid: expected.execution.result.rootPid,
    rootExitCode: 0, timedOut: false, cleanupVerified: true, error: null, stdout: process.version + '\r\n', stderr: '' });
  assert.ok(expected.execution.result.rootPid > 0);
  assert.deepEqual((await mutate(first, proof, route + '/approve', { revision: expected.revision })).json().task, expected);
  inspect(f.filename, db => assert.equal(db.prepare('SELECT count(*) AS n FROM task_executions').get().n, 1));
  await f.stop(first); const second = await f.boot(Number(new URL(first.url).port));
  assert.notEqual(first.child.pid, second.child.pid); assert.equal(first.url, second.url);
  denied(await request(second, route, { headers: proof }), 401);
  const current = await admit(second);
  assert.deepEqual(await get(second, current, task.id), expected);
  assert.deepEqual(await get(second, current, other.id), other);
  task = await propose(second, current, expected);
  assert.equal(task.execution, null); assert.equal(task.proposalStatus, 'pending');
  const denial = await mutate(second, current, route + '/deny', { revision: task.revision }); assert.equal(denial.status, 200);
  const deniedTask = denial.json().task; assert.equal(deniedTask.proposalStatus, 'denied'); assert.equal(deniedTask.execution, null);
  inspect(f.filename, db => {
    assert.equal(db.prepare('SELECT count(*) AS n FROM task_executions').get().n, 1);
    assert.equal(db.prepare('SELECT count(*) AS n FROM task_executions WHERE proposalRevision=?').get(task.revision).n, 0);
    assert.equal(db.prepare('SELECT count(*) AS n FROM task_proposals WHERE taskId=?').get(task.id).n, 1);
  });
  await f.stop(second); const third = await f.boot(); const thirdProof = await admit(third);
  assert.deepEqual(await get(third, thirdProof, task.id), deniedTask);
  assert.equal((await propose(third, thirdProof, deniedTask)).proposalStatus, 'pending');
  console.log(`M2 APPROVAL PROOF: URL ${second.url}/; task ${task.id}; run ${expected.execution.id}; root PID ${expected.execution.result.rootPid}; stdout ${JSON.stringify(expected.execution.result.stdout)}; exit 0; cleanup true; server PID ${first.child.pid} -> ${second.child.pid}; denial has no run; retained ${f.dataDir}`);
});

test('M2 deny real HTTP: executor tripwire remains untouched through propose, deny and restart', async t => {
  const f = await fixture(t, true); const app = await f.boot(); const proof = await admit(app);
  const task = await propose(app, proof, await create(app, proof)); const route = `/api/tasks/${task.id}`;
  const res = await mutate(app, proof, route + '/deny', { revision: task.revision }); assert.equal(res.status, 200);
  const expected = res.json().task;
  assert.equal(expected.proposalStatus, 'denied'); assert.equal(expected.execution, null); assert.equal(expected.status, 'open');
  inspect(f.filename, db => assert.equal(db.prepare('SELECT count(*) AS n FROM task_executions').get().n, 0));
  await f.stop(app); const restarted = await f.boot(); const current = await admit(restarted);
  assert.deepEqual(await get(restarted, current, task.id), expected);
  assert.doesNotMatch(app.errors() + restarted.errors(), /M2_EXECUTOR_INVOKED/);
});

test('M2 approve/deny actual boundary: auth, origin, CSRF, revision, fields and methods fail without executor/records', async t => {
  const f = await fixture(t, true); const app = await f.boot(); const proof = await admit(app);
  const task = await propose(app, proof, await create(app, proof));
  for (const decision of ['approve','deny']) {
    const route = `/api/tasks/${task.id}/${decision}`; const body = JSON.stringify({ revision: task.revision });
    const headers = { ...proof, Origin: app.url, 'Content-Type': 'application/json' };
    denied(await request(app, route, { method: 'POST', headers: { Origin: app.url, 'Content-Type': 'application/json' }, body }), 401);
    for (const changes of [{ 'X-Trial-CSRF': 'wrong' }, { Origin: 'null' }, { Origin: 'https://evil.example' }, { Host: 'localhost' }])
      denied(await request(app, route, { method: 'POST', headers: { ...headers, ...changes }, body }), 403);
    for (const field of ['Origin','X-Trial-CSRF']) { const missing = { ...headers }; delete missing[field]; denied(await request(app, route, { method: 'POST', headers: missing, body }), 403); }
    for (const invalid of [{}, { revision: 0 }, { revision: '2' }, { revision: task.revision, argv: ['evil'] },
      { revision: task.revision, cwd: '..' }, { revision: task.revision, env: {} }, { revision: task.revision, approval: true }])
      assert.equal((await mutate(app, proof, route, invalid)).status, 400);
    denied(await mutate(app, proof, route, { revision: task.revision, actor: 'Eddie' }), 403);
    assert.equal((await mutate(app, proof, route, { revision: 1 })).status, 409);
    assert.equal((await request(app, route, { headers: proof })).status, 405);
    assert.equal((await mutate(app, proof, route, { revision: task.revision }, 'PATCH')).status, 405);
  }
  assert.deepEqual(await get(app, proof, task.id), task);
  inspect(f.filename, db => assert.equal(db.prepare('SELECT count(*) AS n FROM task_executions').get().n, 0));
  assert.doesNotMatch(app.errors(), /M2_EXECUTOR_INVOKED/);
});

test('M2 git status executes only fixed argv at actual repo root through native custody', async t => {
  const f = await fixture(t); const app = await f.boot(); const proof = await admit(app);
  const task = await propose(app, proof, await create(app, proof), { command: 'git status', cwd: '.' });
  const res = await mutate(app, proof, `/api/tasks/${task.id}/approve`, { revision: task.revision }); assert.equal(res.status, 202);
  const done = await finished(app, proof, task.id);
  assert.equal(done.proposalStatus, 'completed', JSON.stringify(done.execution.result));
  assert.deepEqual(done.execution.argv, ['C:\\Program Files\\Git\\cmd\\git.exe', 'status']);
  assert.equal(done.execution.actualCwd, ROOT);
  const branch = execFileSync('C:\\Program Files\\Git\\cmd\\git.exe', ['symbolic-ref', '--short', 'HEAD'], { cwd: ROOT, windowsHide: true, encoding: 'utf8' }).trim();
  assert.ok(done.execution.result.stdout.startsWith(`On branch ${branch}\n`));
  assert.equal(done.execution.result.rootExitCode, 0); assert.equal(done.execution.result.cleanupVerified, true);
});

test('M2 invalid persistence rejects approval/denial and preserves exact bytes with no executor', async t => {
  const f = await fixture(t, true); await mkdir(path.dirname(f.filename), { recursive: true });
  await writeFile(f.filename, 'retained invalid M2 approval persistence'); const before = await readFile(f.filename);
  const app = await f.boot(); const proof = await admit(app);
  for (const decision of ['approve','deny']) assert.equal((await mutate(app, proof, `/api/tasks/${randomUUID()}/${decision}`, { revision: 1 })).status, 503);
  assert.deepEqual(await readFile(f.filename), before);
});

test('M2 invalid completed cleanup cannot be accepted after restart; data remains intact', async t => {
  const f = await fixture(t); const app = await f.boot(); const proof = await admit(app);
  const task = await propose(app, proof, await create(app, proof));
  assert.equal((await mutate(app, proof, `/api/tasks/${task.id}/approve`, { revision: task.revision })).status, 202);
  const done = await finished(app, proof, task.id); await f.stop(app);
  inspect(f.filename, db => db.prepare('UPDATE task_executions SET result=? WHERE id=?').run(
    JSON.stringify({ ...done.execution.result, cleanupVerified: false }), done.execution.id), false);
  const before = await readFile(f.filename); const restarted = await f.boot(); const current = await admit(restarted);
  assert.equal((await request(restarted, '/api/health', { headers: current })).status, 503);
  assert.equal((await mutate(restarted, current, `/api/tasks/${task.id}/approve`, { revision: done.revision })).status, 503);
  assert.deepEqual(await readFile(f.filename), before);
});

test('M2 additive v2 migration preserves saved pending proposal and all task fields; deny still has zero runs', async t => {
  const f = await fixture(t, true); await mkdir(path.dirname(f.filename), { recursive: true });
  const task = { id: randomUUID(), title: 'Existing M2 proposal', description: 'Preserved description', label: 'Preserved label',
    status: 'done', revision: 8, createdAt: '2026-10-03T00:00:00.000Z', updatedAt: '2026-10-03T01:00:00.000Z' };
  inspect(f.filename, db => {
    db.exec(`CREATE TABLE tasks (id TEXT PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL,label TEXT NOT NULL,
      status TEXT NOT NULL CHECK(status IN ('open','done')),revision INTEGER NOT NULL CHECK(revision>0),createdAt TEXT NOT NULL,updatedAt TEXT NOT NULL);
      CREATE TABLE task_proposals (taskId TEXT PRIMARY KEY REFERENCES tasks(id),command TEXT NOT NULL,cwd TEXT NOT NULL CHECK(cwd='.'),status TEXT NOT NULL CHECK(status='pending')); PRAGMA user_version=2;`);
    db.prepare('INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?)').run(...Object.values(task));
    db.prepare("INSERT INTO task_proposals VALUES (?,?,?,'pending')").run(task.id, proposal.command, proposal.cwd);
  }, false);
  const app = await f.boot(); const proof = await admit(app);
  assert.deepEqual(await get(app, proof, task.id), { ...task, proposal, proposalStatus: 'pending', execution: null });
  const res = await mutate(app, proof, `/api/tasks/${task.id}/deny`, { revision: 8 }); assert.equal(res.status, 200);
  assert.equal(res.json().task.status, 'done'); assert.equal(res.json().task.proposalStatus, 'denied');
  inspect(f.filename, db => { assert.equal(db.prepare('PRAGMA user_version').get().user_version, 5);
    assert.equal(db.prepare('SELECT count(*) AS n FROM task_executions').get().n, 0); });
});

test('M2 store busy claim prevents proposal replacement and duplicate decisions before any process runs', async () => {
  const dataDir = `test/app03-m2-approve-busy-${randomUUID()}`; await mkdir(path.join(ROOT, dataDir), { recursive: true });
  const filename = path.join(ROOT, dataDir, 'tasks.sqlite'); const store = openTaskStore(filename);
  try {
    let task = store.propose(store.create({ title: 'Busy store proof' }).id, { proposal, revision: 1 });
    task = store.decide(task.id, { revision: task.revision }, true, { argv: [process.execPath, '--version'], cwd: ROOT }).task;
    assert.equal(task.proposalStatus, 'approved');
    assert.throws(() => store.propose(task.id, { proposal, revision: task.revision }), /busy/);
    assert.deepEqual(store.decide(task.id, { revision: task.revision }, true), { task, replayed: true });
    store.running(task.id, task.execution.id);
    assert.throws(() => store.propose(task.id, { proposal, revision: task.revision }), /busy/);
    const failed = store.finish(task.id, task.execution.id, { status: 'FAIL', rootPid: null, rootExitCode: null,
      timedOut: false, cleanupVerified: false, error: 'Synthetic store-only unavailable bridge', stdout: '', stderr: '' });
    assert.equal(failed.proposalStatus, 'failed'); assert.equal(failed.status, 'open');
    assert.equal(store.propose(task.id, { proposal, revision: failed.revision }).proposalStatus, 'pending');
  } finally { store.close(); }
});

test('M2 unavailable bridge persists failure without fabricated exit/cleanup and permits a new proposal', async t => {
  const f = await fixture(t, 'unavailable'); const app = await f.boot(); const proof = await admit(app);
  const task = await propose(app, proof, await create(app, proof));
  assert.equal((await mutate(app, proof, `/api/tasks/${task.id}/approve`, { revision: task.revision })).status, 202);
  const done = await finished(app, proof, task.id);
  assert.equal(done.proposalStatus, 'failed'); assert.equal(done.status, 'open');
  assert.equal(done.execution.result.rootPid, null); assert.equal(done.execution.result.rootExitCode, null);
  assert.equal(done.execution.result.cleanupVerified, false); assert.match(done.execution.result.error, /executor tripwire/);
  assert.equal((await propose(app, proof, done)).proposalStatus, 'pending');
  assert.match(app.errors(), /M2_EXECUTOR_INVOKED/); // Bridge spawn was blocked before child creation.
});
