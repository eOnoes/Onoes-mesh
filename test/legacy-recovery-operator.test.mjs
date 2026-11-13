import nodeTest from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, realpathSync, writeFileSync, readFileSync, mkdirSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import { createServer } from 'node:net';
import { openTaskStore } from '../lib/task-store.mjs';
import { databaseFileIdentity } from '../lib/database-identity.mjs';
import { createDispatchBarrier } from '../lib/workroom-dispatch-barrier.mjs';
import { nativeResourceFingerprint } from '../lib/windows-native-maintenance.mjs';
import { legacyRecoveryFingerprint as hash } from '../lib/workroom-legacy-evidence.mjs';
import { readLegacyRows } from '../integrations/legacy-recovery-plan.mjs';
import { inspectReplayQueues, verifyReplayRecords, verifyStartupControls, loadOperatorScope, runLegacyOperator } from '../integrations/legacy-recovery-operator.mjs';

const test = process.platform === 'win32' && process.arch === 'x64' ? nodeTest : nodeTest.skip;
const sha = bytes => createHash('sha256').update(bytes).digest('hex');

async function fixture() {
  const dir = realpathSync.native(mkdtempSync(join(tmpdir(), 'mesh-operator-')));
  const databasePath = join(dir, 'tasks.sqlite'), store = openTaskStore(databasePath), db = new DatabaseSync(databasePath);
  const task = store.create({ title: 'Synthetic old requests', description: 'Disposable operator qualification only.' });
  const bindings = [];
  const relayPath = join(dir, 'relay.sqlite'), relay = new DatabaseSync(relayPath);
  relay.exec('CREATE TABLE outbox(idem_key TEXT,agent_id TEXT,session_id TEXT,state TEXT,transport_ref TEXT);');
  const hermesPath = join(dir, 'hermes.sqlite'), hermes = new DatabaseSync(hermesPath);
  hermes.exec('CREATE TABLE session_admissions(admission_id TEXT,request_id TEXT,target_session_id TEXT,payload_digest TEXT,status TEXT,outcome TEXT,owner_epoch INTEGER,generation INTEGER);');
  const tasks = [];
  for (let n = 0; n < 8; n++) {
    const sendId = 'send-' + n, agentId = n < 6 ? 'echo' : 'dsh', conversationId = 'fixture-session';
    db.prepare(`INSERT INTO workroom_sends(id,taskId,agentId,conversationId,text,fingerprint,state,at,payload,basis,phase)
      VALUES(?,?,?,?,?,?,'accepted',?,?,?,'work')`).run(sendId, task.id, agentId, conversationId, 'Synthetic request', 'a'.repeat(64), '2020-01-01T00:00:00Z', 'Synthetic payload', '{}');
    relay.prepare('INSERT INTO outbox VALUES(?,?,?,?,NULL)').run(sendId, agentId, conversationId, 'accepted');
    const binding = { sendId, agentId, conversationId };
    if (n < 6) {
      const record = { admission_id: 'admission-' + n, request_id: 'request-' + n, target_session_id: conversationId,
        payload_digest: sha('Synthetic request'), status: 'terminal', outcome: 'completed', owner_epoch: 1, generation: n + 1 };
      hermes.prepare('INSERT INTO session_admissions VALUES(?,?,?,?,?,?,?,?)').run(...Object.values(record));
      Object.assign(binding, { admissionId: record.admission_id, nativeFingerprint: hash(record) });
    } else {
      const record = { id: 'native-' + n, contextId: conversationId, status: { state: 3, timestamp: '2020-01-01T00:00:00Z' } };
      tasks.push(record); Object.assign(binding, { nativeTaskId: record.id, nativeFingerprint: hash(record) });
    }
    bindings.push(binding);
  }
  const dshPath = join(dir, 'dsh.json'); writeFileSync(dshPath, JSON.stringify(tasks));
  const originalDir = join(dir, 'Start Menu', 'Programs', 'Startup'); mkdirSync(originalDir, { recursive: true });
  const taskObservations = ['Hermes_Gateway', 'Onoes Deep Watchdog'].map(name => ({ name, path: '\\', enabled: false, state: 'Disabled',
    actions: [{ Execute: 'synthetic.exe', Arguments: '', WorkingDirectory: '' }], principal: { UserId: 'SYNTHETIC', LogonType: 'Interactive', RunLevel: 'Limited' } }));
  const shortcuts = ['Onoes Deep (DSH A2A).lnk', 'Onoes DeepSeek Harness Web.lnk'].map((name, i) => {
    const parked = join(dir, 'parked-' + i + '.lnk'); writeFileSync(parked, 'Synthetic shortcut ' + i);
    return { original: join(originalDir, name), parked, sha256: sha(readFileSync(parked)) };
  });
  const seed = createServer(); await new Promise(resolve => seed.listen(0, '127.0.0.1', resolve));
  const port = seed.address().port; await new Promise(resolve => seed.close(resolve));
  assert.ok(![3081, 4123, 4320, 8452, 8453, 8642].includes(port));
  const lock = join(dir, 'gateway.lock'); writeFileSync(lock, 'Synthetic lock');
  const scope = { schema: 'mesh/legacy-operator-scope/v1', owner: 'Eddie', locality: 'desktop_echo_dsh_only',
    workspace: realpathSync.native(process.cwd()), databasePath,
    relay: { path: relayPath, identity: databaseFileIdentity(relayPath) }, hermes: { path: hermesPath, identity: databaseFileIdentity(hermesPath) },
    dsh: { path: dshPath }, bindings, nativeResources: { profileLocks: [lock], endpoints: [['127.0.0.1', port], ['::1', port]] },
    startup: { tasks: taskObservations.map(({ name, path, actions, principal }) => ({ name, path, definitionFingerprint: hash({ actions, principal }) })), shortcuts } };
  const scopePath = join(dir, 'scope.json'); writeFileSync(scopePath, JSON.stringify(scope));
  const options = { scopePath, scopeSha256: sha(readFileSync(scopePath)), planPath: join(dir, 'plan.json') };
  const barrier = createDispatchBarrier(db); barrier.pause();
  const preparedAt = new Date(Date.now() - 120000).toISOString(), laterBoot = new Date(Date.now() - 60000).toISOString();
  let afterBoot = false;
  const runtime = { validateDeployment: candidate => assert.equal(candidate.databasePath, databasePath),
    startupReader: () => structuredClone(taskObservations), collect: async ({ sourceFiles }) => ({
    workspace: scope.workspace, databasePath, databaseIdentity: databaseFileIdentity(databasePath), host: 'SYNTHETIC', machineIdentity: '1'.repeat(64),
    bootedAt: afterBoot ? laterBoot : '2020-01-01T00:00:00Z', observedAt: afterBoot ? new Date().toISOString() : preparedAt,
    sources: { ...Object.fromEntries(Object.entries(sourceFiles).map(([name, path]) => [name, sha(readFileSync(path))])),
      nativeResourceScope: nativeResourceFingerprint(scope.nativeResources) }, ...readLegacyRows(databasePath, bindings.map(b => b.sendId)),
  }) };
  return { dir, scope, options, db, relay, hermes, barrier, runtime, taskObservations, tasks,
    targets: () => readLegacyRows(databasePath, bindings.map(b => b.sendId)).targets,
    boot() { afterBoot = true; },
    authorize() {
      const plan = JSON.parse(readFileSync(options.planPath, 'utf8')), path = join(dir, 'approval.json');
      writeFileSync(path, JSON.stringify({ schema: 'mesh/legacy-recovery-authorization/v1', owner: 'Eddie', decision: 'apply_exact_eight',
        planHash: plan.planHash, host: 'SYNTHETIC', bootedAt: laterBoot, authorizedAt: new Date(Date.now() - 1000).toISOString(), expiresAt: new Date(Date.now() + 60000).toISOString() }));
      return { authorizationPath: path, authorizationSha256: sha(readFileSync(path)) };
    },
    close() { db.close(); store.close(); relay.close(); hermes.close(); } };
}

