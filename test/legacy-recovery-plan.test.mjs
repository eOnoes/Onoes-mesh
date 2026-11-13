import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import {makeLegacyRecoveryPlan,assessLegacyRecovery,legacyMachineIdentity,legacyRecoveryFingerprint} from '../lib/workroom-legacy-evidence.mjs';
import {readLegacyRows} from '../integrations/legacy-recovery-plan.mjs';

const snapshot = () => ({ workspace: resolve('synthetic-mesh'), databasePath: resolve('synthetic.sqlite'), databaseIdentity: 'd'.repeat(64), boardSha256: 'f'.repeat(64), taskCount: 14, host: 'SYNTHETIC',
  machineIdentity: '1'.repeat(64), bootedAt: '2026-10-30T16:43:37.000Z', observedAt: '2026-11-13T03:00:00.000Z',
  sources: Object.fromEntries(['mesh', 'relay', 'hermes', 'dsh'].map(k => [k, 'a'.repeat(64)])),
  targets: Array.from({ length: 8 }, (_, n) => ({ taskId: 'task-' + n, sendId: 'send-' + n, agentId: n < 6 ? 'echo' : 'dsh',
    fingerprint: 'b'.repeat(64), state: 'accepted', phase: 'work', nativeBound: false })), otherWorkSendIds: [], otherWriterHolds: [] });

test('same-boot live-like evidence remains blocked and never grants release', () => {
  const s = snapshot(), plan = makeLegacyRecoveryPlan(s), result = assessLegacyRecovery(plan, s);
  assert.equal(result.status, 'blocked');
  assert.deepEqual(result.reasons, ['later_pc_boot_not_verified']);
  assert.equal(result.canRelease, false);
});

test('later boot only reaches operator review and preserves unknown outcome', () => {
  const s = snapshot(), plan = makeLegacyRecoveryPlan(s);
  const observation = { ...s, bootedAt: '2026-11-13T04:00:00Z', observedAt: '2026-11-13T04:01:00Z', targets: [...s.targets].reverse() };
  const result = assessLegacyRecovery(plan, observation);
  assert.equal(result.status, 'ready_for_operator_review');
  assert.equal(result.canRelease, false);
  assert.equal(result.disposition, 'historical_outcome_unknown');
  assert.equal(result.pcCustody.boardPreserved, true);
  assert.equal(result.pcCustody.workerRetirementEstablished, false);
});

test('changed identity, source, receipt or extra work cannot pass the review assessment', () => {
  const s = snapshot(), plan = makeLegacyRecoveryPlan(s);
  for (const [change, reason] of [
    [{ host: 'OTHER-PC' }, 'host_changed'], [{ workspace: resolve('other') }, 'workspace_or_database_changed'],
    [{ machineIdentity: '2'.repeat(64) }, 'machine_identity_changed'],
    [{ databasePath: resolve('other.sqlite') }, 'workspace_or_database_changed'],
    [{ databaseIdentity: 'e'.repeat(64) }, 'workspace_or_database_changed'],
    [{ boardSha256: 'e'.repeat(64) }, 'saved_board_changed'],
    [{ taskCount: 15 }, 'saved_board_changed'],
    [{ sources: { ...s.sources, relay: 'c'.repeat(64) } }, 'source_changed'],
    [{ targets: s.targets.map((t, n) => n ? t : { ...t, fingerprint: 'c'.repeat(64) }) }, 'legacy_send_changed'],
    [{ otherWorkSendIds: ['new-writer'] }, 'other_work_requires_reconciliation'],
    [{ otherWriterHolds: [{ taskId: 'new', sendId: '', reason: 'active_team' }] }, 'other_writer_holds_require_reconciliation'],
  ]) {
    const result = assessLegacyRecovery(plan, { ...s, bootedAt: '2026-11-13T04:00:00Z', observedAt: '2026-11-13T04:01:00Z', ...change });
    assert.ok(result.reasons.includes(reason), reason); assert.equal(result.canRelease, false);
  }
  assert.throws(() => assessLegacyRecovery({ ...plan, host: 'OTHER-PC' }, s), /identity changed/);
});

