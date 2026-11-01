// Self-contained pure gate; mock effects and native descriptors never start services.
import test from 'node:test';
import path from 'node:path';
import assert from 'node:assert/strict';
import { createFixtureController, validateAdmission, launchSpec, sha256, SOURCE_PATHS,
  WORKTREE, ROOTS, PORTS, RUNTIMES, BASELINE, CANONICAL_BASELINE, DEPENDENCY_PATHS,
  DEPENDENCY_CATALOG_SHA256 } from '../tools/closure-owner-fixture.mjs';
import { createNativeEffects, validateNativeSpec, validateNativeIdentity,
  sameNativeDirectory, validateHarnessRetention } from '../tools/closure-owner-fixture-native.mjs';

// Synthetic pin bytes and catalog names are self-contained in a clean checkout.
const intake = { scope: 'CONCRETE_NATIVE_FIXTURE_ADAPTER_SOURCE_ONLY', runtimeEffectsAdmitted: false };
const NOW = Date.parse('2026-10-06T21:00:00.000Z');
function approved() {
  return { schema: 'closure-owner-fixture-runtime/v1', state: 'APPROVED', manager: 'f46e2ca656b9',
    job: 'closure-disposable-owner-fixture-verify', worktree: WORKTREE,
    baseline: BASELINE, canonicalBaseline: CANONICAL_BASELINE,
    issuedAt: new Date(NOW).toISOString(), deadline: new Date(NOW + 900000).toISOString(),
    limits: { starts: 4, restarts: 2, interruptions: 2, cleanupMs: 60000 },
    roots: { ...ROOTS }, ports: { ...PORTS }, host: '127.0.0.1', modes: ['mesh','standalone'],
    commands: ['node-version','m3-slow'],
    sourcePins: Object.fromEntries(SOURCE_PATHS.map(p => [p, 'a'.repeat(64)])),
    runtimePins: Object.fromEntries(Object.values(RUNTIMES).map(p => [p, 'b'.repeat(64)])),
    dependencyPins: Object.fromEntries(DEPENDENCY_PATHS.map(p => [p, 'c'.repeat(64)])),
    custody: { helper: 'test/m6-standalone-fixture.mjs', entry: 'custody',
      observer: 'test/test_owned_cancel.py:Observer', retention: 'harness-before-launch-descendants-before-control',
      stop: 'immediate-pid-create-exe-argv-revalidation', exits: 'original-retained-handles',
      listeners: 'owned-loopback-only', manager: 'one-process-monotonic' },
    boundaries: { commandApproval: 'explicit-existing-ui-api-only', relay: 'existing-confined-mesh-only',
      standaloneOptionalServices: 'absent', inference: 'no-ui-no-refresh', mind: false, nativeTailscale: false,
      externalOrigin: false, protectedPorts: [4317,8446], protectedPids: [2612068,3671748],
      protectedStore: 'test/app03-manager-m1-disposable', cleanup: 'stop-owned-only-retain-stores' },
  };
}
function rig(a = approved(), options = {}) {
  const events = []; let wall = NOW, mono = 0, fresh = true, drift = null, changed = false, badExit = false;
  let listenerHost = '127.0.0.1';
  const inspection = {
    async pins() { events.push('read:pins'); if (drift) throw Error(drift); },
    async fresh() { events.push('read:fresh'); if (!fresh) throw Error('STORE_EXISTS'); },
  };
  const mockEffects = { kind: 'pure-mock', runtime: false,
    async retainManager() { events.push('effect:retain-manager'); },
    async prepareExclusive() { events.push('effect:prepare'); fresh = false; },
    async launchRetained(spec, generation) {
      events.push(['effect:launch', spec]);
      return { handle: {}, generation, pid: 900000 + generation,
        creationTime100ns: String(generation), executable: RUNTIMES.node,
        argv: [RUNTIMES.node, 'test/m1-serve.mjs'], retainedBeforeControl: true, spec };
    },
    async listeners(i) { events.push('read:listeners');
      return [{ host: listenerHost, port: Number(i.spec.env.MESH_PREVIEW_PORT), pid: i.pid, generation: i.generation }]; },
    async revalidate(i) { events.push('read:revalidate'); return { ...i, live: true,
      creationTime100ns: changed ? 'wrong' : i.creationTime100ns }; },
    async stopRetained() { events.push('effect:stop-retained'); },
    async originalExit(i) { events.push('read:original-exit'); return { handle: i.handle,
      generation: badExit ? i.generation + 1 : i.generation, signaled: true, exitCode: 1 }; },
  };
  const bytes = JSON.stringify(a);
  const controller = createFixtureController({ admissionBytes: bytes, expectedSha256: sha256(bytes), inspection,
    clock: { wall: () => wall, monotonic: () => mono }, mockEffects, ...options });
  return { controller, events, effects: () => events.filter(e => (Array.isArray(e) ? e[0] : e).startsWith('effect:')),
    time(w, m) { wall = w; mono = m; }, setFresh(v) { fresh = v; }, setDrift(v) { drift = v; },
    changeIdentity() { changed = true; }, changeExit() { badExit = true; },
    changeListener() { listenerHost = '0.0.0.0'; } };
}