test('the assembled operator prepares, denies same-boot apply, commits only after the fixture boot and exact approval, and stays paused', async () => {
  const f = await fixture();
  try {
    const originals = f.db.prepare('SELECT * FROM workroom_sends ORDER BY id').all();
    const prepared = await runLegacyOperator({ ...f.options, action: 'prepare' }, f.runtime);
    assert.equal(prepared.canRelease, false);
    assert.equal((await runLegacyOperator({ ...f.options, action: 'inspect' }, f.runtime)).status, 'blocked');
    await assert.rejects(runLegacyOperator({ ...f.options, action: 'apply', ...f.authorize() }, f.runtime), /later_pc_boot/);
    f.boot();
    const receipt = await runLegacyOperator({ ...f.options, action: 'apply', ...f.authorize() }, f.runtime);
    assert.equal(receipt.disposition, 'historical_outcome_unknown'); assert.equal(receipt.dispatchRemainsPaused, true);
    assert.equal(f.barrier.status().state, 'paused'); assert.equal(f.barrier.status().held, false);
    assert.deepEqual(f.db.prepare('SELECT * FROM workroom_sends ORDER BY id').all(), originals);
    assert.equal(f.db.prepare('SELECT COUNT(*) AS n FROM workroom_legacy_recovery_sends').get().n, 8);
  } finally { f.close(); }
});

