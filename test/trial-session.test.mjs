import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { createTrialSessionManager, createTrialHttpGuard, SESSION_COOKIE_NAME,
  TRIAL_ACTOR } from '../lib/trial-session.mjs';

const fakeId = 'A'.repeat(43);
test('recovery manager is capped at session capacity, rotates at capacity, expires and consumes once', () => {
  let at = 1000;
  const manager = createTrialSessionManager({ ttlMs: 300000, maxSessions: 1, now: () => at });
  const old = manager.createSession();
  let previous;
  for (let i = 0; i < 100; i++) {
    const fresh = manager.createRecoveryChallenge(old.sessionId);
    if (previous) assert.equal(manager.completeRecovery(old.sessionId, previous.challenge), null);
    previous = fresh;
    assert.equal(manager.size(), 1);
  }
  assert.equal(manager.createRecoveryChallenge(fakeId), null);
  const current = manager.completeRecovery(old.sessionId, previous.challenge);
  assert.ok(current); assert.equal(manager.size(), 1);
  assert.equal(manager.authorize(old.sessionId), null);
  assert.equal(manager.completeRecovery(old.sessionId, previous.challenge), null);
  const expiring = manager.createRecoveryChallenge(current.sessionId);
  at += 30000;
  assert.equal(manager.completeRecovery(current.sessionId, expiring.challenge), null);
  assert.ok(manager.authorize(current.sessionId));
  const revoked = manager.createRecoveryChallenge(current.sessionId);
  manager.revoke(current.sessionId);
  assert.equal(manager.completeRecovery(current.sessionId, revoked.challenge), null);
  assert.equal(manager.size(), 0);
});
async function fixture(t, settings = {}) {
  let clock = 1000;
  const manager = createTrialSessionManager({ ttlMs: 100, maxSessions: 4, now: () => clock, ...settings });
  let guard;
  // Let missing-Host regression requests reach the guard rather than Node's parser denial.
  const server = http.createServer({ maxHeaderSize: 16_384, requireHostHeader: false }, async (req, res) => {
    if (req.url.startsWith('/bootstrap')) return guard.bootstrap(req, res);
    if (req.url.startsWith('/logout')) return guard.logout(req, res);
    const context = await guard.authorize(req, res);
    if (context) {
      res.setHeader('Content-Type', 'application/json');
      res.end(JSON.stringify(context));
    }
  });
  server.requestTimeout = 5000;
  server.headersTimeout = 5000;
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  const port = server.address().port;
  guard = createTrialHttpGuard({ manager, port });
  t.after(async () => {
    server.closeAllConnections();
    await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  });
  function request({ path = '/private', method = 'GET', cookie, csrf, body,
    headers = {}, rawHeaders, originless = false } = {}) {
    const data = body === undefined ? (['GET', 'HEAD'].includes(method) ? undefined : '{}') :
      typeof body === 'string' ? body : JSON.stringify(body);
    const normal = { Host: `127.0.0.1:${port}`, ...(!originless ? { Origin: guard.trustedOrigin } : {}),
      ...(data !== undefined ? { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(data) } : {}),
      ...(cookie ? { Cookie: cookie } : {}), ...(csrf ? { 'X-Trial-CSRF': csrf } : {}), ...headers };
    return new Promise((resolve, reject) => {
      const req = http.request({ host: '127.0.0.1', port, path, method,
        headers: rawHeaders ?? normal, agent: false }, res => {
        let text = '';
        res.setEncoding('utf8');
        res.on('data', chunk => { text += chunk; });
        res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, text,
          json: text ? JSON.parse(text) : null }));
      });
      req.on('error', reject);
      req.setTimeout(4000, () => req.destroy(new Error('Owned test timeout')));
      req.end(data);
    });
  }
  async function bootstrap() {
    const result = await request({ path: '/bootstrap', method: 'POST' });
    assert.equal(result.status, 201);
    return { result, cookie: result.headers['set-cookie'][0].split(';')[0], csrf: result.json.csrfToken };
  }
  return { manager, request, bootstrap, port, origin: guard.trustedOrigin,
    tick: value => { clock = value; }, restart: () => {
      guard = createTrialHttpGuard({ manager: createTrialSessionManager({ ttlMs: 100, maxSessions: 4,
        now: () => clock }), port });
    } };
}
function denied(result, status, clearsCookie = false) {
  assert.equal(result.status, status);
  assert.equal(result.text, '');
  assert.equal(result.headers['cache-control'], 'no-store');
  if (clearsCookie) assert.deepEqual(result.headers['set-cookie'], [`${SESSION_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0`]);
  else assert.equal(result.headers['set-cookie'], undefined);
}

