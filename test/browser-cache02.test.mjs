import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import * as policy from '../public/shell-cache-policy-browser-v2.mjs';
import * as original from '../public/shell-cache-policy.mjs';

// Node metadata/cache doubles replay parent-owned Chromium trace shapes.
// They do not establish browser CacheStorage or offline product acceptance.
const origin = 'http://127.0.0.1:12345';
const base = 'D:/tmp/fleet-consolidation-20260929/goals/MESH-PWA05-CACHE-BROWSER02-BASELINE/';
const sibling = 'D:/tmp/fleet-consolidation-20260929/build/mesh-pwa-cache-module-v1/';
const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const read = file => readFile(new URL('../' + file, import.meta.url));
const traced = { accept: '*/*', 'user-agent': 'Chromium fixture', 'sec-ch-ua': '"Chromium";v="fixture"', 'sec-ch-ua-mobile': '?0', 'sec-ch-ua-platform': '"Windows"' };
function request(path = '/app.js', headers = traced, mode = 'cors', method = 'GET') {
  const req = new Request(origin + path, { headers, method });
  // Node cannot construct mode=navigate; emulate browser-supplied metadata only.
  if (mode === 'navigate') Object.defineProperty(req, 'mode', { value: mode });
  return req;
}
function response(path = '/app.js', options = {}) {
  const res = new Response('public fixture', { status: options.status ?? 200, headers: { 'content-type': 'text/javascript', 'cache-control': 'public, max-age=0', ...options.headers } });
  for (const [key, value] of Object.entries({ type: 'basic', url: origin + path, redirected: false, ...options.metadata })) Object.defineProperty(res, key, { value });
  return res;
}
function storage(keys = [], cached = response()) {
  const calls = []; const cache = {
    keys: async () => keys,
    match: async (key, options) => { calls.push(['match', key, options]); return cached; },
    put: async (key, value) => { calls.push(['put', key, value]); }
  };
  return { calls, has: async name => { assert.equal(name, policy.CACHE_NAME); return true; }, open: async name => { assert.equal(name, policy.CACHE_NAME); return cache; } };
}

test('CACHE-BROWSER02: six actual traced request shapes now admitted; original reproduces denial', () => {
  for (const path of ['/', '/app.js', '/styles.css', '/manifest.webmanifest', '/icon.svg', '/shell-cache-policy.mjs']) {
    const req = request(path, path === '/' ? { ...traced, 'upgrade-insecure-requests': '1' } : traced, path === '/' ? 'navigate' : 'cors');
    assert.equal(original.getPublicEntry(req, origin), null);
    assert.equal(policy.getPublicEntry(req, origin)?.path, path);
  }
});

test('CACHE-BROWSER02: root remains navigation-only and exactly seven assets remain public', () => {
  assert.equal(policy.getPublicEntry(request('/'), origin), null);
  assert.equal(policy.getPublicEntry(request('/', traced, 'navigate'), origin)?.path, '/');
  assert.deepEqual(policy.PUBLIC_ASSETS, original.PUBLIC_ASSETS);
  assert.equal(policy.MAX_ENTRIES, 7); assert.equal(policy.POLICY_VERSION, original.POLICY_VERSION);
  assert.equal(policy.CACHE_NAME, original.CACHE_NAME);
  for (const path of Object.keys(policy.PUBLIC_ASSETS)) assert.equal(policy.getPublicEntry(request(path, traced, path === '/' ? 'navigate' : 'cors'), origin)?.path, path);
});

test('CACHE-BROWSER02: Origin admits exact owned loopback value and refuses cross-origin/null/variants', () => {
  assert.ok(policy.getPublicEntry(request('/app.js', { ...traced, Origin: origin }), origin));
  for (const value of ['http://example.test', 'null', origin + '/', 'http://localhost:12345', 'http://127.0.0.1:12346']) assert.equal(policy.getPublicEntry(request('/app.js', { ...traced, Origin: value }), origin), null);
  assert.equal(policy.getPublicEntry(new Request('http://example.test/app.js', { headers: { Origin: 'http://example.test' } }), 'http://example.test'), null);
});

test('CACHE-BROWSER02: authorization/cookie/custom proof and unmeasured sec names remain refused', () => {
  for (const name of ['Authorization', 'Cookie', 'X-Trial-CSRF', 'X-Custom-Proof', 'sec-ch-ua-full-version', 'sec-unknown']) {
    const req = request('/app.js', { ...traced, [name]: 'fixture' });
    assert.equal(policy.getPublicEntry(req, origin), null);
    assert.throws(() => policy.makePopulationRequest(req, origin), /outside/);
  }
});

