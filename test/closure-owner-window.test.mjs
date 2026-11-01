import test from 'node:test';
import assert from 'node:assert/strict';
import { runPureOwnerWindow, validateWindowAdmission, ADMISSION_FILE, MAX_WINDOW_MS } from '../tools/closure-owner-window.mjs';
import { createFixtureController, sha256, WORKTREE, BASELINE, CANONICAL_BASELINE, ROOTS, PORTS,
  SOURCE_PATHS, RUNTIMES, DEPENDENCY_PATHS } from '../tools/closure-owner-fixture.mjs';

const NOW = Date.parse('2026-10-06T21:00:00Z'), DRIVER = 'd'.repeat(64);
function approved(ms = MAX_WINDOW_MS) {
  const issuedAt = new Date(NOW).toISOString(), deadline = new Date(NOW + ms).toISOString();
  return { schema: 'closure-owner-window-runtime/v1', state: 'APPROVED', manager: 'f46e2ca656b9',
    job: 'closure-owner-window-driver', purpose: 'NEW_INTERACTIVE_OWNER_WINDOW', worktree: WORKTREE,
    baseline: BASELINE, canonicalBaseline: CANONICAL_BASELINE, issuedAt, deadline, driverSha256: DRIVER,
    fixtureAdmission: { schema: 'closure-owner-fixture-runtime/v1', state: 'APPROVED', manager: 'f46e2ca656b9',
      job: 'closure-disposable-owner-fixture-verify', worktree: WORKTREE, baseline: BASELINE,
      canonicalBaseline: CANONICAL_BASELINE, issuedAt, deadline,
      limits: { starts: 4, restarts: 2, interruptions: 2, cleanupMs: 60000 }, roots: { ...ROOTS },
      ports: { ...PORTS }, host: '127.0.0.1', modes: ['mesh','standalone'], commands: ['node-version','m3-slow'],
      sourcePins: Object.fromEntries(SOURCE_PATHS.map(p => [p, 'a'.repeat(64)])),
      runtimePins: Object.fromEntries(Object.values(RUNTIMES).map(p => [p, 'b'.repeat(64)])),
      dependencyPins: Object.fromEntries(DEPENDENCY_PATHS.map(p => [p, 'c'.repeat(64)])),
      custody: { helper: 'test/m6-standalone-fixture.mjs', entry: 'custody', observer: 'test/test_owned_cancel.py:Observer',
        retention: 'harness-before-launch-descendants-before-control', stop: 'immediate-pid-create-exe-argv-revalidation',
        exits: 'original-retained-handles', listeners: 'owned-loopback-only', manager: 'one-process-monotonic' },
      boundaries: { commandApproval: 'explicit-existing-ui-api-only', relay: 'existing-confined-mesh-only',
        standaloneOptionalServices: 'absent', inference: 'no-ui-no-refresh', mind: false, nativeTailscale: false,
        externalOrigin: false, protectedPorts: [4317,8446], protectedPids: [2612068,3671748],
        protectedStore: 'test/app03-manager-m1-disposable', cleanup: 'stop-owned-only-retain-stores' } } };
}
const flush = async () => { for (let i = 0; i < 100; i++) await Promise.resolve(); };
function rig(a = approved(), extra = {}) {
  const events = [], calls = []; let wall = NOW, mono = 0, handler, timer, closed = 0, detached = 0;
  const clock = { wall: () => wall, monotonic: () => mono,
    setTimeout(fn, ms) { timer = { fn, ms }; return timer; }, clearTimeout() { timer = null; } };
  const mockEffects = { kind: 'pure-mock', runtime: false,
    async retainManager() { calls.push('retain'); }, async prepareExclusive() { calls.push('prepare'); },
    async launchRetained(spec, generation) {
      calls.push(['launch', spec.dataDir, generation]);
      return { handle: {}, generation, pid: 900000 + generation, creationTime100ns: String(generation),
        executable: RUNTIMES.node, argv: [RUNTIMES.node, 'test/m1-serve.mjs'], retainedBeforeControl: true, spec };
    },
    async listeners(i) { return [{ host: '127.0.0.1', port: Number(i.spec.env.MESH_PREVIEW_PORT), pid: i.pid, generation: i.generation }]; },
    async revalidate(i) { return { ...i, live: true }; }, async stopRetained() { calls.push('stop-retained'); },
    async originalExit(i) { return { handle: i.handle, generation: i.generation, signaled: true, exitCode: 0 }; } };
  const bytes = JSON.stringify(a);
  const options = { admissionBytes: bytes, expectedSha256: sha256(bytes), driverSha256: DRIVER, clock,
    input: { subscribe(h) { handler = h; return () => { detached++; }; } }, publish(e) { events.push(e); },
    fake: { kind: 'pure-mock', runtime: false, createController(g) {
      const c = createFixtureController({ admissionBytes: g.fixtureBytes, expectedSha256: g.fixtureHash, clock,
        inspection: { async pins() {}, async fresh() {} }, mockEffects });
      return { ...c, async close() { closed++; calls.push('close'); return c.close(); } };
    } }, ...extra };
  return { events, calls, options, start: () => runPureOwnerWindow(options),
    get handler() { return handler; }, get closed() { return closed; }, get detached() { return detached; },
    get timer() { return timer; }, time(w, m) { wall = w; mono = m; },
    expire() { wall = NOW + MAX_WINDOW_MS; mono = MAX_WINDOW_MS; timer.fn(); } };
}

