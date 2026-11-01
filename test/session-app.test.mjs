import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import net from 'node:net';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { startApp, ROOT } from '../server.mjs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { once } from 'node:events';

const subtree = () => `test/app03-m2-approve-http-${process.pid}-${randomUUID()}`;
async function fixture(t, options = {}) {
  const app = await startApp({ dataDir: subtree(), ...options });
  t.after(() => app.close()); return app;
}
function request(app, route, { method = 'GET', headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request(app.url + route, { method, headers }, res => {
      const chunks = []; res.on('data', c => chunks.push(c));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, text: Buffer.concat(chunks).toString(), json() { return JSON.parse(this.text); } }));
    });
    req.on('error', reject); req.end(body);
  });
}
async function admit(app) {
  const res = await request(app, '/api/trial-session/bootstrap', { method: 'POST', headers: { Origin: app.url, 'Content-Type': 'application/json' }, body: '{}' });
  assert.equal(res.status, 201); assert.equal(res.headers['cache-control'], 'no-store');
  assert.equal(/HttpOnly/.test(res.headers['set-cookie'][0]), true);
  return { Cookie: res.headers['set-cookie'][0].split(';')[0], 'X-Trial-CSRF': res.json().csrfToken };
}
function denial(res, status) {
  assert.equal(res.status, status); assert.equal(res.text.length, 0);
  assert.equal(res.headers['cache-control'], 'no-store');
}
function mutation(app, proof, route, body, method = 'POST') {
  return request(app, route, { method, headers: { ...proof, Origin: app.url, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
}

test('M1 actual server process: same URL/store survive restart and stale cookie can be replaced', async t => {
  const dataDir = `test/app03-m2-approve-m1-restart-${randomUUID()}`;
  const children = [];
  t.after(async () => {
    for (const child of children) {
      if (child.exitCode !== null || child.signalCode !== null) continue;
      const exited = once(child, 'exit'); child.kill(); await exited;
    }
  });
  async function boot(port = 0) {
    const child = spawn(process.execPath, ['server.mjs'], { cwd: ROOT, windowsHide: true,
      env: { ...process.env, MESH_PORT: String(port), MESH_DATA_DIR: dataDir }, stdio: ['ignore', 'pipe', 'pipe'] });
    children.push(child);
    let output = ''; let errors = '';
    child.stderr.on('data', chunk => { errors += chunk; });
    const info = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Server startup timed out: ' + errors)), 5000);
      child.once('error', error => { clearTimeout(timer); reject(error); });
      child.once('exit', code => { clearTimeout(timer); reject(new Error(`Server exited ${code}: ${errors}`)); });
      child.stdout.on('data', chunk => {
        output += chunk;
        const line = output.split('\n').find(value => value.startsWith('{'));
        if (!line) return;
        try { const value = JSON.parse(line); clearTimeout(timer); resolve(value); } catch { /* Wait for the complete line. */ }
      });
    });
    assert.equal(info.event, 'mesh_listening'); assert.equal(info.dataDir, dataDir);
    return { url: info.url, child };
  }
  const first = await boot(); const proof = await admit(first);
  const created = await mutation(first, proof, '/api/tasks', { title: 'hello' });
  assert.equal(created.status, 201); const original = created.json().task;
  const exited = once(first.child, 'exit'); first.child.kill(); await exited;
  const second = await boot(Number(new URL(first.url).port));
  assert.equal(second.url, first.url); assert.notEqual(second.child.pid, first.child.pid);
  denial(await request(second, '/api/tasks', { headers: proof }), 401);
  const stale = await mutation(second, proof, '/api/trial-session/bootstrap', {});
  denial(stale, 401); assert.deepEqual(stale.headers['set-cookie'], ['mesh_trial=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0']);
  const current = await admit(second);
  assert.deepEqual((await request(second, '/api/tasks', { headers: current })).json().tasks, [original]);
  assert.deepEqual((await request(second, `/api/tasks/${original.id}`, { headers: current })).json().task, original);
});

test('actual HTTP: public static shell and all private routes require admission', async t => {
  const app = await fixture(t);
  for (const route of ['/', '/app.js', '/styles.css', '/pwa-register.mjs', '/sw.js', '/shell-cache-policy.mjs', '/manifest.webmanifest', '/icon.svg']) {
    const res = await request(app, route); assert.equal(res.status, 200);
    assert.equal(res.headers['cache-control'].startsWith('public'), true);
    assert.equal(res.headers['content-security-policy'].includes("img-src 'self'"), true);
    assert.equal((await request(app, route, { method: 'HEAD' })).text.length, 0);
  }
  for (const route of ['/api', '/api/health', '/api/tasks', '/api/worker-activity', '/api/service-connections', '/api/inference-observation', '/api/unknown']) denial(await request(app, route), 401);
  denial(await request(app, '/', { headers: { Host: 'localhost' } }), 403);
  denial(await request(app, '/api/tasks', { headers: { Host: 'localhost' } }), 403);
  denial(await request(app, '/api/trial-session/bootstrap', { method: 'POST', headers: { Origin: app.url, 'Content-Type': 'application/json' }, body: '{"actor":"human"}' }), 403);
  denial(await request(app, '/api/trial-session/bootstrap', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }), 403);
});