test('CACHE-BROWSER02: task/session/API/query/cross-origin/nonGET/network-only paths denied', () => {
  for (const path of ['/tasks', '/session', '/api/tasks', '/api/trial-session/bootstrap', '/api/trial-session/logout', '/api/health', '/pwa-register.mjs', '/app.js?q=1', '/app.js#fragment', '/unknown']) assert.equal(policy.getPublicEntry(request(path), origin), null);
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']) assert.equal(policy.getPublicEntry(request('/app.js', traced, 'cors', method), origin), null);
  for (const url of ['http://example.test/app.js', 'http://127.0.0.1:12346/app.js', 'http://user:pass@127.0.0.1:12345/app.js']) assert.equal(policy.getPublicEntry(new Request(url.replace('user:pass@', '')), url.includes('user:pass@') ? url : origin), null);
});

test('CACHE-BROWSER02: canonical population omits every caller header/credential/referrer', () => {
  const req = new Request(origin + '/app.js', { credentials: 'include', referrer: origin + '/private', headers: { ...traced, Origin: origin, 'accept-language': 'en', 'cache-control': 'no-cache' } });
  const key = policy.makePopulationRequest(req, origin);
  assert.equal(key.url, origin + '/app.js'); assert.equal(key.method, 'GET');
  assert.equal(key.credentials, 'omit'); assert.equal(key.referrer, ''); assert.equal(key.referrerPolicy, 'no-referrer');
  assert.equal(key.mode, 'same-origin'); assert.equal(key.redirect, 'error'); assert.equal(key.cache, 'no-store');
  assert.deepEqual([...key.headers], [['accept', 'text/javascript, application/javascript']]); assert.equal(key.body, null);
});

test('CACHE-BROWSER02: status/type/URL/redirect/cookie/vary/location/MIME/cache response guards retained', () => {
  const url = origin + '/app.js';
  assert.ok(policy.isAdmissibleResponse(response(), url, origin));
  const bad = [{ status: 201 }, { metadata: { type: 'default' } }, { metadata: { type: 'opaque' } }, { metadata: { redirected: true } }, { metadata: { url: origin + '/styles.css' } }];
  for (const header of ['set-cookie', 'set-cookie2', 'vary', 'location']) bad.push({ headers: { [header]: 'fixture' } });
  for (const mime of ['text/html', 'application/json', '']) bad.push({ headers: { 'content-type': mime } });
  for (const control of ['', 'max-age=0', 'public, private', 'public, no-store', 'public, private=field', 'public, no-store=1', 'public, fixture="quoted"']) bad.push({ headers: { 'cache-control': control } });
  for (const options of bad) assert.equal(policy.isAdmissibleResponse(response('/app.js', options), url, origin), false);
  assert.equal(policy.isAdmissibleResponse(response(), url + '?q=1', origin), false);
});

test('CACHE-BROWSER02: admitted fetch uses sanitized key and bounded public put; rejected response never put', async () => {
  const cacheStorage = storage(); const res = response(); let key;
  assert.equal(await policy.handlePublicFetch(request('/app.js', { ...traced, Origin: origin }), { origin, cacheStorage, fetchImpl: async req => { key = req; return res; } }), res);
  assert.equal(key.credentials, 'omit'); assert.deepEqual([...key.headers.keys()], ['accept']);
  assert.equal(cacheStorage.calls.length, 1); assert.equal(cacheStorage.calls[0][0], 'put');
  const rejected = storage();
  await policy.handlePublicFetch(request(), { origin, cacheStorage: rejected, fetchImpl: async () => response('/app.js', { headers: { 'cache-control': 'private' } }) });
  assert.equal(rejected.calls.length, 0);
});

test('CACHE-BROWSER02: invalid/oversized/duplicate/private/credential keys fail closed without purge', async () => {
  const canonical = policy.makePopulationRequest(request(), origin);
  const badKeys = [Array(8).fill(canonical), [canonical, canonical], [new Request(origin + '/api/tasks', { credentials: 'omit' })], [new Request(origin + '/app.js')], [new Request(origin + '/app.js?q=1', { credentials: 'omit' })], [new Request(origin + '/app.js', { credentials: 'omit', headers: { Origin: origin } })], [new Request(origin + '/app.js', { credentials: 'omit', headers: { Authorization: 'fixture' } })]];
  for (const keys of badKeys) {
    const cacheStorage = storage(keys);
    await policy.handlePublicFetch(request(), { origin, cacheStorage, fetchImpl: async () => response() });
    assert.equal(cacheStorage.calls.length, 0);
    const failure = Error('fixture offline');
    await assert.rejects(policy.handlePublicFetch(request(), { origin, cacheStorage, fetchImpl: async () => { throw failure; } }), error => error === failure);
    assert.equal(cacheStorage.calls.length, 0);
  }
});