test('missing and preparation admissions are never executable', async () => {
  const r = rig();
  const missing = rig(approved(), { admissionBytes: undefined, expectedSha256: undefined });
  await assert.rejects(missing.controller.launch('mesh'), /ADMISSION_MISSING/);
  assert.deepEqual(missing.effects(), []);
  const bytes = JSON.stringify(intake);
  assert.throws(() => validateAdmission(bytes, sha256(bytes), NOW), /ADMISSION_SCHEMA/);
  assert.equal(r.controller.status().modes.mesh.state, 'queued');
});
test('tampered bytes and missing expected pin fail before effects', async () => {
  for (const options of [{ expectedSha256: '0'.repeat(64) }, { expectedSha256: undefined }]) {
    const r = rig(approved(), options);
    await assert.rejects(r.controller.launch('mesh'), /ADMISSION_(HASH_MISMATCH|MISSING)/);
    assert.deepEqual(r.effects(), []);
  }
});
const denialCases = [
  ['unapproved', a => { a.state = 'PREPARED'; }, /ADMISSION_NOT_APPROVED/],
  ['expired', a => { a.deadline = new Date(NOW).toISOString(); }, /ADMISSION_EXPIRED/],
  ['outside worktree', a => { a.worktree = 'D:\\Dev\\Onoes-Mesh'; }, /ADMISSION_OWNER/],
  ['old source baseline', a => {
    a.baseline = '907d8efe5aab18d547076a8acfc023aa09b13ae0';
    assert.notEqual(a.baseline, BASELINE);
  }, /ADMISSION_OWNER/],
  ['canonical drift hidden', a => {
    a.canonicalBaseline = 'd8e4af7e16a46141a59f46a10102cc1e94b78d31';
    assert.notEqual(a.canonicalBaseline, CANONICAL_BASELINE);
  }, /ADMISSION_OWNER/],
  ['protected store', a => { a.roots.mesh = 'test/app03-manager-m1-disposable'; }, /STORE_SCOPE/],
  ['outside store', a => { a.roots.mesh = '../owner'; }, /STORE_SCOPE/],
  ['wrong GUID store', a => { a.roots.mesh += '-other'; }, /STORE_SCOPE/],
  ['wrong host', a => { a.host = '0.0.0.0'; }, /PORT_SCOPE/],
  ['protected preview', a => { a.ports.mesh = 4317; }, /PORT_SCOPE/],
  ['wrong port', a => { a.ports.standalone = 44183; }, /PORT_SCOPE/],
  ['wrong mode', a => { a.modes = ['mesh']; }, /MODE_SCOPE/],
  ['extra whitelist command', a => { a.commands.push('git-status'); }, /COMMAND_SCOPE/],
  ['implicit command approval', a => { a.boundaries.commandApproval = 'automatic'; }, /EFFECT_SCOPE/],
  ['caller environment', a => { a.env = { NODE_OPTIONS: '--import=evil' }; }, /ADMISSION_SCHEMA/],
  ['missing source pin', a => { delete a.sourcePins['lib/relay-link.mjs']; }, /SOURCE_CATALOG/],
  ['missing runtime pin', a => { delete a.runtimePins[RUNTIMES.node]; }, /RUNTIME_CATALOG/],
  ['missing native adapter runtime pin', a => { delete a.runtimePins[RUNTIMES.adapter]; }, /RUNTIME_CATALOG/],
  ['missing helper runtime pin', a => { delete a.runtimePins[RUNTIMES.helper]; }, /RUNTIME_CATALOG/],
  ['unbounded starts', a => { a.limits.starts = 5; }, /START_LIMIT/],
  ['unbounded restarts', a => { a.limits.restarts = 3; }, /RESTART_LIMIT/],
  ['unbounded interruptions', a => { a.limits.interruptions = 3; }, /INTERRUPTION_LIMIT/],
  ['unbounded cleanup', a => { a.limits.cleanupMs = 60001; }, /CLEANUP_LIMIT/],
  ['missing dependency pin', a => { delete a.dependencyPins[Object.keys(a.dependencyPins)[0]]; }, /DEPENDENCY_CATALOG/],
  ['outside dependency', a => { a.dependencyPins['../../owner'] = 'a'.repeat(64); }, /DEPENDENCY_CATALOG/],
];
for (const [name, mutate, error] of denialCases) test(`${name}: fail before effects`, async () => {
  const a = approved(); mutate(a); const r = rig(a);
  await assert.rejects(r.controller.launch('mesh'), error); assert.deepEqual(r.effects(), []);
});
for (const drift of ['SOURCE_DRIFT:server.mjs','DEPENDENCY_DRIFT:typing_extensions.py','RUNTIME_DRIFT:node.exe'])
  test(`${drift}: fail before effects`, async () => {
    const r = rig(); r.setDrift(drift);
    await assert.rejects(r.controller.launch('mesh'), { message: drift }); assert.deepEqual(r.effects(), []);
  });
