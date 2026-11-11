import test from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { readFile, readdir } from 'node:fs/promises';
import { createLocalInference, LOCAL_PROFILE, LOCAL_LIMITS } from '../lib/local-inference.mjs';
import { localFixture } from './local-inference-fixture.mjs';
import { startApp } from '../server.mjs';
import { request, admit } from './m5-nodes-fixture.mjs';

const admitted = () => true;
function setup() {
  const fixture = localFixture();
  const control = createLocalInference({ adapter: fixture.adapter, now: fixture.now });
  const propose = action => control.propose(action, {}, 'session', admitted);
  const approve = p => control.approve({ proposalId: p.proposal.id, confirm: true }, 'session', admitted);
  return { fixture, control, propose, approve, load: async () => approve(await propose('load')) };
}
const rejects = (operation, status) => assert.rejects(operation, e => e.status === status);

test('default native adapter is unavailable and cannot launch from environment or browser input', async () => {
  const control = createLocalInference();
  const status = await control.status();
  assert.equal(status.state, 'UNAVAILABLE'); assert.equal(status.nodeId, 'this-pc');
  assert.equal(status.controls.reason, 'NATIVE_QUALIFICATION_REQUIRED');
  assert.equal(status.runtime.status, 'UNKNOWN'); assert.equal(status.telemetry.gpu, 'UNAVAILABLE');
  await rejects(() => control.propose('load', {}, 'session', admitted), 409);
});

test('live defaults and missing native qualification expose only pending Nemotron selection with no control authority', async () => {
  const previous=process.env.MESH_NEMOTRON_CONTROL;
  try {
    for(const flag of [undefined,'1']){
      if(flag===undefined)delete process.env.MESH_NEMOTRON_CONTROL;else process.env.MESH_NEMOTRON_CONTROL=flag;
      const app=await startApp({dataDir:`test/app03-nemotron-pending-${randomUUID()}`,relayEnabled:false});
      try {
        const proof=await admit(app);
        const status=(await request(app,'/api/inference/status',{headers:proof})).json();
        assert.equal(status.profile.id,'nemotron-bolt-local');
        assert.equal(status.profile.model,'Nemotron 3.5 Bolt 74B A9B');
        assert.equal(status.runtimeId,'nemotron-llama-b11669');
        assert.equal(status.state,'UNAVAILABLE');assert.equal(status.source,'none');
        assert.equal(status.runtime.status,'UNKNOWN');assert.equal(status.observedAt,null);
        assert.equal(status.controls.reason,'NEMOTRON_QUALIFICATION_REQUIRED');
        for(const key of ['load','stop','unload','recover','chat'])assert.equal(status.controls[key],false);
        assert.equal('executable' in status.profile,false);assert.equal('executableSha256' in status.profile,false);
        for(const [route,body] of [['propose-load',{}],['propose-unload',{}],['propose-recover',{}],
          ['approve',{proposalId:randomUUID(),confirm:true}],['chat',{prompt:'must not run'}]]){
          const denied=await request(app,'/api/inference/'+route,{method:'POST',body:JSON.stringify(body),
            headers:{...proof,Origin:app.url,'Content-Type':'application/json'}});
          assert.equal(denied.status,409,route);
        }
        assert.equal((await request(app,'/api/inference/receipt/'+randomUUID(),{headers:proof})).status,404);
      } finally {await app.close();}
    }
  } finally {if(previous===undefined)delete process.env.MESH_NEMOTRON_CONTROL;else process.env.MESH_NEMOTRON_CONTROL=previous;}
});

