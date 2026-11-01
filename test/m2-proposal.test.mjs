import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { randomUUID } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { DatabaseSync } from 'node:sqlite';
import path from 'node:path';
import { ROOT } from '../server.mjs';

const proposal = { command: 'node --version', cwd: '.' };
const subtree = name => `test/app03-m2-approve-proposal-${name}-${randomUUID()}`;
// Installed in the actual server process before its application imports. A
// proposal attempting any Node executor fails and leaves an observable marker.
const tripwire = `import cp from 'node:child_process'; import {syncBuiltinESMExports} from 'node:module';
for (const name of ['spawn','spawnSync','exec','execSync','execFile','execFileSync','fork']) {
 cp[name] = () => { console.error('M2_EXECUTOR_INVOKED'); throw new Error('M2 cannot execute'); };
} syncBuiltinESMExports(); console.error('M2_EXECUTION_TRIPWIRE_READY');`;

async function processFixture(t, dataDir = subtree('http')) {
  const children = [];
  async function stop(app) {
    if (app.child.exitCode !== null || app.child.signalCode !== null) return;
    const exit = once(app.child, 'exit'); app.child.kill(); await exit;
    assert.doesNotMatch(app.errors(), /M2_EXECUTOR_INVOKED/);
  }
  t.after(async () => { for (const app of children) await stop(app); });
  async function boot(port = 0) {
    const child = spawn(process.execPath, ['--import', 'data:text/javascript,' + encodeURIComponent(tripwire), 'server.mjs'], {
      cwd: ROOT, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, MESH_PORT: String(port), MESH_DATA_DIR: dataDir }
    });
    let output = ''; let errors = '';
    const app = { child, errors: () => errors }; children.push(app);
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
    assert.equal(info.event, 'mesh_listening'); assert.equal(info.dataDir, dataDir);
    assert.match(errors, /M2_EXECUTION_TRIPWIRE_READY/);
    app.url = info.url;
    return app;
  }
  return { boot, stop, dataDir, filename: path.join(ROOT, dataDir, 'tasks.sqlite') };
}
function request(app, route, { method = 'GET', headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request(app.url + route, { method, headers }, res => {
      const chunks = []; res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers,
        text: Buffer.concat(chunks).toString(), json() { return JSON.parse(this.text); } }));
    });
    req.on('error', reject); req.end(body);
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
async function create(app, proof, title = 'M2 saved task') {
  const res = await mutate(app, proof, '/api/tasks', { title }); assert.equal(res.status, 201); return res.json().task;
}
function guardDenied(res, status) {
  assert.equal(res.status, status); assert.equal(res.text, ''); assert.equal(res.headers['cache-control'], 'no-store');
}
function inspect(filename, operation) {
  const db = new DatabaseSync(filename, { readOnly: true });
  try { return operation(db); } finally { db.close(); }
}

test('M2 real HTTP + SQLite: saved task -> proposal -> read -> actual process restart -> same pending proposal, no executor', async t => {
  const f = await processFixture(t); const first = await f.boot(); const proof = await admit(first);
  const catalog = await request(first, '/api/commands', { headers: proof }); assert.equal(catalog.status, 200);
  assert.deepEqual(catalog.json().commands, [
    { id: 'node-version', command: 'node --version', cwd: '.' }, { id: 'git-status', command: 'git status', cwd: '.' },
    { id: 'm3-slow', command: 'node lib/slow-command.mjs', cwd: '.' }
  ]);
  const task = await create(first, proof); const other = await create(first, proof, 'Other task');
  const route = `/api/tasks/${task.id}`;
  const saved = await mutate(first, proof, route + '/proposal', { proposal, revision: task.revision });
  assert.equal(saved.status, 200); const expected = saved.json().task;
  assert.deepEqual(expected.proposal, proposal); assert.equal(expected.proposalStatus, 'pending'); assert.equal(expected.revision, 2);
  assert.deepEqual((await request(first, route, { headers: proof })).json().task, expected);
  assert.deepEqual((await request(first, `/api/tasks/${other.id}`, { headers: proof })).json().task, other);
  inspect(f.filename, db => {
    assert.equal(db.prepare('PRAGMA user_version').get().user_version, 5);
    assert.deepEqual({ ...db.prepare('SELECT * FROM task_proposals').get() }, { taskId: task.id, ...proposal, status: 'pending' });
  });
  await f.stop(first); const second = await f.boot(Number(new URL(first.url).port));
  assert.notEqual(first.child.pid, second.child.pid); assert.equal(first.url, second.url);
  guardDenied(await request(second, route, { headers: proof }), 401);
  const current = await admit(second);
  assert.deepEqual((await request(second, route, { headers: current })).json().task, expected);
  assert.deepEqual((await request(second, '/api/tasks', { headers: current })).json().tasks, [expected, other]);
  console.log(`M2 restart proof: ${second.url}/; task ${task.id}; store ${f.dataDir}; PID ${first.child.pid} -> ${second.child.pid}; exact pending ${JSON.stringify(proposal)}; executor tripwire untouched`);
});