test('existing first-launch root denied before retain/mkdir/import/spawn', async () => {
  const r = rig(); r.setFresh(false); await assert.rejects(r.controller.launch('mesh'), /STORE_EXISTS/);
  assert.deepEqual(r.effects(), []);
});
test('native adapter refuses preparation or missing bytes before any native effect', async () => {
  const bytes = JSON.stringify(intake);
  const e = createNativeEffects({ admissionBytes: bytes, expectedSha256: sha256(bytes),
    guard: () => assert.fail('guard must not run'), remaining: () => 60000 });
  await assert.rejects(e.retainManager(), /ADMISSION_SCHEMA/);
  await assert.rejects(createNativeEffects().retainManager(), /ADMISSION_MISSING/);
});
test('fixed npm start/environment; standalone optional services absent; no approval method', async () => {
  const r = rig(); const mesh = launchSpec('mesh'), standalone = launchSpec('standalone');
  assert.deepEqual(mesh.argv, [RUNTIMES.npm,'start']); assert.equal(mesh.startScript, 'node test/m1-serve.mjs');
  assert.equal(standalone.env.MESH_STANDALONE, '1'); assert.equal(standalone.env.MESH_RELAY, '0');
  for (const key of ['NODE_OPTIONS','PYTHONPATH','MESH_PORT','MESH_REGISTRY_PATH','TOKEN']) assert.equal(key in mesh.env, false);
  await r.controller.launch('mesh'); await r.controller.launch('standalone');
  assert.deepEqual(Object.keys(r.controller).sort(), ['close','launch','restart','status','stop','validate']);
  assert.equal(r.controller.status().modes.mesh.physical, 'NOT_OBSERVED');
  assert.equal(r.effects().some(e => String(e).includes('approve')), false);
});
test('duplicate launch and wrong-generation stop have zero new effects', async () => {
  const r = rig(); await r.controller.launch('mesh'); const count = r.effects().length;
  await assert.rejects(r.controller.launch('mesh'), /DUPLICATE_LAUNCH/);
  await assert.rejects(r.controller.stop('mesh', 2), /WRONG_GENERATION/); assert.equal(r.effects().length, count);
});
test('same held store/preview URL across bounded restart; no new fresh-root adoption', async () => {
  const a = approved(); a.limits.restarts = 1; const r = rig(a);
  await r.controller.launch('mesh'); await r.controller.restart('mesh', 1);
  const launches = r.effects().filter(e => Array.isArray(e)); assert.equal(launches.length, 2);
  assert.deepEqual(launches[0][1], launches[1][1]); assert.equal(r.controller.status().modes.mesh.generation, 2);
  assert.equal(r.events.filter(e => e === 'read:fresh').length, 1);
  const count = r.effects().length; await assert.rejects(r.controller.restart('mesh', 2), /START_RESTART_CAP/);
  assert.equal(r.effects().length, count);
});
test('no restart/adoption before held launch', async () => {
  const r = rig(); await assert.rejects(r.controller.restart('mesh', 0), /RESTART_REQUIRES_HELD_FIXTURE/);
  assert.deepEqual(r.effects(), []);
});
test('restart source drift denies before stop', async () => {
  const r = rig(); await r.controller.launch('mesh'); const count = r.effects().length;
  r.setDrift('SOURCE_DRIFT:server.mjs'); await assert.rejects(r.controller.restart('mesh', 1), /SOURCE_DRIFT/);
  assert.equal(r.effects().length, count);
});
test('deadline held monotonically despite wall rollback; cleanup grace only', async () => {
  const r = rig(); await r.controller.launch('mesh'); const count = r.effects().length;
  r.time(NOW + 1, 900001);
  await assert.rejects(r.controller.restart('mesh', 1), /DEADLINE/); assert.equal(r.effects().length, count);
  await r.controller.stop('mesh', 1); assert.equal(r.controller.status().modes.mesh.state, 'stopped');
});
test('finite cleanup deadline and interruption cap', async () => {
  const a = approved(); a.limits.interruptions = 0; const r = rig(a);
  await r.controller.launch('mesh'); const count = r.effects().length;
  await assert.rejects(r.controller.restart('mesh', 1), /INTERRUPTION_CAP/); assert.equal(r.effects().length, count);
  r.time(NOW + 960001, 960001); await assert.rejects(r.controller.stop('mesh', 1), /CLEANUP_DEADLINE/);
  assert.equal(r.effects().length, count);
});
test('immediate identity mismatch prevents retained-handle stop', async () => {
  const r = rig(); await r.controller.launch('mesh'); const count = r.effects().length; r.changeIdentity();
  await assert.rejects(r.controller.stop('mesh', 1), /IDENTITY_CHANGED/); assert.equal(r.effects().length, count);
});
test('wrong original exit generation never marks stopped', async () => {
  const r = rig(); await r.controller.launch('mesh'); r.changeExit();
  await assert.rejects(r.controller.stop('mesh', 1), /ORIGINAL_EXIT_UNVERIFIED/);
  assert.notEqual(r.controller.status().modes.mesh.state, 'stopped');
});
test('unowned listener never becomes runtime-verified or physical acceptance', async () => {
  const r = rig(); r.changeListener(); await assert.rejects(r.controller.launch('mesh'), /LISTENER_OWNERSHIP/);
  assert.equal(r.controller.status().modes.mesh.state, 'launched');
  assert.equal(r.controller.status().modes.mesh.runtimeVerified, false);
  await r.controller.stop('mesh', 1);
});

