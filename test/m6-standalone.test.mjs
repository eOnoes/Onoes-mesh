import test from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { startApp } from '../server.mjs';
import { request, admit } from './m5-nodes-fixture.mjs';

test('M6 process flag forces absent services despite Relay and trusted observation hooks', async t => {
  const prior = process.env.MESH_STANDALONE;
  process.env.MESH_STANDALONE = '1';
  t.after(() => { if (prior === undefined) delete process.env.MESH_STANDALONE; else process.env.MESH_STANDALONE = prior; });
  let observations = 0;
  const forbidden = () => { observations++; throw new Error('standalone must not observe'); };
  const app = await startApp({ dataDir: `test/app03-m6-standalone-api-${randomUUID()}`, relayEnabled: true,
    inferenceTestReader: forbidden, nodeProbeTestOptions: { spawnImpl: forbidden } });
  t.after(() => app.close());
  const proof = await admit(app);
  for (const route of ['/api/health', '/api/service-connections', '/api/inference-observation', '/api/node-probes', '/api/relay']) {
    assert.equal((await request(app, route)).status, 401);
    const response = await request(app, route, { headers: proof });
    assert.equal(response.status, 200); assert.equal(response.headers['cache-control'], 'no-store');
    const value = response.json();
    if (route === '/api/health') assert.equal(value.mode, 'standalone');
    if (route === '/api/service-connections') for (const service of value.services) {
      assert.equal(service.status, 'not_configured'); assert.equal(service.source, 'none');
    }
    if (route === '/api/inference-observation') { assert.equal(value.status, 'not_configured'); assert.deepEqual(value.nodes, []); }
    if (route === '/api/node-probes') { assert.equal(value.status, 'not_configured'); assert.equal(value.source, 'none'); assert.deepEqual(value.nodes, []); }
    if (route === '/api/relay') assert.equal(value.status, 'not_configured');
  }
  const post = body => request(app, '/api/node-probes/refresh', { method: 'POST', body: JSON.stringify(body),
    headers: { ...proof, Origin: app.url, 'Content-Type': 'application/json' } });
  assert.equal((await post({})).json().status, 'not_configured');
  for (const field of ['standalone','mode','relayEnabled','config','argv','modulePath']) assert.equal((await post({ [field]: false })).status, 400);
  assert.equal((await request(app, '/api/health?standalone=0', { headers: proof })).status, 404);
  assert.equal((await request(app, '/api/node-probes/refresh', { method: 'POST', body: '{}',
    headers: { Cookie: proof.Cookie, Origin: app.url, 'Content-Type': 'application/json' } })).status, 403);
  assert.equal((await request(app, '/api/node-probes', { headers: { ...proof, Origin: 'http://evil.test' } })).status, 403);
  assert.equal((await request(app, '/api/node-probes', { method: 'HEAD', headers: proof })).text, '');
  assert.equal(observations, 0);
});

test('M6 flag off preserves the existing fixed node reader and inference seam', async t => {
  const prior = process.env.MESH_STANDALONE;
  process.env.MESH_STANDALONE = '0';
  t.after(() => { if (prior === undefined) delete process.env.MESH_STANDALONE; else process.env.MESH_STANDALONE = prior; });
  let observations = 0;
  const app = await startApp({ dataDir: `test/app03-m6-standalone-off-${randomUUID()}`, relayEnabled: false,
    inferenceTestReader: ({ nowIso }) => { observations++; return { schemaVersion: 'mesh-inference-observation/v1', status: 'disabled', observedAt: nowIso, nodes: [], errors: [] }; } });
  t.after(() => app.close()); const proof = await admit(app);
  assert.equal(app.mode, 'mesh');
  assert.equal((await request(app, '/api/node-probes', { headers: proof })).json().nodes.length, 2);
  assert.equal((await request(app, '/api/inference-observation', { headers: proof })).json().status, 'disabled');
  assert.equal(observations, 1);
});
