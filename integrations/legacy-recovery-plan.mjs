import { createHash, randomUUID } from 'node:crypto';
import { readFile, realpath, writeFile, stat } from 'node:fs/promises';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { DatabaseSync } from 'node:sqlite';
import { resolve, isAbsolute } from 'node:path';
import { pathToFileURL } from 'node:url';
import { homedir } from 'node:os';
import { assertPcRecovery } from './verify-live-release.mjs';

const run = promisify(execFile);
const sha = value => createHash('sha256').update(value).digest('hex');
const canonical = value => JSON.stringify(value, (_, item) => item && typeof item === 'object' && !Array.isArray(item)
  ? Object.fromEntries(Object.entries(item).sort(([a], [b]) => a.localeCompare(b))) : item);
const id = value => typeof value === 'string' && /^[A-Za-z0-9_-]{1,100}$/.test(value);
const digest = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const time = value => typeof value === 'string' && Number.isFinite(Date.parse(value));
const same = (a, b) => canonical(a) === canonical(b);
export const legacyRecoveryFingerprint = value => sha(canonical(value));

function validateSnapshot(snapshot) {
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
  validateSnapshot(snapshot);
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
  validateSnapshot({ ...body, observedAt: body.preparedAt, bootedAt: body.baselineBoot, otherWorkSendIds: [] });
  validateSnapshot(observation);
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

export function readLegacyRows(databasePath, sendIds) {
  const db = new DatabaseSync(databasePath, { readOnly: true });
  try {
    db.exec('PRAGMA query_only=ON; BEGIN;');
    const result = captureLegacyRecoveryRows(db, sendIds);
    db.exec('COMMIT;');
    return result;
  } finally { db.close(); }
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

export async function observeLegacyRecovery({ workspace, databasePath, sendIds, sourceFiles }) {
  if (process.platform !== 'win32') throw Error('The live collector requires this Windows PC.');
  const { stdout } = await run('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command',
    '$o=Get-CimInstance Win32_OperatingSystem; @{host=$o.CSName;bootedAt=$o.LastBootUpTime.ToUniversalTime().ToString("o")} | ConvertTo-Json -Compress'],
  { windowsHide: true, timeout: 15000, maxBuffer: 8192 });
  const machine = JSON.parse(stdout.trim());
  const file = await stat(databasePath, { bigint: true });
  if (!file.isFile() || file.ino <= 0n || file.birthtimeNs <= 0n) throw Error('Database file identity is unavailable.');
  const databaseIdentity = sha(canonical({ device: String(file.dev), file: String(file.ino), created: String(file.birthtimeNs) }));
  const snapshot = { workspace: await realpath(workspace), databasePath: await realpath(databasePath), databaseIdentity,
    host: machine.host, bootedAt: machine.bootedAt, observedAt: new Date().toISOString(), sources: {},
    ...readLegacyRows(databasePath, sendIds) };
  for (const [name, file] of Object.entries(sourceFiles)) snapshot.sources[name] = sha(await readFile(file));
  validateSnapshot(snapshot);
  return snapshot;
}

export function legacyRecoverySources(workspace) {
  return {
    meshClaimPolicy: resolve(workspace, 'lib/workroom-claim-policy.mjs'),
    meshWorkroom: resolve(workspace, 'lib/workroom.mjs'),
    legacyRecoveryStore: resolve(workspace, 'lib/workroom-legacy-recovery.mjs'),
    recoveryPlanner: resolve(workspace, 'integrations/legacy-recovery-plan.mjs'),
    pcCustodyVerifier: resolve(workspace, 'integrations/verify-live-release.mjs'),
    relayStore: 'D:/Dev/Onoes-Relay/relay_sessions.py', relayServer: 'D:/Dev/Onoes-Relay/relay_server.py',
    relayNativeReceipts: 'D:/Dev/Onoes-Relay/relay_native_receipts.py',
    hermesRuns: resolve(homedir(), 'AppData/Local/hermes/hermes-agent/gateway/platforms/api_server_runs.py'),
    dshBridge: resolve(homedir(), '.dsh/profiles/a2a/node_modules/dsh-a2a-server/lib/index.js'),
  };
}

async function main() {
  const [action, input, output] = process.argv.slice(2);
  if (!['prepare', 'inspect'].includes(action) || !input || !output) throw Error('Use prepare <exact-scope.json> <new-plan.json> or inspect <plan.json> <new-assessment.json>. No apply action exists.');
  const value = JSON.parse(await readFile(resolve(input), 'utf8'));
  const workspace = action === 'prepare' ? process.cwd() : value.workspace;
  if (await realpath(workspace) !== await realpath(process.cwd())) throw Error('Run from the reviewed Mesh workspace.');
  const snapshot = await observeLegacyRecovery({ workspace, databasePath: action === 'prepare'
    ? resolve('data/workroom-preview/tasks.sqlite') : value.databasePath,
  sendIds: value.targets.map(t => t.sendId), sourceFiles: legacyRecoverySources(workspace) });
  const result = action === 'prepare' ? makeLegacyRecoveryPlan(snapshot) : assessLegacyRecovery(value, snapshot);
  await writeFile(resolve(output), JSON.stringify(result, null, 2) + '\n', { flag: 'wx' });
  process.stdout.write(JSON.stringify({ action, output: resolve(output), targetCount: result.targets?.length || result.targetCount,
    planHash: result.planHash, status: result.status || 'prepared_only', reasons: result.reasons || [], canRelease: false }) + '\n');
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(error => { process.stderr.write(error.message + '\n'); process.exitCode = 1; });
}