test('proposal never executes; approval is explicit, fixed, session-bound, expiring and single-use', async () => {
  const { fixture, control, propose, approve } = setup();
  await rejects(() => control.approve({ proposalId: 'missing', confirm: true }, 'session', admitted), 409);
  for (const field of ['path', 'executable', 'modelPath', 'model', 'modelName', 'port', 'argv', 'env', 'nodeId', 'runtimeId'])
    await rejects(() => control.propose('load', { [field]: 'browser-chosen' }, 'session', admitted), 400);
  const p = await propose('load');
  assert.equal(p.proposal.state, 'PROPOSED'); assert.equal(fixture.calls.start.length, 0);
  await rejects(() => control.approve({ proposalId: p.proposal.id, confirm: false }, 'session', admitted), 400);
  await rejects(() => control.approve({ proposalId: p.proposal.id, confirm: true }, 'other', admitted), 409);
  await rejects(() => control.approve({ proposalId: p.proposal.id, confirm: true, argv: [] }, 'session', admitted), 400);
  const result = await approve(p);
  assert.equal(result.receipt.state, 'RUNNING'); assert.equal(result.receipt.readBackVerified, true);
  assert.deepEqual(fixture.calls.start, [LOCAL_PROFILE]); assert.equal(Object.isFrozen(fixture.calls.start[0]), true);
  await rejects(() => approve(p), 409); assert.equal(fixture.calls.start.length, 1);
  assert.deepEqual(control.receipt(result.receipt.id, 'session').receipt, result.receipt);
  assert.throws(() => control.receipt(result.receipt.id, 'other'), e => e.status === 404);
  const stopped = await approve(await propose('stop')); assert.equal(stopped.receipt.state, 'STOPPED');
  const expired = await propose('load'); fixture.advance(LOCAL_LIMITS.proposalMs);
  await rejects(() => approve(expired), 409);
});

test('wrong/recycled PID, executable, cwd, argv, listener, GPU and stale health fail closed', async t => {
  const changes = {
    wrongPID: v => ({ ...v, identity: { ...v.identity, pid: 44 } }),
    recycledPID: v => ({ ...v, identity: { ...v.identity, createdAt: '2000-01-01T00:00:00.000Z' } }),
    executable: v => ({ ...v, identity: { ...v.identity, executable: 'other.exe' } }),
    executableHash: v => ({ ...v, identity: { ...v.identity, executableSha256: '0'.repeat(64) } }),
    cwd: v => ({ ...v, identity: { ...v.identity, cwd: 'other' } }),
    argv: v => ({ ...v, identity: { ...v.identity, argvHash: 'b'.repeat(64) } }),
    listener: v => ({ ...v, listener: { pid: 44, host: '127.0.0.1' } }),
    publicBind: v => ({ ...v, listener: { pid: v.identity.pid, host: '0.0.0.0' } }),
    handle: v => ({ ...v, retainedHandle: false }),
    GPU: v => ({ ...v, gpuMapping: 'UNKNOWN' }),
    health: v => ({ ...v, health: { ...v.health, observedAt: v.observedAt - 5001 } }),
    observation: v => ({ ...v, observedAt: v.observedAt - 5001 }),
    model: v => ({ ...v, health: { ...v.health, profileId: 'other-model' } }),
  };
  for (const [name, change] of Object.entries(changes)) await t.test(name, async () => {
    const { fixture, control, propose, approve, load } = setup(); await load();
    const p = await propose('stop'); fixture.override(change);
    const s = await control.status(); assert.equal(s.state, 'UNCERTAIN');
    for (const key of ['load', 'stop', 'unload', 'chat']) assert.equal(s.controls[key], false);
    await rejects(() => approve(p), 409); await rejects(() => control.chat({ prompt: 'private' }, admitted), 409);
    assert.equal(fixture.calls.stop.length, 0); assert.equal(fixture.calls.chat.length, 0);
  });
});

test('Stop and Unload require approval and read back original exit; a live or missing process is not exit proof', async () => {
  for (const action of ['stop', 'unload']) {
    const { fixture, control, propose, approve, load } = setup(); await load();
    const p = await propose(action); assert.equal(fixture.calls.stop.length, 0);
    const result = await approve(p); assert.equal(result.receipt.state, 'STOPPED');
    assert.equal(result.receipt.readBackVerified, true); assert.deepEqual(fixture.calls.stop[0], fixture.identity);
    assert.equal((await control.status()).state, 'STOPPED');
  }
  for (const failure of ['stillRunning', 'missingExitProof']) {
    const { fixture, control, propose, approve, load } = setup(); await load();
    if (failure === 'stillRunning') fixture.stopExits = false;
    else fixture.override(v => ({ ...v, exitVerified: false }));
    const result = await approve(await propose('unload'));
    assert.equal(result.receipt.state, 'UNCERTAIN'); assert.equal(result.receipt.readBackVerified, false);
  }
});

