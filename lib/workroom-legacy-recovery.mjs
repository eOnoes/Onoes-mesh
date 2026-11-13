import { resolve } from 'node:path';
import { statSync } from 'node:fs';
import { assessLegacyRecovery, captureLegacyRecoveryRows, legacyRecoveryFingerprint as hash } from './workroom-legacy-evidence.mjs';

const permits = new WeakMap();
const projections = new WeakMap();
const same = (a, b) => hash(a) === hash(b);
const sha = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const pathKey = value => resolve(value).toLowerCase();

function approval(value, plan, observation) {
  if (!value || value.schema !== 'mesh/legacy-recovery-authorization/v1' ||
      value.decision !== 'apply_exact_eight' || value.planHash !== plan.planHash || !sha(value.recordHash) ||
      typeof value.host !== 'string' || !value.host || !Number.isFinite(Date.parse(value.bootedAt)) ||
      (observation && (value.host !== observation.host || value.bootedAt !== observation.bootedAt))) {
    throw Error('Exact live recovery authorization is missing. Preparation approval cannot release holds.');
  }
}
function fence(value, plan, observation) {
  if (!value || value.schema !== 'mesh/legacy-local-fence/v1' || value.planHash !== plan.planHash ||
      value.host !== observation.host || value.bootedAt !== observation.bootedAt ||
      value.machineIdentity !== observation.machineIdentity ||
      !same(value.sources, observation.sources) || value.dispatchPaused !== true ||
      value.coveredLocalWriters !== true || value.activeWriterCount !== 0 || value.replayPrevented !== true ||
      !Array.isArray(value.uncoveredWriters) || value.uncoveredWriters.length) {
    throw Error('Covered writer boundary and replay fences are not verified.');
  }
}
function fresh(observation) {
  const age = Date.now() - Date.parse(observation.observedAt);
  if (!Number.isFinite(age) || age < -1000 || age > 30000) throw Error('Recovery observation is stale.');
}

// Trusted operator code supplies these capabilities. No HTTP route or default
// production provider exists; caller-supplied JSON cannot manufacture a permit.
export async function issueLegacyRecoveryPermit({ plan, authorize, observe, verifyFence, commitGuard }) {
  if (![authorize, observe, verifyFence, commitGuard].every(fn => typeof fn === 'function') ||
      commitGuard.constructor?.name === 'AsyncFunction') throw Error('Trusted recovery providers and a synchronous commit guard are required.');
  plan = structuredClone(plan);
  const owner = await authorize(plan.planHash); approval(owner, plan);
  const observation = await observe(plan);
  approval(owner, plan, observation);
  const result = assessLegacyRecovery(plan, observation);
  if (result.status !== 'ready_for_operator_review') throw Error('Recovery remains blocked: ' + result.reasons.join(', '));
  fresh(observation);
  const boundary = await verifyFence(plan, observation); fence(boundary, plan, observation);
  if (!same(await authorize(plan.planHash), owner)) throw Error('Recovery authorization changed.');
  const permit = Object.freeze({});
  permits.set(permit, { plan, owner: structuredClone(owner), authorize, observe, verifyFence, commitGuard });
  return permit;
}

export function isLegacyRecovered(message) {
  const proof = projections.get(message);
  try { return Boolean(proof && proof.signature === hash(message) && proof.current()); }
  catch { return false; }
}

