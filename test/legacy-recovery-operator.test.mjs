import nodeTest from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, realpathSync, writeFileSync, readFileSync, mkdirSync, existsSync } from 'node:fs';
import { tmpdir, homedir } from 'node:os';
import { join, resolve, relative } from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync, spawnSync } from 'node:child_process';
import { DatabaseSync } from 'node:sqlite';
import { createServer } from 'node:net';
import { openTaskStore } from '../lib/task-store.mjs';
import { databaseFileIdentity } from '../lib/database-identity.mjs';
import { createDispatchBarrier } from '../lib/workroom-dispatch-barrier.mjs';
import { nativeResourceFingerprint } from '../lib/windows-native-maintenance.mjs';
import { legacyRecoveryFingerprint as hash } from '../lib/workroom-legacy-evidence.mjs';
import { readLegacyRows, legacyRecoverySources } from '../integrations/legacy-recovery-plan.mjs';
import { normalizeRelayDelivery, verifyDshOrigins, inspectReplayQueues, inspectRetainedRecords, verifyRetainedReview, verifyReplayRecords, verifyStartupControls, loadOperatorScope, runLegacyOperator } from '../integrations/legacy-recovery-operator.mjs';

const test = process.platform === 'win32' && process.arch === 'x64' ? nodeTest : nodeTest.skip;
const sha = bytes => createHash('sha256').update(bytes).digest('hex');

