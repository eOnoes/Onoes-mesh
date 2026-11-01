import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { randomUUID } from 'node:crypto';
import { startApp } from '../server.mjs';

const challengeRoute = '/api/trial-session/recovery-challenge';
const completeRoute = '/api/trial-session/recovery-complete';
async function fixture(t, options = {}) {
  const app = await startApp({ dataDir: `test/app03-session-recovery-http-${randomUUID()}`, ...options });
  t.after(() => app.close());
  return app;
}
function request(app, route, { method = 'POST', headers = {}, body, rawHeaders } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request(app.url + route, { method, headers: rawHeaders ?? {
      Origin: app.url, 'Content-Type': 'application/json', ...headers,
    } }, res => {
      let text = ''; res.setEncoding('utf8'); res.on('data', value => { text += value; });
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, text,
        json: () => JSON.parse(text) }));
    });
    req.on('error', reject); req.end(body ?? (['GET', 'HEAD'].includes(method) ? undefined : '{}'));
  });
}
function denied(res, status) {
  assert.equal(res.status, status); assert.equal(res.text, '');
  assert.equal(res.headers['cache-control'], 'no-store');
  assert.equal(res.headers['set-cookie'], undefined);
}
async function admit(app) {
  const res = await request(app, '/api/trial-session/bootstrap'); assert.equal(res.status, 201);
  return { Cookie: res.headers['set-cookie'][0].split(';')[0], 'X-Trial-CSRF': res.json().csrfToken };
}
async function challenge(app, proof) {
  const res = await request(app, challengeRoute, { headers: { Cookie: proof.Cookie } });
  assert.equal(res.status, 200); assert.equal(res.headers['cache-control'], 'no-store');
  assert.equal(res.headers['set-cookie'], undefined);
  assert.deepEqual(Object.keys(res.json()).sort(), ['challenge', 'expiresAt']);
  assert.match(res.json().challenge, /^[A-Za-z0-9_-]{43}$/);
  assert.notEqual(res.json().challenge, proof['X-Trial-CSRF']);
  return { Cookie: proof.Cookie, 'X-Trial-CSRF': res.json().challenge };
}
async function read(app, proof, route = '/api/tasks') {
  // Originless reads need the existing session-bound proof.
  return request(app, route, { method: 'GET', headers: { ...proof, Origin: undefined }, body: undefined,
    rawHeaders: ['Host', new URL(app.url).host, 'Cookie', proof.Cookie, 'X-Trial-CSRF', proof['X-Trial-CSRF']] });
}

test('live cookie with cleared proof: immediate deliberate recovery preserves saved task/revision and revokes original tab', async t => {
  const app = await fixture(t); const old = await admit(app);
  const created = await request(app, '/api/tasks', { headers: old, body: JSON.stringify({ title: 'Disposable recovery task' }) });
  assert.equal(created.status, 201); const task = created.json().task;
  denied(await request(app, '/api/trial-session/bootstrap', { headers: { Cookie: old.Cookie } }), 403);
  const fresh = await challenge(app, old);
  denied(await read(app, fresh), 403);
  for (const method of ['GET', 'HEAD']) denied(await request(app, '/api/tasks', { method, headers: fresh }), 403);
  denied(await request(app, '/api/trial-session/logout', { headers: fresh }), 403);
  const done = await request(app, completeRoute, { headers: fresh }); assert.equal(done.status, 201);
  const current = { Cookie: done.headers['set-cookie'][0].split(';')[0], 'X-Trial-CSRF': done.json().csrfToken };
  assert.notEqual(current.Cookie, old.Cookie); assert.notEqual(current['X-Trial-CSRF'], old['X-Trial-CSRF']);
  assert.equal(done.json().admission, 'EXPLICIT_SYNTHETIC_DEMO');
  assert.deepEqual((await read(app, current)).json().tasks, [task]);
  denied(await read(app, old), 401);
  // Other tabs receive the rotated shared cookie, but retain a revoked proof.
  const originalTab = { Cookie: current.Cookie, 'X-Trial-CSRF': old['X-Trial-CSRF'] };
  denied(await read(app, originalTab), 403);
  denied(await request(app, '/api/tasks', { method: 'GET', headers: originalTab }), 403);
  denied(await request(app, '/api/trial-session/bootstrap', { headers: originalTab }), 403);
  for (const route of ['/api/tasks', '/api/trial-session/logout', `/api/tasks/${task.id}/approve`, `/api/tasks/${task.id}/cancel`, '/api/relay/message'])
    denied(await request(app, route, { headers: originalTab }), 403);
  for (const route of ['/api/tasks', '/api/trial-session/logout', `/api/tasks/${task.id}/approve`, `/api/tasks/${task.id}/cancel`, '/api/relay/message'])
    denied(await request(app, route, { headers: old }), 401);
  denied(await request(app, completeRoute, { headers: fresh }), 403);
  const replayWithNewCookie = { ...fresh, Cookie: current.Cookie };
  denied(await request(app, completeRoute, { headers: replayWithNewCookie }), 403);
  denied(await request(app, '/api/tasks', { method: 'GET', headers: replayWithNewCookie }), 403);
});