test('actual HTTP: originless proof, malformed/hostile input, body-free denials', async t => {
  const app = await fixture(t); const proof = await admit(app);
  for (const method of ['GET', 'HEAD']) {
    const good = await request(app, '/api/tasks', { method, headers: proof }); assert.equal(good.status, 200); assert.equal(good.headers['cache-control'], 'no-store');
    denial(await request(app, '/api/tasks', { method, headers: { Cookie: proof.Cookie } }), 403);
    denial(await request(app, '/api/tasks', { method, headers: { ...proof, 'X-Trial-CSRF': 'wrong' } }), 403);
    denial(await request(app, '/api/tasks', { method, headers: { ...proof, Origin: 'null' } }), 403);
  }
  denial(await request(app, '/api/tasks', { headers: { ...proof, 'Sec-Fetch-Site': 'cross-site' } }), 403);
  denial(await mutation(app, proof, '/api/tasks', { title: 'Synthetic', actor: 'human', grants: ['admin'] }), 403);
  denial(await request(app, '/api/tasks', { method: 'POST', headers: { ...proof, Origin: app.url, 'Content-Type': 'application/json' }, body: '{' }), 400);
  denial(await request(app, '/api/tasks', { method: 'POST', headers: { ...proof, Origin: app.url, 'Content-Type': 'text/plain' }, body: '{}' }), 415);
  denial(await mutation(app, proof, '/api/tasks', { title: 'x'.repeat(5000) }), 413);
  denial(await request(app, '/api/tasks', { method: 'GET', headers: { ...proof, 'Content-Length': '2' }, body: '{}' }), 400);
  denial(await request(app, '/api/tasks', { headers: ['Host', new URL(app.url).host, 'Cookie', proof.Cookie, 'X-Trial-CSRF', proof['X-Trial-CSRF'], 'X-Trial-CSRF', proof['X-Trial-CSRF']] }), 400);
  const unknown = await request(app, '/api/unknown', { headers: proof }); assert.equal(unknown.status, 404); assert.equal(unknown.headers['cache-control'], 'no-store');
});

