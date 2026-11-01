// PURE only: synthetic retained records and in-memory pipes; no native helper.
import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { PassThrough, Writable } from 'node:stream';
import { runPureFixtureShutdown } from '../tools/closure-owner-fixture-native.mjs';
import { createCustodyPipe } from './m6-standalone-fixture.mjs';

function rig() {
  const calls = []; let time = 0;
  const identity = (pid, parent, custodyClass = 'workload') => ({ pid, parentPid: parent,
    creationTime100ns: String(134357975684908571n + BigInt(pid)),
    parentCreationTime100ns: String(134357975684908571n + BigInt(parent)),
    executable: custodyClass === 'infrastructure' ? 'conhost.exe' : 'node.exe',
    commandLine: `owned ${pid}`, argv: ['owned', String(pid)], custodyClass, exitSignaled: false });
  const apps = ['mesh','standalone'].map((mode, n) => {
    const root = identity(100 + n * 10, 1), server = identity(root.pid + 1, root.pid);
    const console = identity(root.pid + 2, server.pid, 'infrastructure');
    return { mode, child: { pid: root.pid }, root, server,
      identities: new Map([root, server, console].map(i => [`${i.pid}:${i.creationTime100ns}`, i])),
      closed: Promise.resolve({ code: 0 }), cleanupVerified: false };
  });
  const records = () => apps.flatMap(a => [...a.identities.values()]).map(i => ({ ...i }));
  const fake = { kind: 'pure-mock', runtime: false,
    budget() { return 60000; }, now() { time += 1000; return time; }, async pause() {},
    bounded: p => p,
    async collect(app) { calls.push(`collect:${app.mode}`); return fake.snapshot(); },
    async snapshot() { return records(); },
    async save(app) { calls.push(`save:${app.mode}`); },
    async call(action, i) { calls.push(`${action}:${i.pid}`);
      const held = apps.flatMap(a => [...a.identities.values()]).find(v => v.pid === i.pid);
      held.exitSignaled = true; held.exitCode = 1;
    }, async finish() { calls.push('observer-finish'); } };
  return { apps, fake, calls, records, run: options => runPureFixtureShutdown({ apps, fake, ...options }) };
}

test('normal close cleans two owned modes, workload before console, observer last', async () => {
  const r = rig(); const result = await r.run();
  assert.equal(result.evidence, 'PURE_MOCK_NOT_RUNTIME_EVIDENCE');
  assert.deepEqual(r.calls.filter(c => c.startsWith('kill:')),
    ['kill:101','kill:100','kill:102','kill:111','kill:110','kill:112']);
  assert.ok(r.apps.every(a => a.cleanupVerified));
  assert.equal(r.calls.at(-1), 'observer-finish');
});

test('interruption still starts with exact server then cleans both modes', async () => {
  const r = rig(); await r.run({ interruption: true });
  assert.equal(r.calls.find(c => c.startsWith('kill:')), 'kill:101');
  assert.ok(r.apps.every(a => a.cleanupVerified));
});

test('failure-shaped observer loss records errors and attempts remaining owned mode', async () => {
  const r = rig(); let lost = false; const original = r.fake.call;
  r.fake.call = async (action, i) => { await original(action, i); lost = true; };
  r.fake.snapshot = async () => { if (lost) throw Error('CUSTODY_PIPE_UNVERIFIED:stdin:EPIPE'); return r.records(); };
  await assert.rejects(r.run(), error => {
    assert.equal(error.message, 'NATIVE_CLEANUP_UNVERIFIED');
    assert.equal(error.errors.length, 2);
    assert.match(error.errors[0].cause.errors[0].message, /mesh:100:\d+:.*EPIPE/);
    assert.match(error.errors[1].cause.message, /EPIPE/); return true;
  });
  assert.ok(r.calls.includes('collect:standalone'));
  assert.ok(r.apps.every(a => !a.cleanupVerified && a.failure));
  assert.ok(!r.calls.includes('observer-finish'));
  assert.deepEqual(r.calls.filter(c => c.startsWith('kill:')), ['kill:101']);
});

test('missing original record cannot become cleanup from absence; second mode still closes', async () => {
  const r = rig(); r.fake.snapshot = async () => r.records().filter(i => i.pid !== 101);
  await assert.rejects(r.run(), error => {
    assert.match(error.errors[0].cause.errors[0].message, /ORIGINAL_HANDLE_MISSING/); return true;
  });
  assert.equal(r.apps[0].cleanupVerified, false); assert.equal(r.apps[1].cleanupVerified, true);
  assert.ok(!r.calls.includes('kill:101')); assert.ok(!r.calls.includes('observer-finish'));
});

test('changed exact native identity refuses control and does not abandon other mode', async () => {
  const r = rig(); r.fake.snapshot = async () => r.records().map(i => i.pid === 101 ? { ...i, argv: ['reused'] } : i);
  await assert.rejects(r.run(), error => {
    assert.match(error.errors[0].cause.errors[0].message, /NATIVE_IDENTITY_CHANGED/); return true;
  });
  assert.ok(!r.calls.includes('kill:101')); assert.equal(r.apps[1].cleanupVerified, true);
});

test('missing integer exit code remains unverified after bounded wait', async () => {
  const r = rig(); const original = r.fake.call;
  r.fake.call = async (...args) => { await original(...args);
    if (args[1].pid === 101) delete r.apps[0].server.exitCode; };
  await assert.rejects(r.run(), error => {
    assert.equal(error.errors[0].cause.message, 'ORIGINAL_EXITS_UNVERIFIED'); return true;
  });
  assert.equal(r.apps[0].cleanupVerified, false); assert.equal(r.apps[1].cleanupVerified, true);
});