test('challenge and completion reject hostile boundaries/claims/headers/bodies without changing the old session or tasks', async t => {
  const app = await fixture(t); const old = await admit(app); const fresh = await challenge(app, old);
  for (const route of [challengeRoute, completeRoute]) {
    const headers = route === challengeRoute ? { Cookie: old.Cookie } : fresh;
    for (const Origin of ['http://evil.invalid', 'null']) denied(await request(app, route, { headers: { ...headers, Origin } }), 403);
    denied(await request(app, route, { headers: { ...headers, Host: 'localhost' } }), 403);
    denied(await request(app, route, { rawHeaders: ['Host', new URL(app.url).host, 'Cookie', old.Cookie, 'Content-Type', 'application/json'] }), 403);
    denied(await request(app, route, { method: 'GET', headers, body: undefined }), 405);
    denied(await request(app, route, { headers, body: '{' }), 400);
    denied(await request(app, route, { headers, body: '{"challenge":"extra"}' }), 400);
    denied(await request(app, route, { headers, body: '{"actor":"human"}' }), 403);
    denied(await request(app, route, { headers: { ...headers, 'Content-Type': 'text/plain' } }), 415);
    denied(await request(app, route, { headers, body: 'x'.repeat(4097) }), 413);
    denied(await request(app, route, { rawHeaders: ['Host', new URL(app.url).host, 'Origin', app.url, 'Content-Type', 'application/json', 'Cookie', old.Cookie, 'X-Trial-CSRF', fresh['X-Trial-CSRF'], 'X-Trial-CSRF', fresh['X-Trial-CSRF']] }), 400);
    denied(await request(app, route, { rawHeaders: ['Host', new URL(app.url).host, 'Origin', app.url, 'Origin', app.url, 'Content-Type', 'application/json', 'Cookie', old.Cookie] }), 400);
    denied(await request(app, route, { headers: { ...headers, Cookie: old.Cookie + '; ' + old.Cookie } }), 400);
    denied(await request(app, route, { headers: { ...headers, 'X-Actor': 'human' } }), 403);
    assert.equal((await read(app, old)).status, 200);
  }
  for (const csrf of [undefined, 'wrong', 'A'.repeat(43), old['X-Trial-CSRF']]) {
    const headers = { Cookie: old.Cookie, ...(csrf ? { 'X-Trial-CSRF': csrf } : {}) };
    denied(await request(app, completeRoute, { headers }), 403);
  }
  const other = await admit(app);
  denied(await request(app, completeRoute, { headers: { ...fresh, Cookie: other.Cookie } }), 403);
  for (const route of ['/api/tasks', '/api/tasks/none/approve', '/api/tasks/none/cancel', '/api/relay/message']) denied(await request(app, route, { headers: fresh }), 403);
  assert.deepEqual((await read(app, old)).json().tasks, []);
  assert.equal((await request(app, completeRoute, { headers: fresh })).status, 201, 'failed completions do not consume or mutate');
  assert.equal((await read(app, other)).status, 200, 'only matching session revoked');
});

test('logout while completion body arrives invalidates the challenge without replacement admission', async t => {
  const app = await fixture(t); const old = await admit(app); const fresh = await challenge(app, old);
  denied(await request(app, challengeRoute), 401);
  denied(await request(app, completeRoute, { headers: { 'X-Trial-CSRF': fresh['X-Trial-CSRF'] } }), 403);
  denied(await request(app, challengeRoute, { headers: old }), 403);
  const result = await new Promise((resolve, reject) => {
    const req = http.request(app.url + completeRoute, { method: 'POST', headers: { ...fresh, Origin: app.url, 'Content-Type': 'application/json', 'Content-Length': '2' } }, res => {
      let text = ''; res.on('data', value => { text += value; }); res.on('end', () => resolve({ status: res.statusCode, text, headers: res.headers }));
    });
    req.on('error', reject); req.write('{');
    setTimeout(async () => {
      try { assert.equal((await request(app, '/api/trial-session/logout', { headers: old })).status, 204); req.end('}'); }
      catch (error) { req.destroy(); reject(error); }
    }, 40);
  });
  denied(result, 403); denied(await read(app, old), 401);
});

test('recovery is bounded, single use, concurrent completion consumes once, replacement challenge invalidates previous', async t => {
  const app = await fixture(t); const old = await admit(app);
  const previous = await challenge(app, old); const fresh = await challenge(app, old);
  denied(await request(app, completeRoute, { headers: previous }), 403);
  const results = await Promise.all([request(app, completeRoute, { headers: fresh }), request(app, completeRoute, { headers: fresh })]);
  assert.deepEqual(results.map(res => res.status).sort(), [201, 403]);
  denied(results.find(res => res.status === 403), 403);
});

test('expired challenge and expiry during asynchronous completion are body-free and grant nothing', async t => {
  let clock = Date.now(); const app = await fixture(t, { sessionNow: () => clock });
  const old = await admit(app); const fresh = await challenge(app, old);
  clock += 30000; denied(await request(app, completeRoute, { headers: fresh }), 403);
  assert.equal((await read(app, old)).status, 200);
  const next = await challenge(app, old);
  const result = await new Promise((resolve, reject) => {
    const req = http.request(app.url + completeRoute, { method: 'POST', headers: { ...next, Origin: app.url, 'Content-Type': 'application/json', 'Content-Length': '2' } }, res => {
      let text = ''; res.on('data', value => { text += value; }); res.on('end', () => resolve({ status: res.statusCode, text, headers: res.headers }));
    });
    req.on('error', reject); req.write('{');
    setTimeout(() => { clock += 30000; req.end('}'); }, 40);
  });
  denied(result, 403); assert.equal((await read(app, old)).status, 200);
  clock += 300000; denied(await request(app, completeRoute, { headers: next }), 403);
});