test('only the exact eight accepted unbound legacy work sends can be prepared', () => {
  const s = snapshot();
  for (const targets of [s.targets.slice(1), [...s.targets, s.targets[0]],
    s.targets.map((t, n) => n ? t : { ...t, nativeBound: true }),
    s.targets.map((t, n) => n ? t : { ...t, state: 'unknown' }),
    s.targets.map((t, n) => n ? t : { ...t, agentId: 'nims' }),
  ]) assert.throws(() => makeLegacyRecoveryPlan({ ...s, targets }));
  assert.throws(() => makeLegacyRecoveryPlan({ ...s, otherWorkSendIds: ['new'] }));
  assert.throws(() => makeLegacyRecoveryPlan({ ...s, otherWriterHolds: [{ taskId: 'new', reason: 'active_team' }] }));
});

test('real SQLite reads preserve original records and detect payload edits and other work', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'mesh-legacy-plan-'));
  try {
    const path = join(dir, 'tasks.sqlite'), db = new DatabaseSync(path);
    db.exec('CREATE TABLE tasks(id TEXT PRIMARY KEY); CREATE TABLE workroom_sends(id TEXT PRIMARY KEY,taskId TEXT,agentId TEXT,state TEXT,phase TEXT,payload TEXT); CREATE TABLE workroom_local_sessions(sendId TEXT); CREATE TABLE workroom_automation(taskId TEXT,state TEXT); CREATE TABLE workroom_flow(taskId TEXT,state TEXT,sendId TEXT);');
    const s = snapshot();
    for (const t of s.targets) {
      db.prepare('INSERT INTO tasks VALUES(?)').run(t.taskId);
      db.prepare('INSERT INTO workroom_sends VALUES(?,?,?,?,?,?)').run(t.sendId, t.taskId, t.agentId, t.state, t.phase, 'original');
    }
    const ids = s.targets.map(t => t.sendId), before = db.prepare('SELECT * FROM workroom_sends ORDER BY id').all();
    const first = readLegacyRows(path, ids);
    assert.deepEqual(db.prepare('SELECT * FROM workroom_sends ORDER BY id').all(), before);
    assert.equal(readLegacyRows(path, ids).boardSha256, first.boardSha256);
    db.prepare("INSERT INTO workroom_automation VALUES('other','active')").run();
    assert.deepEqual(readLegacyRows(path, ids).otherWriterHolds, [{ taskId: 'other', sendId: '', reason: 'active_team' }]);
    db.exec('DELETE FROM workroom_automation');
    for (const state of ['paused', 'needs_review', 'closed', 'completed']) {
      db.prepare("INSERT INTO workroom_automation VALUES('other',?)").run(state);
      assert.deepEqual(readLegacyRows(path, ids).otherWriterHolds, []);
      db.exec('DELETE FROM workroom_automation');
    }
    db.prepare("INSERT INTO workroom_automation VALUES('other','future-team-state')").run();
    assert.equal(readLegacyRows(path, ids).otherWriterHolds[0].reason, 'unknown_team_state');
    db.exec('DELETE FROM workroom_automation');
    for (const state of ['queued','planning','working']) {
      db.prepare('INSERT INTO workroom_flow VALUES(?,?,?)').run('other', state, 'pending-send');
      assert.equal(readLegacyRows(path, ids).otherWriterHolds[0].reason, 'pending_intake');
      db.exec('DELETE FROM workroom_flow');
    }
    db.prepare("INSERT INTO workroom_flow VALUES(?,'working',?)").run(s.targets[0].taskId, ids[0]);
    assert.deepEqual(readLegacyRows(path, ids).otherWriterHolds, []);
    db.exec("UPDATE workroom_flow SET state='future-flow-state'");
    assert.equal(readLegacyRows(path, ids).otherWriterHolds[0].reason, 'unknown_intake_state');
    db.exec("UPDATE workroom_flow SET state='working'");
    db.prepare("UPDATE workroom_flow SET taskId='different-card'").run();
    assert.equal(readLegacyRows(path, ids).otherWriterHolds[0].reason, 'pending_intake');
    db.exec('DELETE FROM workroom_flow');
    db.prepare("INSERT INTO workroom_sends VALUES('native-other','task','echo','rejected','plan','other')").run();
    db.prepare("INSERT INTO workroom_local_sessions VALUES('native-other')").run();
    assert.equal(readLegacyRows(path, ids).otherWriterHolds[0].reason, 'other_native_binding');
    db.exec("DELETE FROM workroom_local_sessions WHERE sendId='native-other'; UPDATE workroom_sends SET state='future-state' WHERE id='native-other'");
    assert.equal(readLegacyRows(path, ids).otherWriterHolds[0].reason, 'unknown_send_state');
    db.exec("DELETE FROM workroom_sends WHERE id='native-other'");
    db.exec("CREATE TABLE workroom_dispatch_gate(id INTEGER,state TEXT,generation INTEGER,holder TEXT); INSERT INTO workroom_dispatch_gate VALUES(1,'paused',1,'fixture-owner'); CREATE TABLE workroom_dispatch_admissions(id TEXT,state TEXT); INSERT INTO workroom_dispatch_admissions VALUES('pending','admitted');");
    assert.equal(readLegacyRows(path, ids).otherWriterHolds[0].reason, 'pending_dispatch_admission');
    db.exec("UPDATE workroom_dispatch_admissions SET state='finished'");
    assert.deepEqual(readLegacyRows(path, ids).otherWriterHolds, []);
    db.exec('DROP TABLE workroom_dispatch_gate');
    assert.throws(() => readLegacyRows(path, ids), /maintenance schema is incomplete/);
    db.exec('DROP TABLE workroom_dispatch_admissions');
    db.prepare("UPDATE workroom_sends SET payload='edited' WHERE id=?").run(ids[0]);
    const second = readLegacyRows(path, ids);
    assert.notEqual(first.targets[0].fingerprint, second.targets[0].fingerprint);
    assert.notEqual(first.boardSha256, second.boardSha256);
    db.prepare("INSERT INTO workroom_sends VALUES('extra','task','echo','accepted','work','new')").run();
    assert.deepEqual(readLegacyRows(path, ids).otherWorkSendIds, ['extra']);
    db.prepare('INSERT INTO workroom_local_sessions VALUES(?)').run(ids[0]);
    assert.equal(readLegacyRows(path, ids).targets[0].nativeBound, true);
    db.exec('DROP TABLE workroom_automation');
    assert.throws(() => readLegacyRows(path, ids), /workroom_automation/);
    db.close();
  } finally { await rm(dir, { recursive: true, force: true }); }
});