test('concurrent controls, stale proposal revisions, revoked admission and uncertain start cannot relaunch', async () => {
  const { fixture, control, propose, approve, load } = setup();
  const p = await propose('load');
  await rejects(() => control.approve({ proposalId: p.proposal.id, confirm: true }, 'session', () => false), 401);
  let release; fixture.holdStart = new Promise(r => { release = r; });
  const work = approve(p); await new Promise(r => setImmediate(r));
  await rejects(() => propose('load'), 409); await rejects(() => approve(p), 409);
  assert.equal((await control.status()).controls.load, false);
  release(); await work;
  const stop = await propose('stop'); fixture.override(v => ({ ...v, retainedHandle: false }));
  await control.status(); fixture.override(null); await control.status();
  await rejects(() => approve(stop), 409);
  const other = setup(); other.fixture.adapter.start = async () => { throw new Error('private diagnostics'); };
  // Constructor holds the adapter object, so a failed start becomes UNKNOWN custody.
  const failed = await other.load(); assert.equal(failed.receipt.state, 'UNCERTAIN');
  assert.equal((await other.control.status()).controls.load, false);
  assert.equal(JSON.stringify(failed).includes('private diagnostics'), false);
});

test('chat is RUNNING-only, bounded, abortable and redacts errors; no history contract', async () => {
  const { fixture, control, load } = setup();
  await rejects(() => control.chat({ prompt: 'secret' }, admitted), 409);
  await load();
  for (const body of [{ prompt: '' }, { prompt: 'x'.repeat(3001) }, { prompt: 'ok', model: 'other' }])
    await rejects(() => control.chat(body, admitted), 400);
  const result = await control.chat({ prompt: 'PRIVATE_PROMPT' }, admitted);
  assert.equal(result.response, 'Fixture reply'); assert.deepEqual(fixture.calls.chat, [{ maxTokens: 512, stream: true }]);
  assert.equal(JSON.stringify(await control.status()).includes('PRIVATE_PROMPT'), false);
  fixture.chatChunks = ['x'.repeat(LOCAL_LIMITS.outputBytes + 1)];
  await rejects(() => control.chat({ prompt: 'secret' }, admitted), 503);
  assert.equal((await control.status()).state, 'RUNNING'); // Explicit fresh proof may recover.
  const controller = new AbortController(); controller.abort();
  await rejects(() => control.chat({ prompt: 'secret' }, admitted, controller.signal), 503);
});