async function fixture() {
  const dir = realpathSync.native(mkdtempSync(join(tmpdir(), 'mesh-operator-')));
  const databasePath = join(dir, 'tasks.sqlite'), store = openTaskStore(databasePath), db = new DatabaseSync(databasePath);
  const task = store.create({ title: 'Synthetic old requests', description: 'Disposable operator qualification only.' });
  const bindings = [];
  const relayPath = join(dir, 'relay.sqlite'), relay = new DatabaseSync(relayPath);
  relay.exec('CREATE TABLE outbox(idem_key TEXT,agent_id TEXT,session_id TEXT,state TEXT,transport_ref TEXT,content TEXT);');
  const hermesPath = join(dir, 'hermes.sqlite'), hermes = new DatabaseSync(hermesPath);
  hermes.exec('CREATE TABLE session_admissions(admission_id TEXT,request_id TEXT,target_session_id TEXT,payload_digest TEXT,status TEXT,outcome TEXT,owner_epoch INTEGER,generation INTEGER,payload_json TEXT);');
  const tasks = [];
  for (let n = 0; n < 8; n++) {
    const sendId = 'send-' + n, agentId = n < 6 ? 'echo' : 'dsh', conversationId = 'fixture-session', delivery = 'Synthetic delivery ' + n;
    db.prepare(`INSERT INTO workroom_sends(id,taskId,agentId,conversationId,text,fingerprint,state,at,payload,basis,phase)
      VALUES(?,?,?,?,?,?,'accepted',?,?,?,'work')`).run(sendId, task.id, agentId, conversationId, 'Synthetic request', 'a'.repeat(64), '2020-01-01T00:00:00Z', delivery, '{}');
    relay.prepare('INSERT INTO outbox VALUES(?,?,?,?,NULL,?)').run(sendId, agentId, conversationId, 'accepted', delivery);
    const binding = { sendId, agentId, conversationId };
    if (n < 6) {
      const record = { admission_id: 'admission-' + n, request_id: 'request-' + n, target_session_id: conversationId,
        payload_digest: sha(delivery), status: 'terminal', outcome: 'completed', owner_epoch: 1, generation: n + 1 };
      hermes.prepare('INSERT INTO session_admissions VALUES(?,?,?,?,?,?,?,?,?)').run(...Object.values(record), JSON.stringify({ text: delivery }));
      Object.assign(binding, { admissionId: record.admission_id, nativeFingerprint: hash(record) });
    } else {
      const record = { id: 'native-' + n, contextId: conversationId, status: { state: 3, timestamp: '2020-01-01T00:00:00Z' } };
      const origin = { role: 1, messageId: 'origin-' + n, taskId: '', contextId: 'original-client-context',
        parts: [{ content: { $case: 'text', value: delivery } }] };
      const history = [origin];
      if (n === 7) history.push({ role: 2, messageId: 'response-7', parts: [] },
        { role: 1, messageId: 'followup-7', taskId: record.id, contextId: origin.contextId,
          parts: [{ content: { $case: 'text', value: 'A different later request' } }] });
      tasks.push({ ...record, history });
      Object.assign(binding, { nativeTaskId: record.id, nativeFingerprint: hash(record),
        originMessageId: origin.messageId, originFingerprint: hash(origin) });
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
    workspace: realpathSync.native(process.cwd()), databasePath, databaseIdentity: databaseFileIdentity(databasePath),
    relay: { path: relayPath, identity: databaseFileIdentity(relayPath) }, hermes: { path: hermesPath, identity: databaseFileIdentity(hermesPath) },
    dsh: { path: dshPath, sha256: sha(readFileSync(dshPath)) }, bindings, nativeResources: { profileLocks: [lock], endpoints: [['127.0.0.1', port], ['::1', port]] },
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
    f.relay.prepare("INSERT INTO outbox VALUES('other','echo','other','retrying',NULL,'Other')").run();
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
    assert.throws(() => verifyReplayRecords(f.scope, f.targets()), /reviewed hash/);
    const deliveries = new Map(f.scope.bindings.filter(b => b.agentId === 'dsh').map(b => [b.sendId,
      f.db.prepare('SELECT payload FROM workroom_sends WHERE id=?').get(b.sendId).payload]));
    assert.throws(() => verifyDshOrigins(f.tasks, f.scope.bindings, deliveries), /replayable/);
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

test('the final composed guard rolls back when replay becomes uncertain or its exact input changes before commit', async () => {
  for (const corruption of ['status', 'echoText', 'dshSnapshot']) {
  const f = await fixture();
  try {
    await runLegacyOperator({ ...f.options, action: 'prepare' }, f.runtime); f.boot();
    let checks = 0;
    const runtime = { ...f.runtime, startupReader() {
      if (++checks === 4) {
        if (corruption === 'dshSnapshot') writeFileSync(f.scope.dsh.path, JSON.stringify([...f.tasks, { id: 'unreviewed-task', history: [] }]));
        else if (corruption === 'echoText') f.hermes.prepare("UPDATE session_admissions SET payload_json=? WHERE admission_id='admission-0'").run(JSON.stringify({ text: 'Different original' }));
        else f.hermes.prepare("UPDATE session_admissions SET status='unknown' WHERE admission_id='admission-0'").run();
      }
      return structuredClone(f.taskObservations);
    } };
    await assert.rejects(runLegacyOperator({ ...f.options, action: 'apply', ...f.authorize() }, runtime),
      corruption === 'dshSnapshot' ? /reviewed hash/ : corruption === 'echoText' ? /Echo request text/ : /unresolved native/);
    assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE name LIKE 'workroom_legacy_recover%'").get().n, 0);
    assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM workroom_events WHERE kind='legacy_recovery_recorded'").get().n, 0);
    assert.equal(f.barrier.status().state, 'paused'); assert.equal(f.barrier.status().held, false);
  } finally { f.close(); }
  }
});


test('exact native receipts cannot substitute another request with the same completed status and conversation', async () => {
  const f = await fixture();
  try {
    f.relay.prepare("UPDATE outbox SET content='Different request' WHERE idem_key='send-0'").run();
    assert.throws(() => verifyReplayRecords(f.scope, f.targets()), /original delivery payload/);
    f.relay.prepare("UPDATE outbox SET content='Synthetic delivery 0' WHERE idem_key='send-0'").run();
    f.hermes.prepare("UPDATE session_admissions SET payload_json=? WHERE admission_id='admission-0'").run(JSON.stringify({text:'Different request'}));
    assert.throws(() => verifyReplayRecords(f.scope, f.targets()), /Echo request text/);
    f.hermes.prepare("UPDATE session_admissions SET payload_json=? WHERE admission_id='admission-0'").run(JSON.stringify({text:'Synthetic delivery 0'}));
    const other = structuredClone(f.scope); other.bindings[0].conversationId = 'another-conversation';
    f.relay.prepare("UPDATE outbox SET session_id='another-conversation' WHERE idem_key='send-0'").run();
    assert.throws(() => verifyReplayRecords(other, f.targets()), /original Workroom delivery/);
    f.relay.prepare("UPDATE outbox SET session_id='fixture-session' WHERE idem_key='send-0'").run();
    const swapped = structuredClone(f.scope), a = swapped.bindings[6], b = swapped.bindings[7];
    [a.nativeTaskId, b.nativeTaskId] = [b.nativeTaskId, a.nativeTaskId];
    [a.nativeFingerprint, b.nativeFingerprint] = [b.nativeFingerprint, a.nativeFingerprint];
    [a.originMessageId, b.originMessageId] = [b.originMessageId, a.originMessageId];
    [a.originFingerprint, b.originFingerprint] = [b.originFingerprint, a.originFingerprint];
    assert.throws(() => verifyReplayRecords(swapped, f.targets()), /DSH request text/);
    assert.equal(verifyReplayRecords(f.scope, f.targets()).exactAcceptedSends, 8);
  } finally { f.close(); }
});

test('delivery normalization matches Python strip, including Unicode boundaries and preserved interior whitespace', async () => {
  const f = await fixture();
  try {
    const inputs = ['\u0085Synthetic delivery 0\u001c', '\u001f\t Synthetic delivery 0\u3000',
      '\ufeffSynthetic delivery 0\ufeff', ' \tSynthetic  delivery\n0\r ', '\u200bSynthetic delivery 0\u200b'];
    const expected = JSON.parse(execFileSync('python', ['-X', 'utf8', '-c',
      'import json,sys;print(json.dumps([v.strip() for v in json.load(sys.stdin)]))'],
    { input: JSON.stringify(inputs), encoding: 'utf8', windowsHide: true, timeout: 10000 }));
    for (let n = 0; n < inputs.length; n++) {
      f.db.prepare("UPDATE workroom_sends SET payload=? WHERE id='send-0'").run(inputs[n]);
      f.relay.prepare("UPDATE outbox SET content=? WHERE idem_key='send-0'").run(expected[n]);
      f.hermes.prepare("UPDATE session_admissions SET payload_json=?,payload_digest=? WHERE admission_id='admission-0'")
        .run(JSON.stringify({ text: expected[n] }), sha(expected[n]));
      const receipt = f.hermes.prepare("SELECT admission_id,request_id,target_session_id,payload_digest,status,outcome,owner_epoch,generation FROM session_admissions WHERE admission_id='admission-0'").get();
      f.scope.bindings[0].nativeFingerprint = hash(receipt);
      assert.doesNotThrow(() => verifyReplayRecords(f.scope, f.targets()), 'Python-normalized delivery case ' + n);
    }
  } finally { f.close(); }
});

test('the boundary classifier matches Python across every Unicode codepoint and preserves interior whitespace', () => {
  const pythonWhitespace = JSON.parse(execFileSync('python', ['-X', 'utf8', '-c',
    'import json;print(json.dumps([n for n in range(0x110000) if chr(n).isspace()]))'],
  { encoding: 'utf8', windowsHide: true, timeout: 10000 }));
  const stripped = new Set(pythonWhitespace);
  for (let n = 0; n < 0x110000; n++) {
    const character = String.fromCodePoint(n), input = character + 'anchor' + character;
    assert.equal(normalizeRelayDelivery(input), stripped.has(n) ? 'anchor' : input, 'Boundary codepoint ' + n);
  }
  for (const n of stripped) {
    const input = 'left' + String.fromCodePoint(n) + 'right';
    assert.equal(normalizeRelayDelivery(input), input, 'Interior codepoint ' + n);
  }
});

test('DSH binds the pinned origin message and supports later follow-up history without inferring original success', async () => {
  const f = await fixture();
  try {
    const followup = f.tasks[1].history.at(-1);
    assert.equal(verifyReplayRecords(f.scope, f.targets()).completedDshTasks, 2);
    const wrong = structuredClone(f.scope); wrong.bindings[7].originMessageId = followup.messageId;
    wrong.bindings[7].originFingerprint = hash(followup);
    assert.throws(() => verifyReplayRecords(wrong, f.targets()), /DSH origin/);
    f.tasks[1].history.unshift({ ...followup, taskId: '', messageId: 'unrelated-origin' });
    writeFileSync(f.scope.dsh.path, JSON.stringify(f.tasks));
    assert.throws(() => verifyReplayRecords(f.scope, f.targets()), /reviewed hash/);
    const deliveries = new Map(f.scope.bindings.filter(b => b.agentId === 'dsh').map(b => [b.sendId,
      f.db.prepare('SELECT payload FROM workroom_sends WHERE id=?').get(b.sendId).payload]));
    assert.throws(() => verifyDshOrigins(f.tasks, f.scope.bindings, deliveries), /DSH origin/);
    f.tasks[1].history.shift();
    const duplicate = structuredClone(f.tasks[1]); duplicate.id = 'unrelated-task';
    writeFileSync(f.scope.dsh.path, JSON.stringify([...f.tasks, duplicate]));
    assert.throws(() => verifyReplayRecords(f.scope, f.targets()), /reviewed hash/);
    assert.throws(() => verifyDshOrigins([...f.tasks, duplicate], f.scope.bindings, deliveries), /DSH origin/);
  } finally { f.close(); }
});

test('the reviewed DSH snapshot rejects changes outside selected receipts instead of trusting origin placement alone', async () => {
  const f = await fixture();
  try {
    f.tasks.push({ id: 'unreviewed-task', contextId: 'elsewhere', status: { state: 2 }, history: [] });
    writeFileSync(f.scope.dsh.path, JSON.stringify(f.tasks));
    assert.throws(() => verifyReplayRecords(f.scope, f.targets()), /reviewed hash/);
  } finally { f.close(); }
});

test('retained-record diagnostics show exact links and private row digests without exposing content or deciding writer scope', async () => {
  const f = await fixture();
  try {
    f.scope.relay.extraSecret = 'SCOPE_SECRET_DO_NOT_EMIT';
    f.relay.prepare("INSERT INTO outbox VALUES('old-delivery','echo','fixture-session','retrying',NULL,?)").run('PRIVATE_BODY_DO_NOT_EMIT');
    f.relay.prepare("UPDATE outbox SET state='retrying' WHERE idem_key='send-0'").run();
    f.hermes.exec('ALTER TABLE session_admissions ADD COLUMN principal_id TEXT;');
    f.hermes.prepare(`INSERT INTO session_admissions(admission_id,request_id,target_session_id,payload_digest,status,outcome,owner_epoch,generation,payload_json,principal_id)
      VALUES('unbound-admission','old-native','another-session','digest','unknown',NULL,1,1,?,?)`)
      .run(JSON.stringify({ native_text_v1: { text: 'PRIVATE_BODY_DO_NOT_EMIT' } }), 'messaging:telegram:PRIVATE_PRINCIPAL_DO_NOT_EMIT');
    const snapshot = () => hash({ sends: f.db.prepare('SELECT * FROM workroom_sends').all(), relay: f.relay.prepare('SELECT * FROM outbox').all(),
      native: f.hermes.prepare('SELECT * FROM session_admissions').all(), tables: f.db.prepare("SELECT name FROM sqlite_master ORDER BY name").all() });
    const before = snapshot(), report = inspectRetainedRecords(f.scope), serialized = JSON.stringify(report);
    assert.equal(snapshot(), before);
    assert.equal(report.records.length, 3); assert.equal(report.canRelease, false);
    for (const privateValue of ['PRIVATE_BODY_DO_NOT_EMIT', 'PRIVATE_PRINCIPAL_DO_NOT_EMIT', 'SCOPE_SECRET_DO_NOT_EMIT'])
      assert.ok(!serialized.includes(privateValue), 'Diagnostic exposed ' + privateValue);
    const old = report.records.find(record => record.recordId === 'old-delivery');
    assert.deepEqual(old.directWorkroomTaskIds, []); assert.equal(old.sharedConversationTaskIds.length, 1);
    const linked = report.records.find(record => record.recordId === 'send-0'); assert.equal(linked.directWorkroomTaskIds.length, 1);
    const native = report.records.find(record => record.recordId === 'unbound-admission');
    assert.equal(native.principalClass, 'telegram'); assert.deepEqual(native.directWorkroomTaskIds, []);
    for (const record of report.records) {
      assert.match(record.recordFingerprint, /^[a-f0-9]{64}$/); assert.equal(record.decision, 'unresolved_do_not_release');
    }
    f.relay.prepare("UPDATE outbox SET content='Changed private request' WHERE idem_key='old-delivery'").run();
    assert.notEqual(inspectRetainedRecords(f.scope).records.find(record => record.recordId === 'old-delivery').recordFingerprint, old.recordFingerprint);
  } finally { f.close(); }
});

test('inspect explains unmatched records while the same apply path still refuses them', async () => {
  const f = await fixture();
  try {
    await runLegacyOperator({ ...f.options, action: 'prepare' }, f.runtime); f.boot();
    f.relay.prepare("INSERT INTO outbox VALUES('old-delivery','echo','elsewhere','retrying',NULL,'Private fixture')").run();
    const result = await runLegacyOperator({ ...f.options, action: 'inspect' }, f.runtime);
    assert.equal(result.controls.status, 'blocked'); assert.equal(result.canRelease, false);
    assert.equal(result.retainedRecords.records[0].recordId, 'old-delivery');
    await assert.rejects(runLegacyOperator({ ...f.options, action: 'apply', ...f.authorize() }, f.runtime), /unresolved queued/);
    assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE name LIKE 'workroom_legacy_recover%'").get().n, 0);
  } finally { f.close(); }
});

test('diagnose refuses file overrides and an unrelated current directory before opening native data', async () => {
  const f = await fixture();
  try {
    const script = resolve('integrations/legacy-recovery-operator.mjs');
    const override = spawnSync(process.execPath, [script, 'diagnose', '--ignore-holds'], { cwd: f.dir, windowsHide: true, encoding: 'utf8' });
    assert.equal(override.status, 1); assert.match(override.stderr, /no scope, overrides or approval/);
    const elsewhere = spawnSync(process.execPath, [script, 'diagnose'], { cwd: f.dir, windowsHide: true, encoding: 'utf8' });
    assert.equal(elsewhere.status, 1); assert.match(elsewhere.stderr, /from its Mesh workspace/);
    assert.equal(override.stdout, ''); assert.equal(elsewhere.stdout, '');
  } finally { f.close(); }
});

// Qualification metadata is synthetic here; files are hashed, not executed.
// Real startup execution is qualified separately by the committed helper scripts.
function retainedFixture(f) {
  f.relay.prepare("INSERT INTO outbox VALUES('old-dsh','dsh','fixture-session','retrying',NULL,'Synthetic private request')").run();
  f.relay.prepare("INSERT INTO outbox VALUES('old-cyony','cyony','elsewhere','retrying',NULL,'Synthetic other request')").run();
  f.hermes.exec('ALTER TABLE session_admissions ADD COLUMN principal_id TEXT;');
  f.hermes.prepare(`INSERT INTO session_admissions(admission_id,request_id,target_session_id,payload_digest,status,outcome,owner_epoch,generation,payload_json,principal_id)
    VALUES('old-unknown','old-input','elsewhere','digest','unknown',NULL,1,1,?,'messaging:telegram:synthetic')`)
    .run(JSON.stringify({ native_text_v1: { text: 'Synthetic request' } }));
  const hashFiles = files => Object.fromEntries(files.map(([name, file]) => [name, sha(readFileSync(file))]));
  const relayNames = ['relay_server.py','relay_a2a.py','relay_a2a_reconcile.py','relay_auth.py','relay_budget.py','relay_channels.py',
    'relay_config.py','relay_db.py','relay_hermes.py','relay_inbox.py','relay_mcp.py','relay_native_receipts.py','relay_notify.py','relay_openclaw.py','relay_sessions.py','relay_webpush.py'];
  const relay = { schema: 'mesh/relay-retained-startup-qualification/v1', liveStoreOpened: false, liveDeploymentChanged: false,
    networkOrProcessAttempts: 0, boundaryRejectionControlsPassed: 3,
    cases: [1,2].map(boot => ({ boot, startupTransportCalls: 0, duplicateTransportCalls: 0, freshRequestTransportCalls: 1, retainedRowsUnchanged: true })),
    sourceSha256: hashFiles(relayNames.map(name => [name, resolve('D:/Dev/Onoes-Relay',name)])),
    qualificationHelperSha256: sha(readFileSync('integrations/qualify-relay-retained-startup.py')) };
  const nativeRoot = resolve(homedir(), 'AppData/Local/hermes/hermes-agent');
  const native = { schema: 'mesh/native-retained-startup-qualification/v1', liveStoreOpened: false, liveServiceRestarted: false,
    originalWorkerRetirementEstablished: false, coordinatorIsPrimaryRecovery: true,
    recoveries: [1,2].map(startup => ({ startup, syntheticModelCalls: startup === 1 ? 1 : 0, unknownRemainedPaused: true,
      blockedFollowerRemainedQueued: true, safeRequestCompleted: true, gatewayCoordinatorPreservedRows: true })),
    sourceSha256: hashFiles(Object.entries(legacyRecoverySources(process.cwd())).filter(([name]) => name.startsWith('hermesRecovery'))
      .map(([,file]) => [relative(nativeRoot,file).split('\\').join('/'),file])),
    helperSha256: hashFiles(['qualify-native-retained-startup.py','qualify-native-retained-peer.py','qualify-native-retained-recovery.py']
      .map(name => [name,resolve('integrations',name)])) };
  const save = (name, data) => { const path = join(f.dir,name); writeFileSync(path,JSON.stringify(data));return { path, sha256:sha(readFileSync(path)) }; };
  const actual = inspectRetainedRecords(f.scope);
  const review = { schema: 'mesh/retained-record-review/v1', owner:'Eddie', decision:'preserve_without_retry_or_retirement',
    writerScope:'confirmed_desktop_only', selectedSendIds:f.scope.bindings.map(binding=>binding.sendId),
    records:actual.records, sources:actual.sources, qualifications:{ relay:save('relay-proof.json',relay),native:save('native-proof.json',native) } };
  function seal() {
    f.scope.retainedReview=save('retained-review.json',review);
    writeFileSync(f.options.scopePath,JSON.stringify(f.scope));f.options.scopeSha256=sha(readFileSync(f.options.scopePath));
  }
  seal();return { review, relay, native, save, seal };
}

test('the exact retained review matches synthetic evidence without mutating records or bypassing the live recovery queue guard', async () => {
  const f = await fixture();
  try {
    await runLegacyOperator({ ...f.options,action:'prepare' },f.runtime);f.boot();
    retainedFixture(f);
    const rows=()=>hash({relay:f.relay.prepare('SELECT * FROM outbox').all(),native:f.hermes.prepare('SELECT * FROM session_admissions').all()});
    const before=rows(), result=verifyRetainedReview(f.scope);
    assert.equal(result.status,'matched_review_only');assert.equal(result.canRelease,false);assert.equal(result.workerRetirementEstablished,false);
    assert.equal(rows(),before);
    const inspected=await runLegacyOperator({...f.options,action:'inspect'},f.runtime);
    assert.equal(inspected.retainedReview.status,'matched_review_only');assert.equal(inspected.controls.status,'blocked');assert.equal(inspected.canRelease,false);
    await assert.rejects(runLegacyOperator({...f.options,action:'apply',...f.authorize()},f.runtime),/unresolved queued/);
    assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE name LIKE 'workroom_legacy_recover%'").get().n,0);
    assert.equal(rows(),before);
  } finally {f.close();}
});

test('retained reviews reject row/link/schema drift, new work and missing owner scope without using absence of task IDs as scope proof',async()=>{
  for(const change of ['row','link','schema','newWork','ownerScope','selectedSend','automation','nativeNull']) {
    const f=await fixture();
    try {
      const r=retainedFixture(f);
      if(change==='row')f.relay.prepare("UPDATE outbox SET content='Changed' WHERE idem_key='old-dsh'").run();
      if(change==='link'){
        f.db.prepare("UPDATE workroom_sends SET conversationId='moved-conversation' WHERE conversationId='fixture-session'").run();
        assert.equal(inspectRetainedRecords(f.scope).records.find(record=>record.recordId==='old-dsh').recordFingerprint,
          r.review.records.find(record=>record.recordId==='old-dsh').recordFingerprint);
      }
      if(change==='schema')f.relay.exec('ALTER TABLE outbox ADD COLUMN extra TEXT');
      if(change==='newWork')f.relay.prepare("INSERT INTO outbox VALUES('new','dsh','elsewhere','queued',NULL,'New')").run();
      if(change==='ownerScope'){r.review.writerScope='pending';r.seal();}
      if(change==='selectedSend'){r.review.selectedSendIds.pop();r.seal();}
      if(change==='automation'||change==='nativeNull'){
        f.hermes.prepare("UPDATE session_admissions SET payload_json=? WHERE admission_id='old-unknown'").run(JSON.stringify(change==='automation'?{local_automation_v1:{}}:{native_text_v1:null}));
        r.review.records=inspectRetainedRecords(f.scope).records;r.seal();
      }
      assert.throws(()=>verifyRetainedReview(f.scope));
    }finally{f.close();}
  }
});

test('retained reviews require exact pinned proofs, complete source sets, current qualifier bytes and full coordinator evidence',async()=>{
  for(const change of ['nativeSource','relaySourceSet','helper','coordinator','proofBytes','reviewBytes','malformed']) {
    const f=await fixture();
    try {
      const r=retainedFixture(f);
      if(change==='nativeSource')r.native.sourceSha256['gateway/session_authority.py']='0'.repeat(64);
      if(change==='relaySourceSet')delete r.relay.sourceSha256['relay_a2a.py'];
      if(change==='helper')r.native.helperSha256['qualify-native-retained-peer.py']='0'.repeat(64);
      if(change==='coordinator')r.native.coordinatorIsPrimaryRecovery=false;
      if(['nativeSource','helper','coordinator'].includes(change)){r.review.qualifications.native=r.save('native-proof.json',r.native);r.seal();}
      if(change==='relaySourceSet'){r.review.qualifications.relay=r.save('relay-proof.json',r.relay);r.seal();}
      if(change==='proofBytes')writeFileSync(r.review.qualifications.native.path,'{}');
      if(change==='reviewBytes')writeFileSync(f.scope.retainedReview.path,'{}');
      if(change==='malformed'){writeFileSync(f.scope.retainedReview.path,'PRIVATE_BAD_JSON');f.scope.retainedReview.sha256=sha(readFileSync(f.scope.retainedReview.path));}
      assert.throws(()=>verifyRetainedReview(f.scope),change==='malformed'?/not valid JSON/:undefined);
    }finally{f.close();}
  }
});