test('manager creates unpredictable fixed synthetic sessions and validates settings', () => {
  for (const settings of [undefined, null, {}, { ttlMs: '100', maxSessions: 1 },
    { ttlMs: 0, maxSessions: 1 }, { ttlMs: 86_400_001, maxSessions: 1 },
    { ttlMs: 1.5, maxSessions: 1 }, { ttlMs: NaN, maxSessions: 1 },
    { ttlMs: 10, maxSessions: 0 }, { ttlMs: 10, maxSessions: 10_001 },
    { ttlMs: 10, maxSessions: '1' }, { ttlMs: 10, maxSessions: 1, now: 5 },
    { ttlMs: 10, maxSessions: 1, role: 'admin' }, { ttlMs: 10, maxSessions: 1, now: () => -1 }]) {
    assert.throws(() => createTrialSessionManager(settings));
  }
  const manager = createTrialSessionManager({ ttlMs: 100, maxSessions: 100 });
  const ids = new Set(); const tokens = new Set();
  for (let i = 0; i < 100; i++) {
    const session = manager.createSession();
    assert.match(session.sessionId, /^[A-Za-z0-9_-]{43}$/);
    assert.match(session.csrfToken, /^[A-Za-z0-9_-]{43}$/);
    assert.notEqual(session.csrfToken, session.sessionId);
    assert.equal(session.actor, TRIAL_ACTOR);
    assert.ok(Object.isFrozen(session.actor.capabilities));
    ids.add(session.sessionId); tokens.add(session.csrfToken);
  }
  assert.equal(ids.size, 100); assert.equal(tokens.size, 100);
  assert.throws(() => manager.createSession({ role: 'admin' }));
  assert.throws(() => manager.authorize(fakeId, { mutation: 'false' }));
  assert.throws(() => createTrialHttpGuard({ manager, port: '1' }));
  assert.throws(() => createTrialHttpGuard({ manager: {}, port: 1000 }));
});

test('manager pressure, expiry boundary, revoke, invalid IDs and clock regression fail closed', () => {
  let at = 100;
  const manager = createTrialSessionManager({ ttlMs: 10, maxSessions: 1, now: () => at });
  const session = manager.createSession();
  assert.throws(() => manager.createSession(), { code: 'TRIAL_CAPACITY' });
  assert.equal(manager.authorize(session.sessionId, { mutation: true, csrfToken: fakeId }), null);
  assert.ok(manager.authorize(session.sessionId, { mutation: true, csrfToken: session.csrfToken }));
  for (const id of [null, 123, '', fakeId, `${session.sessionId}=`]) assert.equal(manager.authorize(id), null);
  at = 110;
  assert.equal(manager.authorize(session.sessionId), null);
  assert.equal(manager.sweepExpired(), 0);
  const next = manager.createSession();
  assert.equal(manager.revoke(next.sessionId), true);
  assert.equal(manager.revoke(next.sessionId), false);
  assert.equal(manager.authorize(next.sessionId), null);
  assert.equal(manager.size(), 0);
  at = 109;
  assert.throws(() => manager.createSession(), /Clock moved backwards/);
});