test('complete inherited dependency catalog includes preserved cache paths', () => {
  assert.equal(DEPENDENCY_PATHS.length, 1612);
  assert.equal(new Set(DEPENDENCY_PATHS).size, 1612);
  assert.ok(DEPENDENCY_PATHS.some(p => p.includes('__pycache__')));
  assert.equal(sha256([...DEPENDENCY_PATHS].sort().join('\n')), DEPENDENCY_CATALOG_SHA256);
});
test('native descriptor accepts fixed start and rejects ambient or caller substitutions', () => {
  assert.equal(validateNativeSpec(launchSpec('mesh')), 'mesh');
  assert.equal(validateNativeSpec(launchSpec('standalone')), 'standalone');
  for (const mutate of [s => { s.argv = ['server.mjs']; }, s => { s.env.NODE_OPTIONS = '--import=evil'; },
    s => { s.env.PYTHONPATH = 'outside'; }, s => { s.env.PYTHONDONTWRITEBYTECODE = '0'; },
    s => { s.cwd = 'D:\\Dev\\Onoes-Mesh'; }, s => { s.env.MESH_PREVIEW_PORT = '4317'; }]) {
    const spec = structuredClone(launchSpec('mesh')); mutate(spec);
    assert.throws(() => validateNativeSpec(spec), /NATIVE_DESCRIPTOR/);
  }
});
test('native npm and server are distinct exact native descriptors', () => {
  const base = { pid: 900000, creationTime100ns: '123', executable: RUNTIMES.node, currentDirectory: WORKTREE };
  const npm = { ...base, argv: [RUNTIMES.node,RUNTIMES.npm,'start'] };
  const server = { ...base, pid: 900001, argv: ['node','test/m1-serve.mjs'] };
  validateNativeIdentity(npm, { argv: [RUNTIMES.node,RUNTIMES.npm,'start'] });
  validateNativeIdentity(server, { argv: [RUNTIMES.node,'test/m1-serve.mjs'] });
  assert.throws(() => validateNativeIdentity(npm, { argv: [RUNTIMES.node,'test/m1-serve.mjs'] }), /NATIVE_IDENTITY/);
  assert.throws(() => validateNativeIdentity(server, { argv: [RUNTIMES.node,RUNTIMES.npm,'start'] }), /NATIVE_IDENTITY/);
  for (const patch of [{ pid: 2612068 }, { executable: 'evil.exe' }, { creationTime100ns: 'missing' },
    { currentDirectory: 'D:\\Dev\\Onoes-Mesh' }, { commandLineError: 'unavailable' }])
    assert.throws(() => validateNativeIdentity({ ...server,...patch }, { argv: [RUNTIMES.node,'test/m1-serve.mjs'] }), /NATIVE_IDENTITY/);
});
test('failed launch is charged once and cannot implicitly retry', async () => {
  const r = rig(approved(), { mockEffects: { kind: 'pure-mock', runtime: false,
    async retainManager() {}, async prepareExclusive() {}, async launchRetained() { throw Error('failed spawn'); } } });
  await assert.rejects(r.controller.launch('mesh'), /failed spawn/);
  assert.equal(r.controller.status().starts, 1);
  assert.equal(r.controller.status().modes.mesh.generation, 1);
  await assert.rejects(r.controller.launch('mesh'), /DUPLICATE_LAUNCH/);
  assert.equal(r.controller.status().starts, 1);
});
test('monotonic rollback fails before further effects', async () => {
  const r = rig(); r.time(NOW, 100); await r.controller.launch('mesh'); const count = r.effects().length;
  r.time(NOW, 99); await assert.rejects(r.controller.restart('mesh', 1), /MONOTONIC_CLOCK/);
  assert.equal(r.effects().length, count);
});
test('start cap denies another launch before stop or spawn', async () => {
  const a = approved(); a.limits.starts = 2; const r = rig(a);
  await r.controller.launch('mesh'); await r.controller.launch('standalone'); const count = r.effects().length;
  await assert.rejects(r.controller.restart('mesh', 1), /START_RESTART_CAP/); assert.equal(r.effects().length, count);
});