test('the production entry refuses disposable or narrowed service coverage even with a pinned scope', async () => {
  const f = await fixture();
  try {
    const { validateDeployment, ...runtime } = f.runtime;
    await assert.rejects(runLegacyOperator({ ...f.options, action: 'prepare' }, runtime), /deployed service\/database layout/);
    assert.equal(existsSync(f.options.planPath), false);
  } finally { f.close(); }
});

test('replay checks reject queued Relay deliveries, unknown native admissions, changed exact receipts and incomplete native coverage', async () => {
  const f = await fixture();
  try {
    assert.equal(verifyReplayRecords(f.scope, f.targets()).exactAcceptedSends, 8);
    f.relay.prepare("INSERT INTO outbox VALUES('other','echo','other','retrying',NULL)").run();
    assert.equal(inspectReplayQueues(f.scope).relay.find(r => r.state === 'retrying').count, 1);
    assert.throws(() => verifyReplayRecords(f.scope, f.targets()), /unresolved queued/);
    f.relay.prepare("DELETE FROM outbox WHERE idem_key='other'").run();
    f.hermes.prepare("UPDATE session_admissions SET status='unknown' WHERE admission_id='admission-0'").run();
    assert.throws(() => verifyReplayRecords(f.scope, f.targets()), /unresolved native/);
    f.hermes.prepare("UPDATE session_admissions SET status='terminal',generation=99 WHERE admission_id='admission-0'").run();
    assert.throws(() => verifyReplayRecords(f.scope, f.targets()), /Echo admission changed/);
    f.hermes.prepare("UPDATE session_admissions SET generation=1 WHERE admission_id='admission-0'").run();
    const changed = structuredClone(f.scope); changed.bindings.pop();
    assert.throws(() => verifyReplayRecords(changed, f.targets()), /exactly the eight/);
    f.tasks[0].status.state = 1; writeFileSync(f.scope.dsh.path, JSON.stringify(f.tasks));
    assert.throws(() => verifyReplayRecords(f.scope, f.targets()), /replayable/);
  } finally { f.close(); }
});

test('startup checks reject enabled or changed tasks, active login shortcuts, changed parked bytes, and replacement scope', async () => {
  const f = await fixture();
  try {
    verifyStartupControls(f.scope, f.taskObservations);
    const enabled = structuredClone(f.taskObservations); enabled[0].enabled = true;
    assert.throws(() => verifyStartupControls(f.scope, enabled), /restart owner/);
    const changed = structuredClone(f.taskObservations); changed[0].actions[0].Arguments = 'different';
    assert.throws(() => verifyStartupControls(f.scope, changed), /restart owner/);
    writeFileSync(f.scope.startup.shortcuts[0].original, 'Active');
    assert.throws(() => verifyStartupControls(f.scope, f.taskObservations), /shortcut remains active/);
    assert.equal(existsSync(f.scope.startup.shortcuts[0].parked), true);
    loadOperatorScope(f.options.scopePath, f.options.scopeSha256);
    writeFileSync(f.options.scopePath, readFileSync(f.options.scopePath, 'utf8') + ' ');
    assert.throws(() => loadOperatorScope(f.options.scopePath, f.options.scopeSha256), /reviewed hash/);
  } finally { f.close(); }
});

test('the final composed guard rolls back when replay becomes uncertain immediately before commit', async () => {
  const f = await fixture();
  try {
    await runLegacyOperator({ ...f.options, action: 'prepare' }, f.runtime); f.boot();
    let checks = 0;
    const runtime = { ...f.runtime, startupReader() {
      if (++checks === 4) f.hermes.prepare("UPDATE session_admissions SET status='unknown' WHERE admission_id='admission-0'").run();
      return structuredClone(f.taskObservations);
    } };
    await assert.rejects(runLegacyOperator({ ...f.options, action: 'apply', ...f.authorize() }, runtime), /unresolved native/);
    assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE name LIKE 'workroom_legacy_recover%'").get().n, 0);
    assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM workroom_events WHERE kind='legacy_recovery_recorded'").get().n, 0);
    assert.equal(f.barrier.status().state, 'paused'); assert.equal(f.barrier.status().held, false);
  } finally { f.close(); }
});
