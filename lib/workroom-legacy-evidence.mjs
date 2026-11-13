import {createHash,randomUUID} from 'node:crypto';
import {isAbsolute} from 'node:path';
import {assertPcRecovery} from './pc-recovery-evidence.mjs';

const sha = value => createHash('sha256').update(value).digest('hex');
const canonical = value => JSON.stringify(value, (_, item) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b))) : item);
const id = value => typeof value === 'string' && /^[A-Za-z0-9_-]{1,100}$/.test(value);
const digest = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const time = value => typeof value === 'string' && Number.isFinite(Date.parse(value));
const same = (a, b) => canonical(a) === canonical(b);
export const legacyRecoveryFingerprint = value => sha(canonical(value));

export function validateLegacyRecoverySnapshot(snapshot) {
  if (!snapshot || !isAbsolute(snapshot.workspace || '') || !isAbsolute(snapshot.databasePath || '') ||
      !digest(snapshot.databaseIdentity) || !digest(snapshot.boardSha256) || !Number.isSafeInteger(snapshot.taskCount) || snapshot.taskCount < 1 ||
      !id(snapshot.host) || !time(snapshot.bootedAt) || !time(snapshot.observedAt) ||
      Date.parse(snapshot.bootedAt) > Date.parse(snapshot.observedAt) ||
      !snapshot.sources || Object.keys(snapshot.sources).length < 4 ||
      !Object.values(snapshot.sources).every(digest) || !Array.isArray(snapshot.targets) || snapshot.targets.length !== 8 ||
      new Set(snapshot.targets.map(t => t.sendId)).size !== 8 ||
      snapshot.targets.some(t => !id(t.sendId) || !id(t.taskId) || !['echo', 'dsh'].includes(t.agentId) ||
        !digest(t.fingerprint) || t.state !== 'accepted' || t.phase !== 'work' || t.nativeBound !== false) ||
      !Array.isArray(snapshot.otherWorkSendIds)) throw Error('Invalid exact-eight legacy recovery snapshot.');
}

export function makeLegacyRecoveryPlan(snapshot) {
  validateLegacyRecoverySnapshot(snapshot);
  if (snapshot.otherWorkSendIds.length) throw Error('Other work sends require separate reconciliation.');
  const plan = {
    schema: 'mesh/legacy-recovery-plan/v1', recoveryId: randomUUID(), preparedAt: snapshot.observedAt,
    workspace: snapshot.workspace, databasePath: snapshot.databasePath, databaseIdentity: snapshot.databaseIdentity,
    boardSha256: snapshot.boardSha256, taskCount: snapshot.taskCount, host: snapshot.host,
    baselineBoot: snapshot.bootedAt, sources: structuredClone(snapshot.sources),
    targets: structuredClone(snapshot.targets).sort((a, b) => a.sendId.localeCompare(b.sendId)),
    disposition: 'historical_outcome_unknown',
  };
  return { ...plan, planHash: sha(canonical(plan)) };
}

export function assessLegacyRecovery(plan, observation) {
  const { planHash, ...body } = plan || {};
  if (!digest(planHash) || sha(canonical(body)) !== planHash || body.schema !== 'mesh/legacy-recovery-plan/v1' ||
      !id(body.recoveryId) || !time(body.preparedAt) || body.disposition !== 'historical_outcome_unknown') {
    throw Error('Recovery plan identity changed.');
  }
  validateLegacyRecoverySnapshot({ ...body, observedAt: body.preparedAt, bootedAt: body.baselineBoot, otherWorkSendIds: [] });
  validateLegacyRecoverySnapshot(observation);
  const reasons = [];
  if (observation.host !== body.host) reasons.push('host_changed');
  if (observation.workspace !== body.workspace || observation.databasePath !== body.databasePath ||
      observation.databaseIdentity !== body.databaseIdentity) reasons.push('workspace_or_database_changed');
  if (!same(observation.sources, body.sources)) reasons.push('source_changed');
  if (observation.boardSha256 !== body.boardSha256 || observation.taskCount !== body.taskCount) reasons.push('saved_board_changed');
  if (!same([...observation.targets].sort((a, b) => a.sendId.localeCompare(b.sendId)), body.targets)) reasons.push('legacy_send_changed');
  if (observation.otherWorkSendIds.length) reasons.push('other_work_requires_reconciliation');
  if (Date.parse(observation.observedAt) < Date.parse(body.preparedAt)) reasons.push('observation_predates_plan');
  if (Date.parse(observation.bootedAt) <= Date.parse(body.preparedAt)) reasons.push('later_pc_boot_not_verified');
  let pcCustody = null;
  if (!reasons.length) {
    const pc = value => ({ schema: 'mesh-pc-recovery/v1', taskCount: value.taskCount,
      bootTime: value.bootedAt || value.baselineBoot, machineSha256: sha(value.host),
      boardSha256: value.boardSha256, holdsSha256: sha(canonical([...value.targets].sort((a, b) => a.sendId.localeCompare(b.sendId)))),
      sourceSha256: sha(canonical(value.sources)) });
    pcCustody = assertPcRecovery(pc(body), pc(observation));
  }
  return {
    schema: 'mesh/legacy-recovery-assessment/v1', planHash, observedAt: observation.observedAt,
    status: reasons.length ? 'blocked' : 'ready_for_operator_review', reasons, targetCount: 8,
    canRelease: false, disposition: 'historical_outcome_unknown', pcCustody,
    remainingGates: ['Reviewed live-maintenance authorization', 'Verified covered writer boundary and replay fences',
      'Exact owner recovery record and guarded durable adjudication; this assessment cannot clear a hold'],
  };
}

// Callers that write must hold their existing BEGIN IMMEDIATE transaction.
export function captureLegacyRecoveryRows(db, sendIds) {
  if (!Array.isArray(sendIds) || sendIds.length !== 8 || new Set(sendIds).size !== 8 || !sendIds.every(id)) {
    throw Error('Exactly eight original send IDs are required.');
  }
    const rows = sendIds.map(sendId => {
      const row = db.prepare('SELECT * FROM workroom_sends WHERE id=?').get(sendId);
      if (!row) throw Error('An original legacy send is missing.');
      const nativeBound = Boolean(db.prepare('SELECT sendId FROM workroom_local_sessions WHERE sendId=?').get(sendId));
      return { sendId, taskId: row.taskId, agentId: row.agentId, state: row.state, phase: row.phase,
        nativeBound, fingerprint: sha(canonical(row)) };
    });
    const selected = new Set(sendIds);
    const otherWorkSendIds = db.prepare("SELECT id FROM workroom_sends WHERE phase='work' AND state IN ('prepared','unknown','accepted') ORDER BY id")
      .all().map(row => row.id).filter(sendId => !selected.has(sendId));
    const board = {};
    for (const { name } of db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").all()) {
      const table = name.replaceAll('"', '""');
      board[name] = db.prepare(`SELECT * FROM "${table}"`).all().map(canonical).sort();
    }
    const boardSha256 = sha(canonical(board));
    const taskCount = db.prepare('SELECT COUNT(*) AS count FROM tasks').get().count;
    return { targets: rows, otherWorkSendIds, boardSha256, taskCount };
}

