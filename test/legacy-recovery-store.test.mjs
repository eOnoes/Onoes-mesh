import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { openTaskStore } from '../lib/task-store.mjs';
import { writerQuiescenceBlockers } from '../lib/workroom-claim-policy.mjs';
import { issueLegacyRecoveryPermit, isLegacyRecovered } from '../lib/workroom-legacy-recovery.mjs';
import { makeLegacyRecoveryPlan, readLegacyRows, legacyRecoveryFingerprint as hash } from '../integrations/legacy-recovery-plan.mjs';

const ledgerCount = (db, name) => db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name=?").get(name)
  ? db.prepare(`SELECT COUNT(*) AS n FROM "${name.replaceAll('"', '""')}"`).get().n : 0;

function fixture() {
  const dir = mkdtempSync(join(tmpdir(), 'mesh-legacy-store-')), path = join(dir, 'tasks.sqlite');
  let store = openTaskStore(path);
  const old = store.create({ title: 'Historical work', description: 'Preserve this original request.' });
  const next = store.create({ title: 'New idea', description: 'Synthetic fixture; no live dispatch.' });
  const db = new DatabaseSync(path), ids = [];
  db.prepare('UPDATE tasks SET createdAt=? WHERE id=?').run('2020-01-01T00:00:00Z', next.id);
  for (let n = 0; n < 8; n++) {
    const id = 'legacy-' + n; ids.push(id);
    db.prepare(`INSERT INTO workroom_sends(id,taskId,agentId,conversationId,text,fingerprint,state,at,payload,basis,phase)
      VALUES(?,?,?,?,?,?,'accepted',?,?,?,'work')`).run(id, old.id, n < 6 ? 'echo' : 'dsh', 'original-session',
    'Original request', 'a'.repeat(64), '2026-01-01T00:00:00Z', 'Frozen original payload', '{}');
  }
  const file = statSync(path, { bigint: true });
  const databaseIdentity = hash({ device: String(file.dev), file: String(file.ino), created: String(file.birthtimeNs) });
  const sources = Object.fromEntries(['mesh', 'relay', 'hermes', 'dsh'].map(k => [k, 'b'.repeat(64)]));
  const snapshot = () => ({ workspace: dir, databasePath: path, databaseIdentity, host: 'SYNTHETIC',
    sources, bootedAt: new Date(Date.now() - 60000).toISOString(), observedAt: new Date().toISOString(), ...readLegacyRows(path, ids) });
  const plan = makeLegacyRecoveryPlan({ ...snapshot(), bootedAt: '2020-01-01T00:00:00Z', observedAt: new Date(Date.now() - 120000).toISOString() });
  let owner = { schema: 'mesh/legacy-recovery-authorization/v1', decision: 'apply_exact_eight', planHash: plan.planHash, recordHash: 'c'.repeat(64) };
  const boundary = (_plan, observation) => ({ schema: 'mesh/legacy-local-fence/v1', planHash: plan.planHash,
    host: observation.host, bootedAt: observation.bootedAt, sources: observation.sources,
    dispatchPaused: true, coveredLocalWriters: true, activeWriterCount: 0, replayPrevented: true, uncoveredWriters: [] });
  const options = () => ({ plan, authorize: () => owner, observe: snapshot, verifyFence: boundary });
  return { dir, path, db, old, next, ids, plan, snapshot, boundary, options,
    get store() { return store; }, setOwner(value) { owner = value; },
    reopen() { store.close(); store = openTaskStore(path); }, close() { db.close(); store.close(); } };
}

test('opening and reading an older database never creates recovery tables', () => {
  const f = fixture();
  try {
    f.db.exec('DROP TABLE IF EXISTS workroom_legacy_recovery_sends; DROP TABLE IF EXISTS workroom_legacy_recoveries;');
    const before = f.db.prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").all();
    f.reopen();
    assert.equal(writerQuiescenceBlockers(f.store.workroom.list()).length, 8);
    assert.deepEqual(f.db.prepare("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").all(), before);
  } finally { f.close(); }
});