test('actual loopback bootstrap, authenticated read and mutation have fixed actor and no-store', async t => {
  const f = await fixture(t);
  const { result, cookie, csrf } = await f.bootstrap();
  assert.equal(result.json.admission, 'EXPLICIT_SYNTHETIC_DEMO');
  assert.deepEqual(result.json.actor, TRIAL_ACTOR);
  assert.equal(result.headers['cache-control'], 'no-store');
  const cookieHeader = result.headers['set-cookie'][0];
  assert.ok(cookieHeader.includes('; HttpOnly; SameSite=Strict;'));
  assert.ok(!cookieHeader.includes('Secure'));
  assert.equal(result.json.sessionId, undefined);
  for (const method of ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']) {
    const response = await f.request({ method, cookie, csrf, ...(method !== 'GET' ? { body: { action: 'demo' } } : {}) });
    assert.equal(response.status, 200);
    assert.deepEqual(response.json.actor, TRIAL_ACTOR);
    assert.equal(response.headers['cache-control'], 'no-store');
    assert.equal(response.json.sessionId, undefined);
  }
});

test('missing, fake, expired and revoked sessions cannot authorize or silently bootstrap', async t => {
  const f = await fixture(t);
  denied(await f.request(), 401);
  for (const path of ['/private', '/bootstrap']) {
    denied(await f.request({ path, method: path === '/bootstrap' ? 'POST' : 'GET',
      cookie: `${SESSION_COOKIE_NAME}=${fakeId}` }), 401, path === '/bootstrap');
  }
  const first = await f.bootstrap();
  f.tick(1100);
  denied(await f.request({ cookie: first.cookie }), 401);
  denied(await f.request({ path: '/bootstrap', method: 'POST', cookie: first.cookie }), 401, true);
  const second = await f.bootstrap();
  f.manager.revoke(second.cookie.split('=')[1]);
  denied(await f.request({ cookie: second.cookie }), 401);
  denied(await f.request({ path: '/bootstrap', method: 'POST', cookie: second.cookie }), 401, true);
});

test('actual boundary rejects untrusted, null, absent, malformed and duplicate Host/Origin', async t => {
  const f = await fixture(t);
  for (const headers of [{ Host: 'evil.test' }, { Host: `localhost:${f.port}` },
    { Host: `127.0.0.1:${f.port + 1}` }, { Origin: 'null' }, { Origin: 'https://evil.test' },
    { Origin: `${f.origin}/` }, { Origin: `${f.origin}, https://evil.test` }, { Origin: '' },
    { Origin: `http://127.0.0.1:${f.port}/@evil` }]) {
    denied(await f.request({ path: '/bootstrap', method: 'POST', headers }), 403);
  }
  const base = ['Host', `127.0.0.1:${f.port}`, 'Origin', f.origin,
    'Content-Type', 'application/json', 'Content-Length', '2'];
  denied(await f.request({ path: '/bootstrap', method: 'POST', rawHeaders: base.filter((_, i) => i !== 2 && i !== 3) }), 403);
  for (const [name, value] of [['Host', `127.0.0.1:${f.port}`], ['Origin', f.origin]]) {
    denied(await f.request({ path: '/bootstrap', method: 'POST', rawHeaders: [...base, name, value] }), 400);
  }
});

test('actual boundary enforces CSRF on every mutation and admitted bootstrap and logout', async t => {
  const f = await fixture(t); const { cookie, csrf } = await f.bootstrap();
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
    denied(await f.request({ method, cookie }), 403);
    denied(await f.request({ method, cookie, csrf: fakeId }), 403);
  }
  denied(await f.request({ path: '/bootstrap', method: 'POST', cookie }), 403);
  denied(await f.request({ path: '/bootstrap', method: 'POST', cookie, csrf }), 409);
  denied(await f.request({ path: '/logout', method: 'POST', cookie }), 403);
  const rawHeaders = ['Host', `127.0.0.1:${f.port}`, 'Origin', f.origin, 'Cookie', cookie,
    'X-Trial-CSRF', csrf, 'X-Trial-CSRF', csrf, 'Content-Type', 'application/json', 'Content-Length', '2'];
  denied(await f.request({ method: 'POST', rawHeaders }), 400);
});

