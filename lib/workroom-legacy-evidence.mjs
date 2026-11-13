import {createHash,randomUUID} from 'node:crypto';
import {isAbsolute} from 'node:path';
import {assertPcRecovery} from './pc-recovery-evidence.mjs';
import {isUnresolvedWorkSend} from './workroom-writer-states.mjs';

const sha = value => createHash('sha256').update(value).digest('hex');
const canonical = value => JSON.stringify(value, (_, item) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b))) : item);
const id = value => typeof value === 'string' && /^[A-Za-z0-9_-]{1,100}$/.test(value);
const digest = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const time = value => typeof value === 'string' && Number.isFinite(Date.parse(value));
const same = (a, b) => canonical(a) === canonical(b);
export const legacyRecoveryFingerprint = value => sha(canonical(value));

export function legacyMachineIdentity({ windowsMachineGuid, hardwareUuid }) {
  const valid = value => typeof value === 'string' && /^[a-f0-9]{8}(-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(value) &&
    !/^(0{32}|f{32})$/i.test(value.replaceAll('-', ''));
  if (!valid(windowsMachineGuid) || !valid(hardwareUuid)) throw Error('Installation and hardware identity are required.');
  return legacyRecoveryFingerprint({ windowsMachineGuid: windowsMachineGuid.toLowerCase(), hardwareUuid: hardwareUuid.toLowerCase() });
}

export function validateLegacyRecoverySnapshot(snapshot) {
  if (!snapshot || !isAbsolute(snapshot.workspace || '') || !isAbsolute(snapshot.databasePath || '') ||
      !digest(snapshot.databaseIdentity) || !digest(snapshot.boardSha256) || !Number.isSafeInteger(snapshot.taskCount) || snapshot.taskCount < 1 ||
      !id(snapshot.host) || !digest(snapshot.machineIdentity) || !time(snapshot.bootedAt) || !time(snapshot.observedAt) ||
      Date.parse(snapshot.bootedAt) > Date.parse(snapshot.observedAt) ||
      !snapshot.sources || Object.keys(snapshot.sources).length < 4 ||
      !Object.values(snapshot.sources).every(digest) || !Array.isArray(snapshot.targets) || snapshot.targets.length !== 8 ||
      new Set(snapshot.targets.map(t => t.sendId)).size !== 8 ||
      snapshot.targets.some(t => !id(t.sendId) || !id(t.taskId) || !['echo', 'dsh'].includes(t.agentId) ||
        !digest(t.fingerprint) || t.state !== 'accepted' || t.phase !== 'work' || t.nativeBound !== false) ||
      !Array.isArray(snapshot.otherWorkSendIds) || !Array.isArray(snapshot.otherWriterHolds)) throw Error('Invalid exact-eight legacy recovery snapshot.');
}

export function makeLegacyRecoveryPlan(snapshot) {
  validateLegacyRecoverySnapshot(snapshot);
  if (snapshot.otherWorkSendIds.length) throw Error('Other work sends require separate reconciliation.');
  if (snapshot.otherWriterHolds.length) throw Error('Active teams or pending intake require separate reconciliation.');
  const plan = {
    schema: 'mesh/legacy-recovery-plan/v2', recoveryId: randomUUID(), preparedAt: snapshot.observedAt,
    workspace: snapshot.workspace, databasePath: snapshot.databasePath, databaseIdentity: snapshot.databaseIdentity,
    boardSha256: snapshot.boardSha256, taskCount: snapshot.taskCount, host: snapshot.host, machineIdentity: snapshot.machineIdentity,
    baselineBoot: snapshot.bootedAt, sources: structuredClone(snapshot.sources),
    targets: structuredClone(snapshot.targets).sort((a, b) => a.sendId.localeCompare(b.sendId)),
    disposition: 'historical_outcome_unknown',
  };
  return { ...plan, planHash: sha(canonical(plan)) };
}

export function assessLegacyRecovery(plan, observation) {
  const { planHash, ...body } = plan || {};
  if (!digest(planHash) || sha(canonical(body)) !== planHash || body.schema !== 'mesh/legacy-recovery-plan/v2' ||
      !id(body.recoveryId) || !time(body.preparedAt) || body.disposition !== 'historical_outcome_unknown') {
    throw Error('Recovery plan identity changed.');
  }
  validateLegacyRecoverySnapshot({ ...body, observedAt: body.preparedAt, bootedAt: body.baselineBoot, otherWorkSendIds: [], otherWriterHolds: [] });
  validateLegacyRecoverySnapshot(observation);
  const reasons = [];
  if (observation.host !== body.host) reasons.push('host_changed');
  if (observation.machineIdentity !== body.machineIdentity) reasons.push('machine_identity_changed');
  if (observation.workspace !== body.workspace || observation.databasePath !== body.databasePath ||
      observation.databaseIdentity !== body.databaseIdentity) reasons.push('workspace_or_database_changed');
  if (!same(observation.sources, body.sources)) reasons.push('source_changed');
  if (observation.boardSha256 !== body.boardSha256 || observation.taskCount !== body.taskCount) reasons.push('saved_board_changed');
  if (!same([...observation.targets].sort((a, b) => a.sendId.localeCompare(b.sendId)), body.targets)) reasons.push('legacy_send_changed');
  if (observation.otherWorkSendIds.length) reasons.push('other_work_requires_reconciliation');
  if (observation.otherWriterHolds.length) reasons.push('other_writer_holds_require_reconciliation');
  if (Date.parse(observation.observedAt) < Date.parse(body.preparedAt)) reasons.push('observation_predates_plan');
  if (Date.parse(observation.bootedAt) <= Date.parse(body.preparedAt)) reasons.push('later_pc_boot_not_verified');
  let pcCustody = null;
  if (!reasons.length) {
    const pc = value => ({ schema: 'mesh-pc-recovery/v1', taskCount: value.taskCount,
      bootTime: value.bootedAt || value.baselineBoot, machineSha256: value.machineIdentity,
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
    const selected = new Set(sendIds), targetTasks = new Map(rows.map(row => [row.sendId, row.taskId]));
    const sends = db.prepare('SELECT id,taskId,phase,state FROM workroom_sends ORDER BY id').all();
    const otherWorkSendIds = sends.filter(isUnresolvedWorkSend).map(row => row.id).filter(sendId => !selected.has(sendId));
    // Missing activity tables are an incompatible source, never an empty board.
    const otherWriterHolds = [];
    for (const team of db.prepare('SELECT taskId,state FROM workroom_automation ORDER BY taskId').all()) {
      if (team.state === 'active') otherWriterHolds.push({ taskId: team.taskId, sendId: '', reason: 'active_team' });
      else if (!['paused', 'needs_review', 'closed', 'completed'].includes(team.state)) {
        otherWriterHolds.push({ taskId: team.taskId, sendId: '', reason: 'unknown_team_state' });
      }
    }
    for (const send of sends) {
      // The ordinary writer admits prepared/accepted/unknown/rejected only.
      // New or corrupt states need review rather than falling through a filter.
      if (!['prepared', 'accepted', 'unknown', 'rejected'].includes(send.state)) {
        otherWriterHolds.push({ taskId: send.taskId, sendId: send.id, reason: 'unknown_send_state' });
      }
    }
    // Conservative one-time boundary: any other native binding needs its own
    // reconciliation, regardless of send phase or a terminal display state.
    for (const native of db.prepare('SELECT sendId FROM workroom_local_sessions ORDER BY sendId').all()) {
      if (!selected.has(native.sendId)) otherWriterHolds.push({ taskId: sends.find(send => send.id === native.sendId)?.taskId || '',
        sendId: native.sendId, reason: 'other_native_binding' });
    }
    for (const row of db.prepare('SELECT taskId,sendId,state FROM workroom_flow ORDER BY taskId').all()) {
      if (['queued', 'planning', 'working'].includes(row.state)) {
        if (targetTasks.get(row.sendId) !== row.taskId) otherWriterHolds.push({ taskId: row.taskId, sendId: row.sendId, reason: 'pending_intake' });
      } else if (!['idea', 'clarification', 'accepted', 'failed'].includes(row.state)) {
        otherWriterHolds.push({ taskId: row.taskId, sendId: row.sendId, reason: 'unknown_intake_state' });
      }
    }
    const dispatchTables = db.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table' AND name IN ('workroom_dispatch_gate','workroom_dispatch_admissions')").get().n;
    if (dispatchTables === 1) throw Error('Dispatch maintenance schema is incomplete.');
    if (dispatchTables === 2) {
      const gate = db.prepare('SELECT state,generation,holder FROM workroom_dispatch_gate WHERE id=1').get();
      if (!gate || !['open','paused'].includes(gate.state) || !Number.isSafeInteger(gate.generation) || gate.generation < 0 ||
          (gate.state === 'open' && gate.holder)) throw Error('Dispatch maintenance state is invalid.');
      for (const row of db.prepare("SELECT id FROM workroom_dispatch_admissions WHERE state!='finished' ORDER BY id").all()) {
        otherWriterHolds.push({ taskId: '', sendId: row.id, reason: 'pending_dispatch_admission' });
      }
    }
    const board = {};
    for (const { name } of db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").all()) {
      const table = name.replaceAll('"', '""');
      board[name] = db.prepare(`SELECT * FROM "${table}"`).all().map(canonical).sort();
    }
    const boardSha256 = sha(canonical(board));
    const taskCount = db.prepare('SELECT COUNT(*) AS count FROM tasks').get().count;
    return { targets: rows, otherWorkSendIds, otherWriterHolds, boardSha256, taskCount };
}