// Exact historical ready descriptor, copied from NATIVE-RECEIPT.json; no intake reads.
const observedHarness = Object.freeze({
  role: 'M6 verification harness', pid: 2636856, creationTime100ns: '134357955391065983',
  executable: 'C:\\Program Files\\node.exe', parentPid: null,
  commandLine: '"C:/Program Files/node.exe" D:\\Dev\\Onoes-Mesh-wt\\closure-owner-fixture-native-adapter\\.runner\\closure-disposable-owner-fixture-verify\\parent-witness.mjs',
  argv: ['C:/Program Files/node.exe', 'D:\\Dev\\Onoes-Mesh-wt\\closure-owner-fixture-native-adapter\\.runner\\closure-disposable-owner-fixture-verify\\parent-witness.mjs'],
  currentDirectory: 'D:\\Dev\\Onoes-Mesh-wt\\closure-owner-fixture-native-adapter\\',
  purpose: 'M6 verification harness', worktree: 'D:\\Dev\\Onoes-Mesh-wt\\closure-owner-fixture-native-adapter',
  custodyClass: 'infrastructure', exitSignaled: false,
});
// Only prospective directory fields are rebound; the historical raw descriptor stays intact.
function readyDirectories() {
  const manager = { ...observedHarness, worktree: WORKTREE, currentDirectory: WORKTREE + '\\' };
  const observer = { pid: 4067260, parentPid: manager.pid, executable: 'C:\\Python314\\pythonw.exe' };
  return [manager, observer];
}
test('directory regression: actual native trailing separator is equal without changing raw receipt', () => {
  assert.notEqual(path.win32.normalize(observedHarness.currentDirectory), path.win32.normalize(observedHarness.worktree));
  assert.equal(path.win32.resolve(observedHarness.currentDirectory), path.win32.resolve(observedHarness.worktree));
  assert.equal(sameNativeDirectory(observedHarness.currentDirectory, observedHarness.worktree), true);
  assert.equal(observedHarness.currentDirectory.endsWith('\\'), true);
});
test('directory regression: fixed approved harness accepts the measured cwd representation', () => {
  const identities = readyDirectories(); const raw = JSON.stringify(identities);
  const retained = validateHarnessRetention(identities, 2636856, 4067260);
  assert.equal(retained.manager, identities[0]); assert.equal(retained.observer, identities[1]);
  assert.equal(JSON.stringify(identities), raw);
  const server = { ...identities[0], argv: ['node', 'test/m1-serve.mjs'] };
  assert.equal(validateNativeIdentity(server, { argv: [RUNTIMES.node, 'test/m1-serve.mjs'] }), server);
});
test('directory regression: different directory and caller cwd cannot replace fixed W', () => {
  for (const cwd of [observedHarness.currentDirectory, 'D:\\Dev\\Onoes-Mesh\\', WORKTREE + '-other\\', '.',
    'closure-fixture-cwd-repair\\', 'D:closure-fixture-cwd-repair', '\\Dev\\Onoes-Mesh-wt\\closure-fixture-cwd-repair\\']) {
    const identities = readyDirectories(); identities[0].currentDirectory = cwd;
    assert.throws(() => validateHarnessRetention(identities, 2636856, 4067260), /HARNESS_RETENTION/);
    assert.throws(() => validateNativeIdentity({ ...identities[0], argv: ['node','test/m1-serve.mjs'] },
      { argv: [RUNTIMES.node,'test/m1-serve.mjs'] }), /NATIVE_IDENTITY/);
  }
  const identities = readyDirectories(); identities[0].worktree = observedHarness.worktree;
  assert.throws(() => validateHarnessRetention(identities, 2636856, 4067260), /HARNESS_RETENTION/);
});
test('directory regression: harness parentage and executable/file argv checks remain exact', () => {
  for (const [index, patch] of [[0, { pid: 2636857 }], [1, { parentPid: 2636857 }],
    [0, { executable: RUNTIMES.node + '/' }], [1, { executable: RUNTIMES.observer + '/' }],
    [0, { commandLineError: 'unavailable' }]]) {
    const identities = readyDirectories(); Object.assign(identities[index], patch);
    assert.throws(() => validateHarnessRetention(identities, 2636856, 4067260), /HARNESS_RETENTION/);
  }
  const server = { ...readyDirectories()[0], currentDirectory: WORKTREE, argv: [RUNTIMES.node,'test/m1-serve.mjs'] };
  for (const patch of [{ executable: RUNTIMES.node + '/' }, { argv: [RUNTIMES.node + '/', 'test/m1-serve.mjs'] },
    { argv: [RUNTIMES.node, 'test/m1-serve.mjs/'] }, { creationTime100ns: 'missing' }, { currentDirectoryError: 'unavailable' }])
    assert.throws(() => validateNativeIdentity({ ...server, ...patch }, { argv: [RUNTIMES.node,'test/m1-serve.mjs'] }), /NATIVE_IDENTITY/);
});
