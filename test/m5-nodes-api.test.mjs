import test from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { writeFile } from 'node:fs/promises';
import { startApp, ROOT } from '../server.mjs';

import { controlledProbe, request, admit } from './m5-nodes-fixture.mjs';

const post = (app, proof, body = '{}') => request(app, '/api/node-probes/refresh', { method: 'POST', body,
  headers: { ...proof, Origin: app.url, 'Content-Type': 'application/json' } });
const wait = async predicate => { for (let n = 0; n < 100 && !predicate(); n++) await new Promise(r => setTimeout(r, 5)); assert.ok(predicate()); };
async function fixture(t, extra = {}) {
  const dataDir = `test/app03-m5-nodes-api-${randomUUID()}`, tx = controlledProbe();
  const app = await startApp({ dataDir, relayEnabled: false, nodeProbeTestOptions: tx.options, ...extra });
  t.after(() => app.close());
  return { app, tx, dataDir, proof: await admit(app) };
}

test('M5 actual HTTP boundary: unauthorized reads and arbitrary inputs cannot launch a probe', async t => {
  const { app, tx, proof } = await fixture(t);
  for (const route of ['/api/node-probes', '/api/node-probes/refresh']) {
    const res = await request(app, route);
    assert.equal(res.status, 401); assert.equal(res.text, ''); assert.equal(res.headers['cache-control'], 'no-store');
  }
  for (const res of [
    await request(app, '/api/node-probes', { headers: { Cookie: proof.Cookie } }),
    await request(app, '/api/node-probes', { headers: { ...proof, Origin: 'http://evil.test' } }),
    await request(app, '/api/node-probes', { headers: { ...proof, Host: 'evil.test' } }),
    await post(app, { Cookie: proof.Cookie }),
    await post(app, { ...proof, 'X-Trial-CSRF': 'a'.repeat(43) }),
  ]) { assert.ok([401, 403].includes(res.status)); assert.equal(res.text, ''); assert.equal(res.headers['cache-control'], 'no-store'); }
  for (const key of ['config', 'argv', 'path', 'destination', 'timeoutMs', 'refresh', 'nodes', 'modulePath']) {
    assert.equal((await post(app, proof, JSON.stringify({ [key]: 'attacker' }))).status, 400);
  }
  assert.equal((await post(app, proof, '[]')).status, 400);
  assert.equal((await request(app, '/api/node-probes/refresh', { headers: proof })).status, 405);
  assert.equal((await request(app, '/api/node-probes?destination=evil', { headers: proof })).status, 404);
  assert.equal(tx.calls.length, 0);
  const before = await request(app, '/api/node-probes', { headers: proof });
  assert.equal(before.status, 200); assert.equal(before.json().nodes[0].lastProbeAt, null);
  assert.equal((await request(app, '/api/node-probes', { method: 'HEAD', headers: proof })).text, '');
  assert.equal((await request(app, '/api/inference-observation', { headers: proof })).json().schemaVersion, 'mesh-inference-observation/v1');
  assert.equal(tx.calls.length, 0, 'old contract and cache reads never launch CLI');
});

test('M5 shared reader: coalescing, cached aging, offline and unavailable remain honest', async t => {
  const { app, tx, proof, dataDir } = await fixture(t);
  tx.hold(); const one = post(app, proof), two = post(app, proof);
  await wait(() => tx.calls.length === 1); tx.release();
  const responses = await Promise.all([one, two]);
  responses.forEach(r => { assert.equal(r.status, 200); assert.equal(r.headers['cache-control'], 'no-store'); });
  const ready = responses[0].json(); assert.deepEqual(ready, responses[1].json());
  assert.equal(ready.nodes[0].status, 'ready'); assert.equal(ready.nodes[1].status, 'ready');
  tx.advance(1000); tx.offline(); const lost = (await post(app, proof)).json();
  assert.equal(lost.nodes[1].status, 'stale'); assert.equal(lost.nodes[1].tailscaleOnline, false);
  assert.equal(lost.nodes[1].lastSuccessAt, ready.nodes[1].lastSuccessAt);
  tx.advance(29000); const stale = (await request(app, '/api/node-probes', { headers: proof })).json();
  assert.equal(stale.nodes[0].status, 'stale');
  tx.advance(30000); const offline = (await request(app, '/api/node-probes', { headers: proof })).json();
  assert.equal(offline.nodes[1].status, 'offline'); assert.equal(tx.calls.length, 2);
  tx.fail(); const unavailable = (await post(app, proof)).json();
  for (const n of unavailable.nodes) {
    assert.equal(n.status, 'offline'); assert.equal(n.observationAvailability, 'unavailable'); assert.equal(n.tailscaleOnline, null);
    assert.equal(n.lastSuccessAt, ready.nodes[0].lastSuccessAt); assert.equal(n.errors[0].code, 'cli_access_denied');
    assert.equal(n.packetReachability, 'unknown'); assert.equal(n.inferenceReadiness, 'unknown'); assert.equal(n.modelReadiness, 'unknown');
    assert.deepEqual(n.capabilities, { observation: true, control: false, load: false, inference: false, unload: false });
  }
  assert.ok(!JSON.stringify(unavailable).includes('PRIVATE_MARKER'));
  await writeFile(`${ROOT}/${dataDir}/controlled-api-proof.json`, JSON.stringify({ provenance: 'Controlled stream and clock, not native tailnet', ready, lost, stale, offline, unavailable, calls: tx.calls }, null, 2));
});

test('M5 delayed native composition rechecks expiry and revocation before replying', async t => {
  let now = 1000;
  const { app, tx, proof } = await fixture(t, { sessionNow: () => now, sessionTtlMs: 1000 });
  tx.hold(); const pending = post(app, proof); await wait(() => tx.calls.length === 1);
  now = 2000; tx.release(); const expired = await pending;
  assert.equal(expired.status, 401); assert.equal(expired.text, ''); assert.equal(expired.headers['cache-control'], 'no-store');
  const replacement = await admit(app); tx.hold(); const revoked = post(app, replacement);
  await wait(() => tx.calls.length === 2);
  assert.equal((await request(app, '/api/trial-session/logout', { method: 'POST', body: '{}',
    headers: { ...replacement, Origin: app.url, 'Content-Type': 'application/json' } })).status, 204);
  tx.release(); const denied = await revoked; assert.equal(denied.status, 401); assert.equal(denied.text, '');
});