test('helper finish failure propagates even when owned exits are verified', async () => {
  const r = rig(); r.fake.finish = async () => { throw Error('helper exit 1'); };
  await assert.rejects(r.run(), /helper exit 1/);
  assert.ok(r.apps.every(a => a.cleanupVerified));
});

test('shutdown seam refuses native selection', async () => {
  await assert.rejects(runPureFixtureShutdown({ fake: { kind: 'native', runtime: true } }), /PURE_SEAM_ONLY/);
});

function pipeRig(write) {
  const child = new EventEmitter(); child.stdout = new PassThrough();
  child.stdin = new Writable({ write });
  const pipe = createCustodyPipe(child, { timeoutMs: 100 });
  return { child, pipe };
}

test('asynchronous EPIPE callback/event rejects request and stays handled between requests', async () => {
  const r = pipeRig((_chunk, _encoding, callback) => queueMicrotask(() => callback(Object.assign(Error('broken'), { code: 'EPIPE' }))));
  await assert.rejects(r.pipe.call('snapshot'), /CUSTODY_PIPE_UNVERIFIED.*EPIPE/);
  await new Promise(resolve => setImmediate(resolve));
  await assert.rejects(r.pipe.call('snapshot'), /EPIPE/);
  assert.ok(r.pipe.diagnostics.some(d => d.code === 'EPIPE'));
  for (let n = 0; n < 100; n++) r.child.stdin.emit('error', Error('x'.repeat(10000)));
  assert.equal(r.pipe.diagnostics.length, 32);
  assert.ok(r.pipe.diagnostics.every(d => d.message.length <= 4096));
});

test('premature stdin close, helper exit and receipt EOF each fail closed', async () => {
  for (const event of ['stdin','helper','eof']) {
    const r = pipeRig((_chunk, _encoding, callback) => callback());
    const request = r.pipe.call('snapshot');
    await Promise.resolve();
    if (event === 'stdin') r.child.stdin.emit('close');
    if (event === 'helper') r.child.emit('close', 1, null);
    if (event === 'eof') r.child.stdout.end();
    await assert.rejects(request, /CUSTODY_PIPE_UNVERIFIED/);
    assert.ok(r.pipe.diagnostics.length > 0);
  }
});

test('pipe serializes requests and finish receipt precedes helper EOF/exit', async () => {
  const actions = []; let r;
  r = pipeRig((chunk, _encoding, callback) => {
    const { action } = JSON.parse(chunk.toString()); actions.push(action);
    queueMicrotask(() => { r.child.stdout.write(JSON.stringify({ event: action, identities: [] }) + '\n'); callback(); });
  });
  const values = await Promise.all([r.pipe.call('snapshot'), r.pipe.call('snapshot'), r.pipe.call('finish')]);
  assert.deepEqual(actions, ['snapshot','snapshot','finish']);
  assert.equal(values.at(-1).event, 'finish'); r.pipe.end(); r.child.emit('close', 0, null);
  assert.deepEqual(await r.pipe.closed, [0, null]); assert.deepEqual(r.pipe.diagnostics, []);
});

test('missing receipt has bounded rejection', async () => {
  const r = pipeRig((_chunk, _encoding, callback) => callback());
  await assert.rejects(r.pipe.call('snapshot'), /Native custody deadline/);
  await assert.rejects(r.pipe.call('snapshot'), /Native custody deadline/);
  assert.equal(r.pipe.diagnostics[0].source, 'deadline');
});

test('actual in-memory pipe error during two-mode close leaves both unverified and attempts standalone', async () => {
  const r = rig(); let killed = false, p;
  p = pipeRig((chunk, _encoding, callback) => {
    const command = JSON.parse(chunk.toString());
    if (killed) { queueMicrotask(() => callback(Object.assign(Error('observer disappeared'), { code: 'EPIPE' }))); return; }
    if (command.action === 'kill') killed = true;
    queueMicrotask(() => { p.child.stdout.write(JSON.stringify({ event: command.action, identities: r.records() }) + '\n'); callback(); });
  });
  r.fake.snapshot = async () => (await p.pipe.call('snapshot')).identities;
  r.fake.call = async (action, i) => { r.calls.push(`${action}:${i.pid}`); await p.pipe.call(action, i); };
  await assert.rejects(r.run(), /NATIVE_CLEANUP_UNVERIFIED/);
  await new Promise(resolve => setImmediate(resolve));
  assert.ok(r.calls.includes('collect:standalone'));
  assert.ok(r.apps.every(a => !a.cleanupVerified));
  assert.match(r.apps[0].cleanupErrors[0], /EPIPE/);
  assert.ok(p.pipe.diagnostics.some(d => d.code === 'EPIPE'));
  assert.ok(!r.calls.includes('observer-finish'));
});

test('wrong action receipt poisons channel before any later control write', async () => {
  let p, writes = 0;
  p = pipeRig((_chunk, _encoding, callback) => {
    writes++; queueMicrotask(() => { p.child.stdout.write('{"event":"wrong"}\n'); callback(); });
  });
  await assert.rejects(p.pipe.call('snapshot'), /CUSTODY_PIPE_UNVERIFIED:receipt-action/);
  await assert.rejects(p.pipe.call('kill'), /CUSTODY_PIPE_UNVERIFIED:receipt-action/);
  assert.equal(writes, 1);
});