test('only an authentic exact-live permit atomically adjudicates eight holds; history survives reopen', async () => {
  const f = fixture();
  try {
    const original = f.db.prepare('SELECT * FROM workroom_sends ORDER BY id').all();
    const task = f.store.get(f.old.id);
    assert.equal(writerQuiescenceBlockers(f.store.workroom.list()).length, 8);
    const permit = await issueLegacyRecoveryPermit(f.options());
    await assert.rejects(f.store.workroom.legacyRecovery.commit({ ...permit }), /authentic/);
    const receipt = await f.store.workroom.legacyRecovery.commit(permit);
    assert.equal(receipt.duplicate, false);
    assert.equal(writerQuiescenceBlockers(f.store.workroom.list()).length, 0);
    assert.deepEqual(f.db.prepare('SELECT * FROM workroom_sends ORDER BY id').all(), original);
    assert.deepEqual(f.store.get(f.old.id), task);
    const message = f.store.workroom.get(f.old.id).messages[0];
    assert.equal(message.legacyRecovery.workerRetirementEstablished, false);
    assert.equal(message.nativeLocal, undefined);
    assert.equal(isLegacyRecovered(message), true);
    assert.equal(isLegacyRecovered(structuredClone(message)), false);
    assert.equal(f.store.workroom.canApproveHandoff(f.old.id, message.id), false);
    await assert.rejects(Promise.resolve().then(() => f.store.workroom.reserve(f.old.id,
      { id: message.id, agentId: message.agentId, conversationId: message.conversationId, text: message.text }, 'work')), /recovered/);
    assert.equal((await f.store.workroom.legacyRecovery.commit(permit)).duplicate, true);
    assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM workroom_events WHERE kind='legacy_recovery_recorded'").get().n, 8);
    f.reopen();
    assert.equal(writerQuiescenceBlockers(f.store.workroom.list()).length, 0);
    const next = f.store.workroom.get(f.next.id);
    const claim = f.store.workroom.flow.claim(next.id, { revision: 0, taskRevision: next.revision,
      briefRevision: next.workroom.revision, progressRevision: next.progress.revision });
    assert.ok(claim.claim.claimId);
    assert.equal(writerQuiescenceBlockers(f.store.workroom.list()).length, 0);
  } finally { f.close(); }
});

test('preparation approval, absent fences, uncovered writers and stale/same-boot observations cannot mint permits', async () => {
  const f = fixture();
  try {
    const base = f.options();
    const cases = [
      { authorize: () => ({ ...base.authorize(), decision: 'prepare_and_test' }) },
      { verifyFence: (_p, o) => ({ ...f.boundary(_p, o), replayPrevented: false }) },
      { verifyFence: (_p, o) => ({ ...f.boundary(_p, o), uncoveredWriters: ['unverified'] }) },
      { verifyFence: (_p, o) => ({ ...f.boundary(_p, o), activeWriterCount: 1 }) },
      { observe: () => ({ ...f.snapshot(), bootedAt: f.plan.baselineBoot }) },
      { observe: () => ({ ...f.snapshot(), observedAt: new Date(Date.now() - 60000).toISOString() }) },
    ];
    for (const change of cases) await assert.rejects(issueLegacyRecoveryPermit({ ...base, ...change }));
    assert.equal(writerQuiescenceBlockers(f.store.workroom.list()).length, 8);
    assert.equal(ledgerCount(f.db, 'workroom_legacy_recoveries'), 0);
  } finally { f.close(); }
});

