import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import {makeLegacyRecoveryPlan,assessLegacyRecovery} from '../lib/workroom-legacy-evidence.mjs';
import {readLegacyRows} from '../integrations/legacy-recovery-plan.mjs';

const snapshot = () => ({ workspace: resolve('synthetic-mesh'), databasePath: resolve('synthetic.sqlite'), databaseIdentity: 'd'.repeat(64), boardSha256: 'f'.repeat(64), taskCount: 14, host: 'SYNTHETIC',
  bootedAt: '2026-10-30T16:43:37.000Z', observedAt: '2026-11-13T03:00:00.000Z',
  sources: Object.fromEntries(['mesh', 'relay', 'hermes', 'dsh'].map(k => [k, 'a'.repeat(64)])),
  targets: Array.from({ length: 8 }, (_, n) => ({ taskId: 'task-' + n, sendId: 'send-' + n, agentId: n < 6 ? 'echo' : 'dsh',
    fingerprint: 'b'.repeat(64), state: 'accepted', phase: 'work', nativeBound: false })), otherWorkSendIds: [] });

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
    [{ databasePath: resolve('other.sqlite') }, 'workspace_or_database_changed'],
    [{ databaseIdentity: 'e'.repeat(64) }, 'workspace_or_database_changed'],
    [{ boardSha256: 'e'.repeat(64) }, 'saved_board_changed'],
    [{ taskCount: 15 }, 'saved_board_changed'],
    [{ sources: { ...s.sources, relay: 'c'.repeat(64) } }, 'source_changed'],
    [{ targets: s.targets.map((t, n) => n ? t : { ...t, fingerprint: 'c'.repeat(64) }) }, 'legacy_send_changed'],
    [{ otherWorkSendIds: ['new-writer'] }, 'other_work_requires_reconciliation'],
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
});

test('real SQLite reads preserve original records and detect payload edits and other work', async () => {
  const dir = await mkdtemp(join(tmpdir(), 'mesh-legacy-plan-'));
  try {
    const path = join(dir, 'tasks.sqlite'), db = new DatabaseSync(path);
    db.exec('CREATE TABLE tasks(id TEXT PRIMARY KEY); CREATE TABLE workroom_sends(id TEXT PRIMARY KEY,taskId TEXT,agentId TEXT,state TEXT,phase TEXT,payload TEXT); CREATE TABLE workroom_local_sessions(sendId TEXT);');
    const s = snapshot();
    for (const t of s.targets) {
      db.prepare('INSERT INTO tasks VALUES(?)').run(t.taskId);
      db.prepare('INSERT INTO workroom_sends VALUES(?,?,?,?,?,?)').run(t.sendId, t.taskId, t.agentId, t.state, t.phase, 'original');
    }
    const ids = s.targets.map(t => t.sendId), before = db.prepare('SELECT * FROM workroom_sends ORDER BY id').all();
    const first = readLegacyRows(path, ids);
    assert.deepEqual(db.prepare('SELECT * FROM workroom_sends ORDER BY id').all(), before);
    assert.equal(readLegacyRows(path, ids).boardSha256, first.boardSha256);
    db.prepare("UPDATE workroom_sends SET payload='edited' WHERE id=?").run(ids[0]);
    const second = readLegacyRows(path, ids);
    assert.notEqual(first.targets[0].fingerprint, second.targets[0].fingerprint);
    assert.notEqual(first.boardSha256, second.boardSha256);
    db.prepare("INSERT INTO workroom_sends VALUES('extra','task','echo','accepted','work','new')").run();
    assert.deepEqual(readLegacyRows(path, ids).otherWorkSendIds, ['extra']);
    db.prepare('INSERT INTO workroom_local_sessions VALUES(?)').run(ids[0]);
    assert.equal(readLegacyRows(path, ids).targets[0].nativeBound, true);
    db.close();
  } finally { await rm(dir, { recursive: true, force: true }); }
});