test('actual boundary denies injected browser actor, roles, capabilities and credentials', async t => {
  const f = await fixture(t); const { cookie, csrf } = await f.bootstrap();
  for (const body of [{ role: 'admin' }, { capabilities: ['admin'] }, { actor: 'owner' },
    { nested: [{ Role: 'owner' }] }, { user_id: 'invented' }, { credentials: 'invented' }]) {
    denied(await f.request({ method: 'POST', cookie, csrf, body }), 403);
    denied(await f.request({ path: '/bootstrap', method: 'POST', body }), 403);
  }
  for (const headers of [{ 'X-Role': 'admin' }, { 'X-Capabilities': 'all' }, { Authorization: 'invented' }]) {
    denied(await f.request({ cookie, headers }), 403);
  }
  denied(await f.request({ path: '/private?role=admin', cookie }), 403);
  denied(await f.request({ path: '/bootstrap', method: 'POST', body: { arbitraryUrl: 'http://example.invalid' } }), 400);
});

test('actual boundary rejects malformed, duplicate, oversized cookie and headers', async t => {
  const f = await fixture(t); const { cookie } = await f.bootstrap();
  for (const value of [`${cookie}; ${cookie}`, `${SESSION_COOKIE_NAME}=bad`,
    `${SESSION_COOKIE_NAME}="${fakeId}"`, `${cookie}; broken`, `${cookie}; a=b; a=c`,
    `${cookie}; a=${'x'.repeat(2048)}`, `${cookie}; ${Array.from({ length: 32 }, (_, i) => `a${i}=b`).join('; ')}`]) {
    denied(await f.request({ cookie: value }), 400);
  }
  denied(await f.request({ rawHeaders: ['Host', `127.0.0.1:${f.port}`, 'Origin', f.origin,
    'Cookie', cookie, 'Cookie', cookie] }), 400);
  denied(await f.request({ cookie, headers: { 'X-Padding': 'x'.repeat(8200) } }), 400);
  const many = ['Host', `127.0.0.1:${f.port}`, 'Origin', f.origin, 'Cookie', cookie];
  for (let i = 0; i < 63; i++) many.push(`X-Header-${i}`, 'x');
  denied(await f.request({ rawHeaders: many }), 400);
});

test('actual boundary limits JSON, methods and body claims without response payload on failure', async t => {
  const f = await fixture(t); const { cookie, csrf } = await f.bootstrap();
  for (const [body, status] of [['{', 400], ['[]', 400], ['null', 400],
    [JSON.stringify({ padding: 'x'.repeat(4096) }), 413], [JSON.stringify({ constructor: 'invented' }), 403]]) {
    denied(await f.request({ method: 'POST', cookie, csrf, body }), status);
  }
  denied(await f.request({ method: 'POST', cookie, csrf, headers: { 'Content-Type': 'text/plain' } }), 415);
  denied(await f.request({ method: 'OPTIONS', cookie }), 405);
  denied(await f.request({ method: 'GET', cookie, body: '{}' }), 400);
  denied(await f.request({ path: '/bootstrap', method: 'GET' }), 405);
  denied(await f.request({ path: '/logout', method: 'GET', cookie }), 405);
  let deep = {}; for (let i = 0; i < 18; i++) deep = { next: deep };
  denied(await f.request({ method: 'POST', cookie, csrf, body: deep }), 400);
});

test('HTTP capacity rejects pressure, expiry frees space, logout and restart fail closed', async t => {
  const f = await fixture(t, { maxSessions: 1 });
  const first = await f.bootstrap();
  denied(await f.request({ path: '/bootstrap', method: 'POST' }), 503);
  assert.equal(f.manager.size(), 1);
  f.tick(1100);
  const second = await f.bootstrap();
  const logout = await f.request({ path: '/logout', method: 'POST', cookie: second.cookie, csrf: second.csrf });
  assert.equal(logout.status, 204); assert.equal(logout.text, '');
  assert.equal(logout.headers['cache-control'], 'no-store');
  assert.ok(logout.headers['set-cookie'][0].includes('Max-Age=0'));
  denied(await f.request({ cookie: second.cookie }), 401);
  denied(await f.request({ cookie: first.cookie }), 401);
  const third = await f.bootstrap();
  f.restart();
  denied(await f.request({ cookie: third.cookie }), 401);
  denied(await f.request({ path: '/bootstrap', method: 'POST', cookie: third.cookie }), 401, true);
});