test('HTTP guard, strict inputs, receipts, no persistence and fresh admission are enforced', async t => {
  const fixture = localFixture(), dataDir = `test/app03-local-inference-${randomUUID()}`;
  const app = await startApp({ dataDir, relayEnabled: false, localInferenceTestOptions: { adapter: fixture.adapter, now: fixture.now } });
  t.after(() => app.close());
  const proof = await admit(app);
  const post = (route, body = {}, headers = {}) => request(app, '/api/inference/' + route, { method: 'POST', body: JSON.stringify(body),
    headers: { ...proof, Origin: app.url, 'Content-Type': 'application/json', ...headers } });
  for (const route of ['status', 'receipt/00000000-0000-0000-0000-000000000000', 'propose-load', 'approve', 'chat']) {
    assert.equal((await request(app, '/api/inference/' + route)).status, 401);
    assert.equal((await post(route, {}, { 'X-Trial-CSRF': '' })).status, 403);
    assert.equal((await post(route, {}, { Origin: 'http://evil.test' })).status, 403);
    assert.equal((await post(route, {}, { Host: 'evil.test' })).status, 403);
  }
  assert.equal((await post('chat', { prompt: 'x'.repeat(4200) })).status, 413);
  for (const key of ['executable', 'modelPath', 'port', 'argv', 'environment', 'modelName', 'nodeId'])
    assert.equal((await post('propose-load', { [key]: 'hostile' })).status, 400);
  assert.equal((await post('approve', { proposalId: randomUUID(), confirm: true })).status, 409);
  const p = (await post('propose-load')).json(); assert.equal(fixture.calls.start.length, 0);
  const r = await post('approve', { proposalId: p.proposal.id, confirm: true }); assert.equal(r.status, 200);
  const receipt = await request(app, '/api/inference/receipt/' + r.json().receipt.id, { headers: proof });
  assert.equal(receipt.json().receipt.readBackVerified, true); assert.equal(receipt.headers['cache-control'], 'no-store');
  fixture.chatChunks = ['PRIVATE_RESPONSE_MARKER'];
  const chat = await post('chat', { prompt: 'PRIVATE_PROMPT_MARKER' }); assert.equal(chat.status, 200);
  assert.equal(chat.json().response, 'PRIVATE_RESPONSE_MARKER');
  const otherProof = await admit(app);
  assert.equal((await request(app, '/api/inference/receipt/' + r.json().receipt.id, { headers: otherProof })).status, 404);
  assert.equal((await request(app, '/api/inference/history', { headers: otherProof })).status, 405);
  const status = await request(app, '/api/inference/status', { headers: otherProof });
  assert.equal(status.status, 200); assert.equal(status.headers['cache-control'], 'no-store');
  assert.equal(/PRIVATE_(PROMPT|RESPONSE)_MARKER/.test(status.text), false);
  assert.equal((await request(app, '/api/inference/status', { method: 'HEAD', headers: proof })).text, '');
  for (const file of await readdir(dataDir)) {
    const bytes = await readFile(`${dataDir}/${file}`);
    assert.equal(/PRIVATE_(PROMPT|RESPONSE)_MARKER/.test(bytes.toString()), false);
  }
  assert.equal((await request(app, '/api/tasks', { headers: proof })).json().tasks.length, 0);
});

test('hung startup times out to UNCERTAIN and never retries or mistakes later custody-clear for exit', async () => {
  const { fixture, control, load, propose } = setup();
  fixture.holdStart = new Promise(() => {});
  const result = await load();
  assert.equal(result.receipt.state, 'UNCERTAIN'); assert.equal(result.receipt.readBackVerified, false);
  assert.equal((await control.status()).state, 'UNCERTAIN');
  await rejects(() => propose('load'), 409); assert.equal(fixture.calls.start.length, 1);
});

test('hung chat reaches its bounded deadline, returns UNKNOWN and never retries', async () => {
  const { fixture, control, load } = setup(); await load();
  let calls = 0;
  fixture.adapter.chat = async function* () { calls++; await new Promise(() => {}); };
  const started = Date.now();
  await assert.rejects(() => control.chat({ prompt: 'PRIVATE_TIMEOUT_MARKER' }, admitted), e =>
    e.status === 503 && /UNKNOWN/.test(e.message) && !e.message.includes('PRIVATE_TIMEOUT_MARKER'));
  assert.ok(Date.now() - started >= LOCAL_LIMITS.chatMs - 100); assert.equal(calls, 1);
});

test('standalone never constructs or calls even an injected inference fixture', async t => {
  const previous = process.env.MESH_STANDALONE; process.env.MESH_STANDALONE = '1';
  t.after(() => { if (previous === undefined) delete process.env.MESH_STANDALONE; else process.env.MESH_STANDALONE = previous; });
  const fixture = localFixture(); fixture.adapter.observe = () => { throw new Error('must not run'); };
  const app = await startApp({ dataDir: `test/app03-local-inference-standalone-${randomUUID()}`, relayEnabled: false,
    localInferenceTestOptions: { adapter: fixture.adapter, now: fixture.now } });
  t.after(() => app.close()); const proof = await admit(app);
  const s = (await request(app, '/api/inference/status', { headers: proof })).json();
  assert.equal(s.state, 'UNAVAILABLE'); assert.equal(s.controls.reason, 'STANDALONE_NOT_CONFIGURED');
  assert.equal(fixture.calls.start.length, 0);
});