test('revoked authorization or a board write after inspection rolls back the whole recovery', async () => {
  const f = fixture();
  try {
    const permit = await issueLegacyRecoveryPermit(f.options());
    f.setOwner(null);
    await assert.rejects(f.store.workroom.legacyRecovery.commit(permit), /authorization/);
    assert.equal(writerQuiescenceBlockers(f.store.workroom.list()).length, 8);
  } finally { f.close(); }
  const g = fixture();
  try {
    let calls = 0;
    const opts = { ...g.options(), verifyFence: (plan, observation) => {
      const proof = g.boundary(plan, observation);
      if (++calls === 2) g.db.prepare("UPDATE tasks SET title='Concurrent edit' WHERE id=?").run(g.old.id);
      return proof;
    } };
    const permit = await issueLegacyRecoveryPermit(opts);
    await assert.rejects(g.store.workroom.legacyRecovery.commit(permit), /changed before recovery commit/);
    assert.equal(ledgerCount(g.db, 'workroom_legacy_recoveries'), 0);
    assert.equal(ledgerCount(g.db, 'workroom_legacy_recovery_sends'), 0);
  } finally { g.close(); }
});

test('new work, tampered projections and modified original receipts stay protected after recovery', async () => {
  const f = fixture();
  try {
    await f.store.workroom.legacyRecovery.commit(await issueLegacyRecoveryPermit(f.options()));
    const message = f.store.workroom.get(f.old.id).messages[0];
    const originalInput = structuredClone(message);
    const independentlyProjected = f.store.workroom.legacyRecovery.project(f.old.id, originalInput);
    originalInput.id = f.ids[1];
    const copied = structuredClone(message);
    assert.equal(writerQuiescenceBlockers([{ id: f.old.id, messages: [copied] }]).length, 1);
    message.legacyRecovery.state = 'forged';
    assert.equal(isLegacyRecovered(message), false);
    f.db.prepare("UPDATE workroom_sends SET payload='Changed later' WHERE id=?").run(f.ids[0]);
    assert.equal(isLegacyRecovered(independentlyProjected), false);
    assert.equal(writerQuiescenceBlockers(f.store.workroom.list()).length, 1);
    assert.equal(isLegacyRecovered(f.store.workroom.get(f.old.id).messages[0]), false);
    f.db.prepare(`INSERT INTO workroom_sends(id,taskId,agentId,conversationId,text,fingerprint,state,at,payload,basis,phase)
      VALUES('new-writer',?,'echo','session','New request',?,'accepted',?,'new','{}','work')`)
      .run(f.next.id, 'e'.repeat(64), new Date().toISOString());
    assert.equal(writerQuiescenceBlockers(f.store.workroom.list()).length, 2);
    assert.equal(writerQuiescenceBlockers([{ id: 'new', messages: [{ id: 'new-send', phase: 'work', state: 'accepted',
      legacyRecovery: { state: 'owner_recovered_unknown', workerRetirementEstablished: true } }] }]).length, 1);
    assert.equal(writerQuiescenceBlockers([{ id: 'active', automation: { state: 'active' }, messages: [] }]).length, 1);
  } finally { f.close(); }
});

test('a failure midway through all eight records rolls back evidence, references and events', async () => {
  const f = fixture();
  try {
    const permit = await issueLegacyRecoveryPermit(f.options());
    f.db.exec(`CREATE TRIGGER reject_partial BEFORE INSERT ON workroom_events
      WHEN NEW.kind='legacy_recovery_recorded' AND NEW.detail LIKE '%legacy-4%'
      BEGIN SELECT RAISE(ABORT,'synthetic mid-write failure'); END;`);
    await assert.rejects(f.store.workroom.legacyRecovery.commit(permit), /mid-write failure/);
    assert.equal(ledgerCount(f.db, 'workroom_legacy_recoveries'), 0);
    assert.equal(ledgerCount(f.db, 'workroom_legacy_recovery_sends'), 0);
    assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM workroom_events WHERE kind='legacy_recovery_recorded'").get().n, 0);
    assert.equal(writerQuiescenceBlockers(f.store.workroom.list()).length, 8);
  } finally { f.close(); }
});

test('a permit cannot be moved to another board/database', async () => {
  const f = fixture(), g = fixture();
  try {
    const permit = await issueLegacyRecoveryPermit(f.options());
    await assert.rejects(g.store.workroom.legacyRecovery.commit(permit), /another database/);
    assert.equal(writerQuiescenceBlockers(g.store.workroom.list()).length, 8);
  } finally { f.close(); g.close(); }
});