test('imported entrypoint has no running fixture and exact fixed admission location', () => {
  assert.equal(ADMISSION_FILE, WORKTREE + '/.runner/owner-window-runtime/RUNTIME-ADMISSION.json');
  assert.equal(MAX_WINDOW_MS, 120000);
  assert.equal(BASELINE, CANONICAL_BASELINE);
});
for (const [name, mutate, pattern] of [
  ['preparation', a => { a.state = 'PREPARED'; }, /SCOPE/],
  ['other manager', a => { a.manager = 'other'; }, /SCOPE/],
  ['replay purpose', a => { a.purpose = 'REPLAY'; }, /SCOPE/],
  ['caller path', a => { a.worktree = 'D:\\Dev\\Onoes-Mesh'; }, /SCOPE/],
  ['wrong baseline', a => { a.baseline = '0'.repeat(40); }, /SCOPE/],
  ['wrong canonical baseline', a => { a.fixtureAdmission.canonicalBaseline = '0'.repeat(40); }, /ADMISSION_OWNER/],
  ['driver pin', a => { a.driverSha256 = 'a'.repeat(64); }, /DRIVER_PIN/],
  ['over 120 seconds', a => { a.deadline = new Date(NOW + 120001).toISOString(); }, /DEADLINE/],
  ['expired', a => { a.deadline = a.issuedAt; }, /DEADLINE/],
  ['injected environment', a => { a.env = {}; }, /SCHEMA/],
  ['protected root', a => { a.fixtureAdmission.roots.mesh = 'test/app03-manager-m1-disposable'; }, /STORE_SCOPE/],
  ['missing source pin', a => { delete a.fixtureAdmission.sourcePins['server.mjs']; }, /SOURCE_CATALOG/],
  ['deadline mismatch', a => { a.fixtureAdmission.deadline = new Date(NOW + 119999).toISOString(); }, /FIXTURE_BUDGET/],
  ['smaller runtime budget', a => { a.fixtureAdmission.limits.starts = 2; }, /FIXTURE_BUDGET/],
]) test(`${name} has zero controller effects`, async () => {
  const a = approved(); mutate(a); const r = rig(a);
  await assert.rejects(r.start(), pattern); assert.deepEqual(r.calls, []); assert.equal(r.handler, undefined);
});
test('missing or wrong externally held hash has zero effects', async () => {
  for (const expectedSha256 of [undefined, '0'.repeat(64)]) {
    const r = rig(approved(), { expectedSha256 }); await assert.rejects(r.start(), /WINDOW_ADMISSION/);
    assert.deepEqual(r.calls, []);
  }
});
test('pure fake cannot identify itself as native', () => {
  assert.throws(() => runPureOwnerWindow({ fake: { kind: 'native', runtime: true } }), /PURE_SEAM_ONLY/);
});
test('starts exactly once each, READY truthful, one restart each, counters never reset', async () => {
  const r = rig(), done = r.start(); await flush();
  const ready = r.events.find(e => e.type === 'READY'); assert.ok(ready);
  assert.equal(ready.evidence, 'PURE_MOCK_NOT_RUNTIME_EVIDENCE'); assert.equal(ready.physical, 'NOT_OBSERVED');
  assert.deepEqual(ready.urls, { mesh: 'http://127.0.0.1:44181', standalone: 'http://127.0.0.1:44182' });
  for (const command of ['restart mesh','restart standalone','restart mesh','restart standalone']) {
    r.handler.line(command); await flush();
  }
  assert.equal(r.calls.filter(c => Array.isArray(c)).length, 4);
  assert.equal(r.events.filter(e => e.type === 'DENIED').length, 2);
  r.handler.line('stop'); const s = await done;
  assert.equal(s.starts, 4); assert.equal(s.restarts, 2); assert.equal(s.interruptions, 2);
  assert.equal(s.modes.mesh.generation, 2); assert.equal(s.modes.standalone.generation, 2);
  assert.equal(r.closed, 1); assert.equal(r.detached, 1); assert.equal(r.timer, null);
});
test('malformed exact commands have zero controller effect', async () => {
  const r = rig(), done = r.start(); await flush(); const count = r.calls.length;
  for (const command of [' restart mesh','restart mesh ','RESTART mesh','restart relay','stop now','approve','start','']) r.handler.line(command);
  await flush(); assert.equal(r.calls.length, count);
  assert.equal(r.events.filter(e => e.type === 'DENIED').length, 8);
  r.handler.line('stop'); await done;
});
for (const reason of ['EOF','SIGINT','SIGTERM','input-error','deadline']) test(`${reason} closes cleanly`, async () => {
  const r = rig(), done = r.start(); await flush();
  if (reason === 'EOF') r.handler.eof();
  else if (reason === 'input-error') r.handler.error(Error('input failed'));
  else if (reason === 'deadline') r.expire();
  else r.handler.signal(reason);
  if (reason === 'input-error') await assert.rejects(done, /input failed/); else await done;
  assert.equal(r.closed, 1); assert.equal(r.detached, 1);
  assert.equal(r.events.at(-1).type, reason === 'input-error' ? 'FAILED' : 'STOPPED');
});
test('earlier admission deadline and wall rollback cannot refill monotonic window', async () => {
  const r = rig(approved(1000)), done = r.start(); await flush(); assert.equal(r.timer.ms, 1000);
  r.time(NOW - 10000, 1000); r.timer.fn(); await done;
  assert.equal(r.events.at(-1).reason, 'deadline'); assert.equal(r.closed, 1);
});
test('concurrent commands serialize on held generation; terminal discards queued controls', async () => {
  const r = rig(), done = r.start(); await flush();
  r.handler.line('restart mesh'); r.handler.line('restart mesh'); r.handler.line('restart standalone'); await flush();
  assert.equal(r.events.filter(e => e.reason === 'RESTART_ALREADY_CONSUMED').length, 1);
  r.handler.line('restart standalone'); r.handler.line('stop'); r.handler.line('restart mesh'); await done;
  assert.equal(r.calls.filter(c => Array.isArray(c)).length, 4);
});
for (const operation of ['validate','launch','restart','close']) test(`${operation} error closes once and reports FAILED`, async () => {
  const r = rig(); const original = r.options.fake.createController;
  r.options.fake.createController = g => {
    const c = original(g); return { ...c, async [operation](...args) {
      if (operation === 'close') await c.close();
      throw Error(operation + '-failure');
    } };
  };
  const done = r.start();
  // Attach rejection handling immediately, including startup failures.
  const rejected = assert.rejects(done, new RegExp(operation + '-failure'));
  await flush();
  if (operation === 'restart') r.handler.line('restart mesh');
  if (operation === 'close') r.handler.line('stop');
  await rejected; assert.equal(r.closed, 1); assert.equal(r.events.at(-1).type, 'FAILED');
});
test('EOF during startup waits for held launch then closes without starting standalone', async () => {
  const r = rig(); const original = r.options.fake.createController; let release;
  const barrier = new Promise(resolve => { release = resolve; });
  r.options.fake.createController = g => { const c = original(g); return { ...c,
    async launch(mode) { await barrier; return c.launch(mode); } }; };
  const done = r.start(); await flush(); r.handler.eof(); release(); await done;
  assert.equal(r.calls.filter(c => Array.isArray(c)).length, 1); assert.equal(r.closed, 1);
  assert.equal(r.events.some(e => e.type === 'READY'), false);
});
test('gate freezes its own fixture bytes independently of later caller mutation', () => {
  const a = approved(), bytes = Buffer.from(JSON.stringify(a)), hash = sha256(bytes);
  const gate = validateWindowAdmission(bytes, hash, DRIVER, NOW); bytes.fill(0);
  assert.equal(JSON.parse(gate.fixtureBytes).worktree, WORKTREE);
});
test('publisher failure still closes owned controller and detaches', async () => {
  const r = rig(approved(), { publish() { throw Error('publish-failure'); } });
  await assert.rejects(r.start(), /publish-failure/);
  assert.equal(r.closed, 1); assert.equal(r.detached, 1);
});
test('input subscribe failure closes controller without launch', async () => {
  const r = rig(approved(), { input: { subscribe() { throw Error('subscribe-failure'); } } });
  await assert.rejects(r.start(), /subscribe-failure/);
  assert.equal(r.closed, 1); assert.equal(r.calls.filter(c => Array.isArray(c)).length, 0);
});