test('actual HTTP + SQLite: create/read/edit/assignment/done/reopen/revision and restart', async t => {
  const dataDir = subtree(); let app = await startApp({ dataDir }); let closed = false;
  t.after(async () => { if (!closed) await app.close(); });
  let proof = await admit(app);
  let res = await mutation(app, proof, '/api/tasks', { title: 'Synthetic board task', description: 'Owned test only', label: 'DEMO label' });
  assert.equal(res.status, 201); let task = res.json().task; assert.equal(task.revision, 1);
  const route = `/api/tasks/${task.id}`;
  assert.equal((await request(app, route, { headers: proof })).json().task.title, 'Synthetic board task');
  const original = task;
  for (const status of ['open', 'done', 'open']) {
    res = await mutation(app, proof, route, { title: 'Edited synthetic task', description: task.description, label: 'Assigned DEMO', status, revision: task.revision }, 'PATCH');
    assert.equal(res.status, 200); const next = res.json().task; assert.equal(next.revision, task.revision + 1); assert.equal(next.status, status); assert.equal(next.label, 'Assigned DEMO'); task = next;
  }
  assert.equal((await mutation(app, proof, route, original, 'PATCH')).status, 400);
  assert.equal((await mutation(app, proof, route, { title: original.title, revision: 1 }, 'PATCH')).status, 409);
  assert.equal((await request(app, '/api/tasks', { headers: proof })).json().tasks.length, 1);
  await app.close(); closed = true;
  app = await startApp({ dataDir }); closed = false;
  denial(await request(app, '/api/tasks', { headers: proof }), 401);
  proof = await admit(app);
  const restored = (await request(app, route, { headers: proof })).json().task;
  assert.equal(restored.revision, 4); assert.equal(restored.label, 'Assigned DEMO'); assert.equal(restored.status, 'open');
  const bytes = await readFile(path.join(ROOT, dataDir, 'tasks.sqlite')); assert.equal(bytes.subarray(0, 16).toString(), 'SQLite format 3\0');
});

test('actual HTTP: logout revokes and expiry blocks further private writes', async t => {
  let now = 1000000;
  const app = await fixture(t, { sessionTtlMs: 1000, sessionNow: () => now });
  const proof = await admit(app);
  denial(await mutation(app, proof, '/api/trial-session/bootstrap', {}), 409);
  const out = await mutation(app, proof, '/api/trial-session/logout', {}); denial(out, 204);
  assert.equal(/Max-Age=0/.test(out.headers['set-cookie'][0]), true);
  denial(await request(app, '/api/tasks', { headers: proof }), 401);
  const fresh = await admit(app); now += 1000;
  denial(await mutation(app, fresh, '/api/tasks', { title: 'Expired synthetic write' }), 401);
});

test('actual HTTP: async observation expiry rechecked before private response', async t => {
  let now = 1000000;
  const app = await fixture(t, { sessionTtlMs: 1000, sessionNow: () => now, inferenceTestReader: async () => { await new Promise(r => setTimeout(r, 10)); now += 1000; return {}; } });
  const proof = await admit(app);
  denial(await request(app, '/api/inference-observation', { headers: proof }), 401);
});

test('actual HTTP: parser clientError returns no-store and zero body bytes', async t => {
  const app = await fixture(t);
  const raw = await new Promise((resolve, reject) => {
    const socket = net.connect(Number(new URL(app.url).port), '127.0.0.1'); let result = '';
    socket.setTimeout(2000, () => socket.destroy(new Error('Parser fixture timeout')));
    socket.on('error', reject); socket.on('data', data => { result += data; }); socket.on('end', () => resolve(result));
    socket.on('connect', () => socket.write('GET / HTTP/1.1\r\nHost: malformed\r\nBad Header: bad\r\n\r\n'));
  });
  assert.equal(raw.startsWith('HTTP/1.1 400'), true); assert.equal(raw.includes('Cache-Control: no-store'), true); assert.equal(raw.split('\r\n\r\n')[1], '');
});

test('actual HTTP: unexpected SQLite preserved; services remain disconnected', async t => {
  const dataDir = subtree(); await mkdir(path.join(ROOT, dataDir), { recursive: true });
  const filename = path.join(ROOT, dataDir, 'tasks.sqlite'); await writeFile(filename, 'APP03 synthetic invalid SQLite fixture');
  const before = await readFile(filename); const app = await fixture(t, { dataDir }); const proof = await admit(app);
  assert.equal((await request(app, '/api/health', { headers: proof })).status, 503);
  assert.equal((await request(app, '/api/tasks', { headers: proof })).status, 503);
  assert.equal((await readFile(filename)).equals(before), true);
  const services = (await request(app, '/api/service-connections', { headers: proof })).json().services;
  assert.equal(services.every(s => s.status === 'not_configured'), true);
  await assert.rejects(startApp({ dataDir: subtree(), port: -1 }));
  await assert.rejects(startApp({ dataDir: 'test/local-board' }));
  await assert.rejects(startApp({ dataDir: subtree(), serviceConfig: { relay: { enabled: true } } }));
});