test('installation and hardware fingerprint distinguishes same-named hosts without exposing raw identifiers', () => {
  const identity = { windowsMachineGuid: 'a32f61a0-5919-4094-a74e-ce5e2ac4516b', hardwareUuid: '4cb6a315-fc41-4a40-b298-ab308c34ac9a' };
  const hash = legacyMachineIdentity(identity);
  assert.match(hash, /^[a-f0-9]{64}$/);
  assert.equal(legacyMachineIdentity(Object.fromEntries(Object.entries(identity).map(([k,v]) => [k,v.toUpperCase()]))), hash);
  assert.notEqual(legacyMachineIdentity({ ...identity, windowsMachineGuid: 'b32f61a0-5919-4094-a74e-ce5e2ac4516b' }), hash);
  assert.notEqual(legacyMachineIdentity({ ...identity, hardwareUuid: '5cb6a315-fc41-4a40-b298-ab308c34ac9a' }), hash);
  for (const bad of [undefined, '', 'SYNTHETIC', '00000000-0000-0000-0000-000000000000', 'ffffffff-ffff-ffff-ffff-ffffffffffff']) {
    assert.throws(() => legacyMachineIdentity({ ...identity, hardwareUuid: bad }), /identity/);
    assert.throws(() => legacyMachineIdentity({ ...identity, windowsMachineGuid: bad }), /identity/);
  }
});

test('hostname-only legacy plans and snapshots without activity coverage cannot qualify', () => {
  const s = snapshot(), plan = makeLegacyRecoveryPlan(s);
  assert.equal(plan.schema, 'mesh/legacy-recovery-plan/v2');
  assert.throws(() => makeLegacyRecoveryPlan({ ...s, machineIdentity: undefined }));
  assert.throws(() => makeLegacyRecoveryPlan({ ...s, otherWriterHolds: undefined }));
  const { planHash, ...old } = plan; old.schema = 'mesh/legacy-recovery-plan/v1';
  assert.throws(() => assessLegacyRecovery({ ...old, planHash: legacyRecoveryFingerprint(old) }, s), /identity changed/);
});
