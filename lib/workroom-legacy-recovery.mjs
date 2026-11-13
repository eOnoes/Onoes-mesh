import { resolve } from 'node:path';
import { statSync } from 'node:fs';
import { assessLegacyRecovery, captureLegacyRecoveryRows, legacyRecoveryFingerprint as hash } from '../integrations/legacy-recovery-plan.mjs';

const permits = new WeakMap();
const projections = new WeakMap();
const same = (a, b) => hash(a) === hash(b);
const sha = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const pathKey = value => resolve(value).toLowerCase();

function approval(value, plan) {
  if (!value || value.schema !== 'mesh/legacy-recovery-authorization/v1' ||
      value.decision !== 'apply_exact_eight' || value.planHash !== plan.planHash || !sha(value.recordHash)) {
    throw Error('Exact live recovery authorization is missing. Preparation approval cannot release holds.');
  }
}
function fence(value, plan, observation) {
  if (!value || value.schema !== 'mesh/legacy-local-fence/v1' || value.planHash !== plan.planHash ||
      value.host !== observation.host || value.bootedAt !== observation.bootedAt ||
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
export async function issueLegacyRecoveryPermit({ plan, authorize, observe, verifyFence }) {
  if (![authorize, observe, verifyFence].every(fn => typeof fn === 'function')) throw Error('Trusted recovery providers are required.');
  plan = structuredClone(plan);
  const owner = await authorize(plan.planHash); approval(owner, plan);
  const observation = await observe(plan);
  const result = assessLegacyRecovery(plan, observation);
  if (result.status !== 'ready_for_operator_review') throw Error('Recovery remains blocked: ' + result.reasons.join(', '));
  fresh(observation);
  const boundary = await verifyFence(plan, observation); fence(boundary, plan, observation);
  if (!same(await authorize(plan.planHash), owner)) throw Error('Recovery authorization changed.');
  const permit = Object.freeze({});
  permits.set(permit, { plan, owner: structuredClone(owner), authorize, observe, verifyFence });
  return permit;
}

export function isLegacyRecovered(message) {
  const proof = projections.get(message);
  try { return Boolean(proof && proof.signature === hash(message) && proof.current()); }
  catch { return false; }
}

export function createLegacyRecoveryStore(db) {
  db.exec(`CREATE TABLE IF NOT EXISTS workroom_legacy_recoveries(
    recoveryId TEXT PRIMARY KEY,planHash TEXT NOT NULL UNIQUE,ownerHash TEXT NOT NULL,
    proofHash TEXT NOT NULL,evidence TEXT NOT NULL,recordedAt TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS workroom_legacy_recovery_sends(
    sendId TEXT PRIMARY KEY REFERENCES workroom_sends(id),taskId TEXT NOT NULL REFERENCES tasks(id),
    recoveryId TEXT NOT NULL REFERENCES workroom_legacy_recoveries(recoveryId),fingerprint TEXT NOT NULL);`);
  function read(taskId, sendId) {
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
      approval(evidence.owner, evidence.plan);
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
    const { plan, owner, authorize, observe, verifyFence } = capability;
    const file = db.prepare('PRAGMA database_list').all().find(item => item.name === 'main')?.file;
    if (!file || pathKey(file) !== pathKey(plan.databasePath)) throw Error('Recovery permit belongs to another database.');
    const identity = statSync(file, { bigint: true });
    if (hash({ device: String(identity.dev), file: String(identity.ino), created: String(identity.birthtimeNs) }) !== plan.databaseIdentity) {
      throw Error('Recovery database file identity changed.');
    }
    const currentOwner = await authorize(plan.planHash); approval(currentOwner, plan);
    if (!same(currentOwner, owner)) throw Error('Recovery authorization changed.');
    const existing = db.prepare('SELECT * FROM workroom_legacy_recoveries WHERE planHash=?').get(plan.planHash);
    if (existing) {
      if (existing.ownerHash !== owner.recordHash || !plan.targets.every(t => read(t.taskId, t.sendId))) throw Error('Saved recovery receipt is inconsistent.');
      return { recoveryId: existing.recoveryId, planHash: plan.planHash, duplicate: true, disposition: 'historical_outcome_unknown' };
    }
    const observation = await observe(plan);
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
          current.otherWorkSendIds.length || current.boardSha256 !== observation.boardSha256 || current.taskCount !== observation.taskCount) {
        throw Error('Saved board changed before recovery commit.');
      }
      const at = new Date().toISOString();
      db.prepare('INSERT INTO workroom_legacy_recoveries VALUES(?,?,?,?,?,?)')
        .run(plan.recoveryId, plan.planHash, owner.recordHash, hash(evidence), JSON.stringify(evidence), at);
      for (const target of plan.targets) {
        db.prepare('INSERT INTO workroom_legacy_recovery_sends VALUES(?,?,?,?)').run(target.sendId, target.taskId, plan.recoveryId, target.fingerprint);
        db.prepare('INSERT INTO workroom_events(taskId,kind,detail,at) VALUES(?,?,?,?)')
          .run(target.taskId, 'legacy_recovery_recorded', `Send ${target.sendId}: owner recovered the legacy hold; original work outcome remains unknown.`, at);
      }
      db.exec('COMMIT;');
      return { recoveryId: plan.recoveryId, planHash: plan.planHash, duplicate: false, disposition: 'historical_outcome_unknown' };
    } catch (error) { db.exec('ROLLBACK;'); throw error; }
  }
  return Object.freeze({ read, project, commit });
}