test('session expiry while mutation body is arriving is rechecked at actual HTTP boundary', async t => {
  const f = await fixture(t); const { cookie, csrf } = await f.bootstrap();
  const result = await new Promise((resolve, reject) => {
    const req = http.request({ host: '127.0.0.1', port: f.port, method: 'POST', path: '/private', agent: false,
      headers: { Host: `127.0.0.1:${f.port}`, Origin: f.origin, Cookie: cookie,
        'X-Trial-CSRF': csrf, 'Content-Type': 'application/json', 'Content-Length': '2' } }, res => {
      let text = ''; res.on('data', chunk => { text += chunk; });
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, text }));
    });
    req.on('error', reject);
    req.write('{');
    setTimeout(() => { f.tick(1100); req.end('}'); }, 25);
  });
  denied(result, 401);
});

test('originless GET and HEAD admit current cookie and matching proof with optional same-origin metadata', async t => {
  const f = await fixture(t); const { cookie, csrf } = await f.bootstrap();
  for (const method of ['GET', 'HEAD']) {
    for (const headers of [{}, { 'Sec-Fetch-Site': 'same-origin' }]) {
      const result = await f.request({ method, cookie, csrf, originless: true, headers });
      assert.equal(result.status, 200);
      assert.equal(result.headers['cache-control'], 'no-store');
      assert.equal(result.headers.pragma, 'no-cache');
      assert.equal(result.headers['set-cookie'], undefined);
      if (method === 'GET') {
        assert.deepEqual(result.json.actor, TRIAL_ACTOR);
        assert.equal(result.json.body, null);
        assert.equal(result.json.expiresAt, 1100);
        assert.equal(result.json.sessionId, undefined);
      } else assert.equal(result.text, '');
    }
    // Exact-Origin reads retain their existing cookie-only admission policy.
    assert.equal((await f.request({ method, cookie })).status, 200);
  }
});

test('originless reads deny absent, wrong, malformed and duplicate proof even with same-origin metadata', async t => {
  const f = await fixture(t); const first = await f.bootstrap(); const other = await f.bootstrap();
  for (const method of ['GET', 'HEAD']) {
    for (const headers of [{}, { 'Sec-Fetch-Site': 'same-origin' }]) {
      for (const csrf of [undefined, fakeId, 'bad', other.csrf]) {
        denied(await f.request({ method, cookie: first.cookie, csrf, originless: true, headers }), 403);
      }
      denied(await f.request({ method, cookie: first.cookie, originless: true,
        headers: { ...headers, 'X-Trial-CSRF': '' } }), 403);
    }
    denied(await f.request({ method, rawHeaders: ['Host', `127.0.0.1:${f.port}`,
      'Cookie', first.cookie, 'X-Trial-CSRF', first.csrf, 'X-Trial-CSRF', first.csrf] }), 400);
  }
});

test('originless reads deny missing, fake, malformed, expired, revoked and restart-invalid sessions', async t => {
  const f = await fixture(t); const first = await f.bootstrap();
  for (const method of ['GET', 'HEAD']) {
    for (const cookie of [undefined, `unrelated=${fakeId}`, `${SESSION_COOKIE_NAME}=${fakeId}`]) {
      denied(await f.request({ method, cookie, csrf: first.csrf, originless: true }), 401);
    }
    for (const cookie of [`${SESSION_COOKIE_NAME}=bad`, `${first.cookie}; ${first.cookie}`, `${first.cookie}; broken`]) {
      denied(await f.request({ method, cookie, csrf: first.csrf, originless: true }), 400);
    }
  }
  f.tick(1100);
  for (const method of ['GET', 'HEAD']) {
    denied(await f.request({ method, cookie: first.cookie, csrf: first.csrf, originless: true }), 401);
  }
  const second = await f.bootstrap();
  f.manager.revoke(second.cookie.split('=')[1]);
  for (const method of ['GET', 'HEAD']) {
    denied(await f.request({ method, cookie: second.cookie, csrf: second.csrf, originless: true }), 401);
  }
  const third = await f.bootstrap(); f.restart();
  for (const method of ['GET', 'HEAD']) {
    denied(await f.request({ method, cookie: third.cookie, csrf: third.csrf, originless: true }), 401);
  }
});