test('M2 real HTTP: exact whitelist/cwd/fields and task revision; one current proposal; edits preserve proposals', async t => {
  const f = await processFixture(t); const app = await f.boot(); const proof = await admit(app);
  const task = await create(app, proof); const route = `/api/tasks/${task.id}`;
  const invalid = [
    { proposal: { command: 'node --version; git status', cwd: '.' }, revision: 1 },
    { proposal: { command: 'node --version ', cwd: '.' }, revision: 1 },
    { proposal: { command: 'node-version', cwd: '.' }, revision: 1 },
    ...['..', './', 'D:/Dev/Onoes-Mesh', ROOT, '', null].map(cwd => ({ proposal: { ...proposal, cwd }, revision: 1 })),
    { proposal: { ...proposal, env: {} }, revision: 1 }, { proposal: { ...proposal, id: 'node-version' }, revision: 1 },
    { proposal: { command: 'node --version' }, revision: 1 }, { proposal: [], revision: 1 },
    { proposal, revision: 1, extra: true }, { proposal }, { proposal, revision: 0 }, { proposal, revision: '1' }
  ];
  for (const body of invalid) {
    const res = await mutate(app, proof, route + '/proposal', body);
    assert.equal(res.status, 400, JSON.stringify(body)); assert.match(res.json().error, /whitelist|cwd|exactly|revision/);
    assert.deepEqual((await request(app, route, { headers: proof })).json().task, task);
  }
  assert.equal((await mutate(app, proof, `/api/tasks/${randomUUID()}/proposal`, { proposal, revision: 1 })).status, 404);
  assert.equal((await mutate(app, proof, '/api/tasks', { title: 'Injected', proposal })).status, 400);
  const outcomes = await Promise.all(['node --version', 'git status'].map(command => mutate(app, proof, route + '/proposal', { proposal: { command, cwd: '.' }, revision: 1 })));
  assert.deepEqual(outcomes.map(res => res.status).sort(), [200, 409]);
  const saved = outcomes.find(res => res.status === 200).json().task;
  assert.equal((await mutate(app, proof, route, { title: task.title, revision: 1 }, 'PATCH')).status, 409);
  const replaced = await mutate(app, proof, route + '/proposal', { proposal: { command: 'git status', cwd: '.' }, revision: saved.revision });
  assert.equal(replaced.status, 200); assert.equal(replaced.json().task.revision, 3);
  const edited = await mutate(app, proof, route, { title: 'Edited', revision: 3 }, 'PATCH');
  assert.equal(edited.status, 200); assert.deepEqual(edited.json().task.proposal, { command: 'git status', cwd: '.' });
  assert.equal(edited.json().task.proposalStatus, 'pending'); assert.equal(edited.json().task.revision, 4);
  inspect(f.filename, db => assert.equal(db.prepare('SELECT count(*) AS count FROM task_proposals WHERE taskId=?').get(task.id).count, 1));
  assert.equal((await mutate(app, proof, route + '/proposal', { proposal, revision: 4 }, 'PATCH')).status, 405);
  assert.equal((await request(app, route + '/proposal', { headers: proof })).status, 405);
});