test('CACHE-BROWSER02: only network throw reads accepted cached response with strict match flags', async () => {
  const key = policy.makePopulationRequest(request(), origin); const cached = response();
  const cacheStorage = storage([key], cached); const failure = Error('fixture offline');
  assert.equal(await policy.handlePublicFetch(request(), { origin, cacheStorage, fetchImpl: async () => { throw failure; } }), cached);
  assert.deepEqual(cacheStorage.calls[0][2], { ignoreSearch: false, ignoreMethod: false, ignoreVary: false });
  const invalid = storage([key], response('/app.js', { headers: { vary: 'cookie' } }));
  await assert.rejects(policy.handlePublicFetch(request(), { origin, cacheStorage: invalid, fetchImpl: async () => { throw failure; } }), error => error === failure);
});

test('CACHE-BROWSER02: candidate exact admission-only derivation and original four/contract/worker preserved', async () => {
  const baseline = await read('public/shell-cache-policy.mjs');
  assert.equal(sha(baseline), '94ddb2f58d11154dc684419f92355e707de076e0a8e9cc4b10e18be71025c396');
  const expected = baseline.toString().replace("  'sec-fetch-dest'", "  'sec-ch-ua', 'sec-ch-ua-mobile', 'sec-ch-ua-platform', 'upgrade-insecure-requests',\n  'sec-fetch-dest'")
    .replace('function hasOnlySafeHeaders(headers) {\n  for (const [name] of headers) if (!SAFE_REQUEST_HEADERS.has(name.toLowerCase())) return false;', 'function hasOnlySafeHeaders(headers, origin) {\n  for (const [name, value] of headers) {\n    if (name.toLowerCase() === \'origin\' && ownedOrigin(origin) && value === origin) continue;\n    if (!SAFE_REQUEST_HEADERS.has(name.toLowerCase())) return false;\n  }')
    .replace('!hasOnlySafeHeaders(request.headers)', '!hasOnlySafeHeaders(request.headers, origin)');
  const candidate = await read('public/shell-cache-policy-browser-v2.mjs');
  assert.deepEqual(candidate, Buffer.from(expected)); assert.equal(sha(candidate), sha(Buffer.from(expected)));
  for (const file of ['sw.js', 'shell-cache-policy.mjs', 'manifest.webmanifest', 'icon.svg']) assert.deepEqual(await read('public/' + file), await readFile(sibling + 'public/' + file));
  assert.equal(sha(await read('public/sw.js')), '336e0949b4508df1a960dfc596baaade5cbfdf2a01fe4a504d7910c3d81aff7f');
  assert.deepEqual(JSON.parse(await readFile(sibling + 'CACHE04-CONTRACT.json', 'utf8')).publicPaths, Object.keys(policy.PUBLIC_ASSETS));
  assert.match((await read('public/sw.js')).toString(), /from '\/shell-cache-policy\.mjs'/);
});

test('CACHE-BROWSER02: exact same-URL candidate route and only two integration expectations changed', async () => {
  const old = "['/shell-cache-policy.mjs', ['public/shell-cache-policy.mjs', 'text/javascript']]";
  const next = "['/shell-cache-policy.mjs', ['public/shell-cache-policy-browser-v2.mjs', 'text/javascript']]";
  const server = await readFile(base + 'pwa-server.mjs'); const suite = await readFile(base + 'test/pwa05.test.mjs');
  assert.equal(sha(server), '184bf83dcd07f98969cb84678f27f7d2bb85edc159064294cd20f6d117ed042f');
  assert.equal(sha(suite), 'b0cd72255007b2cab7aeb0abbf3884b12b39bc6b44ae0593cbdb0d53be13f7e7');
  assert.deepEqual(await read('pwa-server.mjs'), Buffer.from(server.toString().replace(old, next)));
  assert.deepEqual(await read('test/pwa05.test.mjs'), Buffer.from(suite.toString().replace(old, next).replace("['/shell-cache-policy.mjs','shell-cache-policy.mjs','text/javascript']", "['/shell-cache-policy.mjs','shell-cache-policy-browser-v2.mjs','text/javascript']")));
});