export function createLegacyRecoveryStore(db) {
  const has = name => Boolean(db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name=?").get(name));
  function initialize() {
    db.exec(`CREATE TABLE IF NOT EXISTS workroom_legacy_recoveries(
    recoveryId TEXT PRIMARY KEY,planHash TEXT NOT NULL UNIQUE,ownerHash TEXT NOT NULL,
    proofHash TEXT NOT NULL,evidence TEXT NOT NULL,recordedAt TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS workroom_legacy_recovery_sends(
    sendId TEXT PRIMARY KEY REFERENCES workroom_sends(id),taskId TEXT NOT NULL REFERENCES tasks(id),
    recoveryId TEXT NOT NULL REFERENCES workroom_legacy_recoveries(recoveryId),fingerprint TEXT NOT NULL);`);
  }
  function read(taskId, sendId) {
    if (!has('workroom_legacy_recoveries') || !has('workroom_legacy_recovery_sends')) return null;
    const row = db.prepare(`SELECT s.fingerprint,r.* FROM workroom_legacy_recovery_sends s
      JOIN workroom_legacy_recoveries r USING(recoveryId) WHERE s.taskId=? AND s.sendId=?`).get(taskId, sendId);
    if (!row) return null;
    try {
      const original = db.prepare('SELECT * FROM workroom_sends WHERE taskId=? AND id=?').get(taskId, sendId);
      if (!original || original.state !== 'accepted' || original.phase !== 'work' || hash(original) !== row.fingerprint ||
          db.prepare('SELECT sendId FROM workroom_local_sessions WHERE sendId=?').get(sendId)) return null;
      const evidence = JSON.parse(row.evidence);
      if (hash(evidence) !== row.proofHash || evidence.plan.planHash !== row.planHash ||
          evidence.owner.recordHash !== row.ownerHash || evidence.plan.recoveryId !== row.recoveryId ||
          !evidence.plan.targets.some(t => t.sendId === sendId && t.taskId === taskId && t.fingerprint === row.fingerprint)) return null;
      approval(evidence.owner, evidence.plan, evidence.observation);
      fence(evidence.boundary, evidence.plan, evidence.observation);
      if (assessLegacyRecovery(evidence.plan, evidence.observation).status !== 'ready_for_operator_review') return null;
      return { recoveryId: row.recoveryId, planHash: row.planHash, recordedAt: row.recordedAt,
        state: 'owner_recovered_unknown', workerRetirementEstablished: false };
    } catch { return null; }
  }
  function project(taskId, message) {
    const record = read(taskId, message.id);
    if (!record) return message;
    const original = db.prepare('SELECT * FROM workroom_sends WHERE taskId=? AND id=?').get(taskId, message.id);
    if (['id', 'agentId', 'conversationId', 'text', 'state', 'phase'].some(k => message[k] !== original[k])) return message;
    const result = { ...message, legacyRecovery: record };
    const sendId = message.id;
    projections.set(result, { signature: hash(result), current: () => Boolean(read(taskId, sendId)) });
    return result;
  }
  async function commit(permit) {
    const capability = permits.get(permit);
    if (!capability) throw Error('An authentic recovery permit is required.');
    const { plan, owner, authorize, observe, verifyFence, commitGuard } = capability;
    const file = db.prepare('PRAGMA database_list').all().find(item => item.name === 'main')?.file;
    if (!file || pathKey(file) !== pathKey(plan.databasePath)) throw Error('Recovery permit belongs to another database.');
    const identity = statSync(file, { bigint: true });
    if (hash({ device: String(identity.dev), file: String(identity.ino), created: String(identity.birthtimeNs) }) !== plan.databaseIdentity) {
      throw Error('Recovery database file identity changed.');
    }
    const currentOwner = await authorize(plan.planHash); approval(currentOwner, plan);
    if (!same(currentOwner, owner)) throw Error('Recovery authorization changed.');
    const existing = has('workroom_legacy_recoveries')
      ? db.prepare('SELECT * FROM workroom_legacy_recoveries WHERE planHash=?').get(plan.planHash) : null;
    if (existing) {
      if (existing.ownerHash !== owner.recordHash || !plan.targets.every(t => read(t.taskId, t.sendId))) throw Error('Saved recovery receipt is inconsistent.');
      return { recoveryId: existing.recoveryId, planHash: plan.planHash, duplicate: true, disposition: 'historical_outcome_unknown' };
    }
    const observation = await observe(plan);
    approval(owner, plan, observation);
    const result = assessLegacyRecovery(plan, observation);
    if (result.status !== 'ready_for_operator_review') throw Error('Recovery evidence changed: ' + result.reasons.join(', '));
    fresh(observation);
    const boundary = await verifyFence(plan, observation); fence(boundary, plan, observation);
    if (!same(await authorize(plan.planHash), owner)) throw Error('Recovery authorization changed.');
    const evidence = { plan, owner, observation, boundary };
    db.exec('BEGIN IMMEDIATE;');
    try {
      const current = captureLegacyRecoveryRows(db, plan.targets.map(t => t.sendId));
      if (!same(current.targets.sort((a,b) => a.sendId.localeCompare(b.sendId)), plan.targets) ||
          current.otherWorkSendIds.length || current.otherWriterHolds.length || current.boardSha256 !== observation.boardSha256 || current.taskCount !== observation.taskCount) {
        throw Error('Saved board changed before recovery commit.');
      }
      initialize();
      const at = new Date().toISOString();
      db.prepare('INSERT INTO workroom_legacy_recoveries VALUES(?,?,?,?,?,?)')
        .run(plan.recoveryId, plan.planHash, owner.recordHash, hash(evidence), JSON.stringify(evidence), at);
      for (const target of plan.targets) {
        db.prepare('INSERT INTO workroom_legacy_recovery_sends VALUES(?,?,?,?)').run(target.sendId, target.taskId, plan.recoveryId, target.fingerprint);
        db.prepare('INSERT INTO workroom_events(taskId,kind,detail,at) VALUES(?,?,?,?)')
          .run(target.taskId, 'legacy_recovery_recorded', `Send ${target.sendId}: owner recovered the legacy hold; original work outcome remains unknown.`, at);
      }
      // Final authorization boundary: no await may occur inside this transaction.
      // The provider must hold dispatch exclusion through this check and COMMIT.
      const final = commitGuard(structuredClone(plan), structuredClone(observation));
      const asynchronous = [final, final?.owner, final?.boundary].filter(value => typeof value?.then === 'function');
      if (asynchronous.length) {
        for (const value of asynchronous) Promise.resolve(value).catch(() => {});
        throw Error('The commit guard must be synchronous.');
      }
      approval(final?.owner, plan, observation);
      if (!same(final.owner, owner)) throw Error('Recovery authorization changed before commit.');
      fence(final.boundary, plan, observation);
      fresh(observation);
      db.exec('COMMIT;');
      return { recoveryId: plan.recoveryId, planHash: plan.planHash, duplicate: false, disposition: 'historical_outcome_unknown' };
    } catch (error) { db.exec('ROLLBACK;'); throw error; }
  }
  return Object.freeze({ read, project, commit });
}