test('M2 real HTTP: unadmitted, origin, CSRF and authority claims denied without writes or executor', async t => {
  const f = await processFixture(t); const app = await f.boot(); const proof = await admit(app); const task = await create(app, proof);
  const route = `/api/tasks/${task.id}/proposal`; const body = JSON.stringify({ proposal, revision: 1 });
  const headers = { ...proof, Origin: app.url, 'Content-Type': 'application/json' };
  guardDenied(await request(app, route, { method: 'POST', headers: { Origin: app.url, 'Content-Type': 'application/json' }, body }), 401);
  guardDenied(await request(app, '/api/commands'), 401);
  for (const changes of [{ 'X-Trial-CSRF': 'wrong' }, { Origin: 'null' }, { Origin: 'https://evil.example' }, { Host: 'localhost' }])
    guardDenied(await request(app, route, { method: 'POST', headers: { ...headers, ...changes }, body }), 403);
  const noCsrf = { ...headers }; delete noCsrf['X-Trial-CSRF'];
  guardDenied(await request(app, route, { method: 'POST', headers: noCsrf, body }), 403);
  const noOrigin = { ...headers }; delete noOrigin.Origin;
  guardDenied(await request(app, route, { method: 'POST', headers: noOrigin, body }), 403);
  for (const claim of [{ actor: 'Eddie' }, { capabilities: ['execute'] }])
    guardDenied(await mutate(app, proof, route, { proposal, revision: 1, ...claim }), 403);
  for (const claim of [{ approval: true }, { grants: ['execute'] }])
    assert.equal((await mutate(app, proof, route, { proposal, revision: 1, ...claim })).status, 400);
  assert.deepEqual((await request(app, `/api/tasks/${task.id}`, { headers: proof })).json().task, task);
  inspect(f.filename, db => assert.equal(db.prepare('SELECT count(*) AS count FROM task_proposals').get().count, 0));
});

test('M2 additive migration preserves an existing v1 task and persists its proposal across real restart', async t => {
  const f = await processFixture(t, subtree('migration')); await mkdir(path.dirname(f.filename), { recursive: true });
  const task = { id: randomUUID(), title: 'Existing M1 task', description: 'Retained', label: 'local', status: 'open', revision: 7,
    createdAt: '2026-10-03T00:00:00.000Z', updatedAt: '2026-10-03T01:00:00.000Z' };
  const db = new DatabaseSync(f.filename);
  db.exec(`CREATE TABLE tasks (id TEXT PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL,label TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('open','done')),revision INTEGER NOT NULL CHECK(revision>0),createdAt TEXT NOT NULL,updatedAt TEXT NOT NULL); PRAGMA user_version=1;`);
  db.prepare('INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?)').run(...Object.values(task)); db.close();
  const first = await f.boot(); const proof = await admit(first); const route = `/api/tasks/${task.id}`;
  assert.deepEqual((await request(first, route, { headers: proof })).json().task, task);
  const saved = await mutate(first, proof, route + '/proposal', { proposal, revision: 7 }); assert.equal(saved.status, 200);
  assert.deepEqual(saved.json().task.proposal, proposal); assert.equal(saved.json().task.revision, 8);
  await f.stop(first); const second = await f.boot(); const current = await admit(second);
  assert.deepEqual((await request(second, route, { headers: current })).json().task, saved.json().task);
});

test('M2 preserves invalid existing data without migration or proposal writes', async t => {
  const f = await processFixture(t, subtree('invalid')); await mkdir(path.dirname(f.filename), { recursive: true });
  await writeFile(f.filename, 'M2 invalid synthetic persistence'); const before = await readFile(f.filename);
  const app = await f.boot(); const proof = await admit(app);
  assert.equal((await mutate(app, proof, `/api/tasks/${randomUUID()}/proposal`, { proposal, revision: 1 })).status, 503);
  assert.deepEqual(await readFile(f.filename), before);
});