test('present bad Origin and nonexact Host remain denied despite valid session proof', async t => {
  const f = await fixture(t); const { cookie, csrf } = await f.bootstrap();
  for (const method of ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE']) {
    for (const Origin of ['null', '', 'https://evil.test', `http://localhost:${f.port}`,
      `${f.origin}/`, `${f.origin}, https://evil.test`, 'malformed']) {
      denied(await f.request({ method, cookie, csrf, headers: { Origin } }), 403);
    }
    denied(await f.request({ method, rawHeaders: ['Host', `127.0.0.1:${f.port}`,
      'Origin', f.origin, 'Origin', f.origin, 'Cookie', cookie, 'X-Trial-CSRF', csrf,
      'Content-Type', 'application/json', 'Content-Length', ['GET', 'HEAD'].includes(method) ? '0' : '2'] }), 400);
  }
  for (const method of ['GET', 'HEAD']) {
    for (const Host of ['evil.test', `localhost:${f.port}`, `127.0.0.1:${f.port + 1}`]) {
      denied(await f.request({ method, cookie, csrf, originless: true, headers: { Host } }), 403);
    }
    denied(await f.request({ method, rawHeaders: ['Cookie', cookie, 'X-Trial-CSRF', csrf] }), 403);
    denied(await f.request({ method, rawHeaders: ['Host', `127.0.0.1:${f.port}`,
      'Host', `127.0.0.1:${f.port}`, 'Cookie', cookie, 'X-Trial-CSRF', csrf] }), 400);
  }
});

test('originless mutations, demo bootstrap and logout remain forbidden with valid proof', async t => {
  const f = await fixture(t); const { cookie, csrf } = await f.bootstrap();
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) {
    denied(await f.request({ method, cookie, csrf, originless: true,
      headers: { 'Sec-Fetch-Site': 'same-origin' } }), 403);
  }
  for (const path of ['/bootstrap', '/logout']) {
    denied(await f.request({ path, method: 'POST', cookie, csrf, originless: true }), 403);
  }
  denied(await f.request({ path: '/bootstrap', method: 'POST', originless: true }), 403);
  assert.equal(f.manager.size(), 1);
  assert.equal((await f.request({ cookie, csrf, originless: true })).status, 200);
});

test('originless reads reject invalid fetch metadata, claims and bodies without trusting metadata alone', async t => {
  const f = await fixture(t); const { cookie, csrf } = await f.bootstrap();
  for (const method of ['GET', 'HEAD']) {
    for (const site of ['cross-site', 'same-site', 'none', '', 'Same-Origin', 'malformed', 'same-origin, cross-site']) {
      denied(await f.request({ method, cookie, csrf, originless: true, headers: { 'Sec-Fetch-Site': site } }), 403);
    }
    denied(await f.request({ method, originless: true, headers: { 'Sec-Fetch-Site': 'same-origin' } }), 401);
    denied(await f.request({ method, rawHeaders: ['Host', `127.0.0.1:${f.port}`, 'Cookie', cookie,
      'X-Trial-CSRF', csrf, 'Sec-Fetch-Site', 'cross-site', 'Sec-Fetch-Site', 'same-origin'] }), 400);
    for (const headers of [{ 'X-Role': 'admin' }, { 'X-Capabilities': 'all' }, { Authorization: 'invented' }]) {
      denied(await f.request({ method, cookie, csrf, originless: true, headers }), 403);
    }
    denied(await f.request({ path: '/private?role=admin', method, cookie, csrf, originless: true }), 403);
    denied(await f.request({ method, cookie, csrf, originless: true, body: '{}' }), 400);
  }
});
