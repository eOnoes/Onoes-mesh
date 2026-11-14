// One-shot, local operator entry. Importing this file opens no resources.
// The scope hash and owner-record hash are supplied out of band after review.
import { createHash } from 'node:crypto';
import { lstatSync, realpathSync, readFileSync, existsSync, writeFileSync } from 'node:fs';
import { resolve, isAbsolute, dirname, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';
import { DatabaseSync } from 'node:sqlite';
import { homedir } from 'node:os';
import { databaseFileIdentity } from '../lib/database-identity.mjs';
import { createDispatchBarrier, assertDispatchHold } from '../lib/workroom-dispatch-barrier.mjs';
import { holdWindowsNativeMaintenance, assertNativeMaintenanceHold } from '../lib/windows-native-maintenance.mjs';
import { createLegacyAuthorizationReader } from '../lib/workroom-legacy-authorization.mjs';
import { issueLegacyRecoveryPermit, createLegacyRecoveryStore } from '../lib/workroom-legacy-recovery.mjs';
import { makeLegacyRecoveryPlan, assessLegacyRecovery, legacyRecoveryFingerprint as fingerprint } from '../lib/workroom-legacy-evidence.mjs';
import { observeLegacyRecovery, legacyRecoverySources } from './legacy-recovery-plan.mjs';

const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const digest = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const key = path => process.platform === 'win32' ? path.toLowerCase() : path;
const same = (a, b) => fingerprint(a) === fingerprint(b);
const retainedRelayFiles = ['relay_server.py', 'relay_a2a.py', 'relay_a2a_reconcile.py', 'relay_auth.py', 'relay_budget.py',
    'relay_channels.py', 'relay_config.py', 'relay_db.py', 'relay_hermes.py', 'relay_inbox.py', 'relay_mcp.py',
    'relay_native_receipts.py', 'relay_notify.py', 'relay_openclaw.py', 'relay_sessions.py', 'relay_webpush.py'];
function requireValue(condition, message) { if (!condition) throw Error(message); }
// Relay's Python str.strip includes U+0085 and U+001C..001F and excludes
// U+FEFF. JavaScript trim has different boundaries; never normalize interiors.
const relayWhitespace = '[\\u0009-\\u000d\\u001c-\\u0020\\u0085\\u00a0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]';
const relayBoundaries = new RegExp(`^${relayWhitespace}+|${relayWhitespace}+$`, 'gu');
export function normalizeRelayDelivery(value) {
  requireValue(typeof value === 'string', 'A saved string delivery is required.');
  return value.replace(relayBoundaries, '');
}
function localFile(path, maxBytes) {
  requireValue(typeof path === 'string' && isAbsolute(path) && (process.platform !== 'win32' || /^[a-z]:[\\/]/i.test(path)), 'An absolute local file is required.');
  requireValue(key(realpathSync.native(path)) === key(resolve(path)), 'Aliased paths are refused.');
  const info = lstatSync(path, { bigint: true });
  requireValue(info.isFile() && !info.isSymbolicLink() && info.ino > 0n && (!maxBytes || info.size <= BigInt(maxBytes)), 'Invalid operator input file.');
  return info;
}
function readPinned(path, expectedSha256, maxBytes = 1048576) {
  requireValue(digest(expectedSha256), 'A separately reviewed SHA256 is required.');
  const before = localFile(path, maxBytes), bytes = readFileSync(path), after = localFile(path, maxBytes);
  requireValue(before.dev === after.dev && before.ino === after.ino && before.birthtimeNs === after.birthtimeNs &&
    bytes.length <= maxBytes && sha(bytes) === expectedSha256, 'Operator input changed or its reviewed hash does not match.');
  return bytes;
}
function readPinnedObject(input) {
    const bytes = readPinned(input?.path, input?.sha256);
    let value;
    try { value = JSON.parse(bytes.toString('utf8')); }
    catch { throw Error('Retained review input is not valid JSON.'); }
    requireValue(value && typeof value === 'object' && !Array.isArray(value), 'Retained review inputs must be JSON objects.');
    return value;
}

function readonly(path, identity, action) {
  localFile(path);
  requireValue(databaseFileIdentity(path) === identity, 'Replay database identity changed.');
  const db = new DatabaseSync(path, { readOnly: true });
  try {
    db.exec('PRAGMA query_only=ON; BEGIN;');
    const result = action(db);
    db.exec('COMMIT;');
    requireValue(databaseFileIdentity(path) === identity, 'Replay database was replaced during inspection.');
    return result;
  } finally { db.close(); }
}

// Metadata only: do not load chat bodies, attachments, principal IDs or payloads.
export function inspectReplayQueues({ relay, hermes }) {
  return {
    relay: readonly(relay.path, relay.identity, db => db.prepare('SELECT state,COUNT(*) AS count FROM outbox GROUP BY state ORDER BY state').all()),
    hermes: readonly(hermes.path, hermes.identity, db => db.prepare('SELECT status,COUNT(*) AS count FROM session_admissions GROUP BY status ORDER BY status').all()),
  };
}

// A review witness only. Missing Workroom links never establish workspace scope,
// non-replay or writer retirement, and this report cannot create a permit.
export function inspectRetainedRecords(scope) {
  const workroom = readonly(scope.databasePath, scope.databaseIdentity, db => ({
    taskCount: db.prepare('SELECT COUNT(*) AS n FROM tasks').get().n,
    sends: db.prepare('SELECT id,taskId,agentId,conversationId FROM workroom_sends').all(),
    bindings: db.prepare('SELECT sendId,taskId,sessionId,admissionId FROM workroom_local_sessions').all(),
  }));
  const tasks = values => [...new Set(values.filter(Boolean))].sort();
  const recordHash = row => {
    requireValue(Object.values(row).every(value => typeof value !== 'number' || Number.isFinite(value) && Math.abs(value) <= Number.MAX_SAFE_INTEGER),
      'Queue record has unclassifiable numeric metadata.');
    return fingerprint(row);
  };
  const unresolved = (source, table, predicate) => readonly(source.path, source.identity, db => {
    const rows = db.prepare(`SELECT * FROM ${table} WHERE ${predicate} LIMIT 257`).all();
    requireValue(rows.length <= 256, 'Diagnostic record limit exceeded; use a separately scoped review.');
    return { rows, schemaFingerprint: fingerprint(db.prepare(`PRAGMA table_info(${table})`).all()) };
  });
  const relay = unresolved(scope.relay, 'outbox', "state IS NULL OR state NOT IN ('accepted','failed','dead')");
  const hermes = unresolved(scope.hermes, 'session_admissions', "status IS NULL OR status!='terminal'");
  const records = relay.rows.map(row => ({
    source: 'relay_outbox', recordId: row.idem_key, recordFingerprint: recordHash(row),
    agentId: row.agent_id, state: row.state,
    directWorkroomTaskIds: tasks(workroom.sends.filter(send => send.id === row.idem_key).map(send => send.taskId)),
    sharedConversationTaskIds: tasks(workroom.sends.filter(send => send.conversationId === row.session_id).map(send => send.taskId)),
    decision: 'unresolved_do_not_release',
  }));
  for (const row of hermes.rows) {
    let markerTypes, nativeTextEnvelope = false;
    try {
      const payload = JSON.parse(row.payload_json), native = payload?.native_text_v1;
      requireValue(payload && typeof payload === 'object' && !Array.isArray(payload) &&
        (native == null || typeof native === 'object' && !Array.isArray(native)), 'Unclassified admission envelope.');
      nativeTextEnvelope = Boolean(native && typeof native === 'object' && !Array.isArray(native));
      markerTypes = {
        localAutomation: Object.hasOwn(payload, 'local_automation_v1'), kanbanCard: Object.hasOwn(payload, 'kanban_card_v1'),
        nativeAutomation: Boolean(native && Object.hasOwn(native, 'automation')),
        webhookDelivery: Boolean(native && Object.hasOwn(native, 'webhook_delivery')),
      };
    } catch { markerTypes = 'unclassified_payload'; }
    const principal = row.principal_id || '';
    const principalClass = principal.startsWith('messaging:telegram:') ? 'telegram' : principal.startsWith('messaging:') ? 'messaging'
      : principal.startsWith('automation:') ? 'automation' : principal === 'api' ? 'api' : 'unclassified';
    records.push({ source: 'hermes_admission', recordId: row.admission_id, recordFingerprint: recordHash(row),
      state: row.status, principalClass, nativeTextEnvelope, automationMarkers: markerTypes,
      directWorkroomTaskIds: tasks(workroom.bindings.filter(binding => binding.admissionId === row.admission_id).map(binding => binding.taskId)),
      sharedConversationTaskIds: tasks([...workroom.sends.filter(send => send.conversationId === row.target_session_id).map(send => send.taskId),
        ...workroom.bindings.filter(binding => binding.sessionId === row.target_session_id).map(binding => binding.taskId)]),
      decision: 'unresolved_do_not_release' });
  }
  return { schema: 'mesh/retained-record-diagnostic/v1', observedAt: new Date().toISOString(), mode: 'read_only',
    taskCount: workroom.taskCount, workroomSendCount: workroom.sends.length, records,
    sources: {
      workroom: { path: scope.databasePath, identity: scope.databaseIdentity },
      relay: { path: scope.relay.path, identity: scope.relay.identity, schemaFingerprint: relay.schemaFingerprint },
      hermes: { path: scope.hermes.path, identity: scope.hermes.identity, schemaFingerprint: hermes.schemaFingerprint },
    },
    canRelease: false, limitations: ['Separate read transactions; not a held commit fence.',
      'ID and conversation links do not establish project scope, non-replay or writer retirement.',
      'No route, runtime/startup or worker-containment qualification is supplied by this report.'] };
}

// A source-bound fact witness, never a capability. Offline recovery must join
// this with the later boot, actual held resources and separate owner quiet-window
// authority; a matching review by itself cannot recover anything.
export function verifyRetainedReview(scope) {
  const descriptor = scope.retainedReview;
  if (!descriptor) return { status: 'not_supplied', canRelease: false };
  const json = readPinnedObject;
  const review = json(descriptor);
  requireValue(review.schema === 'mesh/retained-record-review/v1' && review.owner === 'Eddie' &&
    review.decision === 'preserve_without_retry_or_retirement' &&
    review.writerScope === 'confirmed_desktop_only' && Array.isArray(review.selectedSendIds) &&
    review.selectedSendIds.length === 8 && new Set(review.selectedSendIds).size === 8 && scope.bindings?.length === 8 &&
    same(review.selectedSendIds?.slice().sort(), scope.bindings?.map(binding => binding.sendId).sort()),
  'An exact owner-reviewed desktop scope and selected send set are required.');
  const current = inspectRetainedRecords(scope);
  const ordered = records => records.slice().sort((a, b) => (a.source + ':' + a.recordId).localeCompare(b.source + ':' + b.recordId));
  requireValue(Array.isArray(review.records) && review.records.length === 3 && current.records.length === 3 &&
    new Set(current.records.map(record => record.source + ':' + record.recordId)).size === 3 &&
    same(review.sources, current.sources) && same(ordered(review.records), ordered(current.records)),
  'The retained source identities, schemas, complete rows or Workroom links changed.');
  const relayRecords = current.records.filter(record => record.source === 'relay_outbox');
  const nativeRecords = current.records.filter(record => record.source === 'hermes_admission');
  requireValue(relayRecords.length === 2 && same(relayRecords.map(record => record.agentId).sort(), ['cyony', 'dsh']) &&
    relayRecords.every(record => record.state === 'retrying' && record.directWorkroomTaskIds.length === 0) &&
    nativeRecords.length === 1 && nativeRecords[0].state === 'unknown' && nativeRecords[0].nativeTextEnvelope === true &&
    ['messaging', 'telegram'].includes(nativeRecords[0].principalClass) && nativeRecords[0].directWorkroomTaskIds.length === 0 &&
    nativeRecords[0].automationMarkers !== 'unclassified_payload' &&
    Object.values(nativeRecords[0].automationMarkers).every(value => value === false),
  'The reviewed retained states are not supported; no queued/started or automation exception exists.');
  const relay = json(review.qualifications?.relay), native = json(review.qualifications?.native);
  requireValue(relay.schema === 'mesh/relay-retained-startup-qualification/v1' && relay.liveStoreOpened === false &&
    relay.liveDeploymentChanged === false && relay.networkOrProcessAttempts === 0 && relay.boundaryRejectionControlsPassed === 3 &&
    relay.cases?.length === 2 && relay.cases.every((item, i) => item.boot === i + 1 && item.startupTransportCalls === 0 &&
      item.duplicateTransportCalls === 0 && item.freshRequestTransportCalls === 1 && item.retainedRowsUnchanged === true),
  'The reviewed Relay startup qualification is incomplete.');
  requireValue(native.schema === 'mesh/native-retained-startup-qualification/v1' && native.liveStoreOpened === false &&
    native.liveServiceRestarted === false && native.originalWorkerRetirementEstablished === false &&
    native.coordinatorIsPrimaryRecovery === true && native.recoveries?.length === 2 && native.recoveries.every((item, i) =>
      item.startup === i + 1 && item.syntheticModelCalls === (i === 0 ? 1 : 0) && item.unknownRemainedPaused === true &&
      item.blockedFollowerRemainedQueued === true && item.safeRequestCompleted === true && item.gatewayCoordinatorPreservedRows === true),
  'The reviewed native coordinator qualification is incomplete.');
  requireValue(same(Object.keys(relay.sourceSha256 || {}).sort(), retainedRelayFiles.slice().sort()), 'Incomplete Relay qualification source set.');
  for (const file of retainedRelayFiles) readPinned(resolve('D:/Dev/Onoes-Relay', file), relay.sourceSha256[file]);
  const nativeRoot = resolve(homedir(), 'AppData/Local/hermes/hermes-agent');
  const nativeFiles = Object.entries(legacyRecoverySources(scope.workspace)).filter(([name]) => name.startsWith('hermesRecovery'));
  requireValue(nativeFiles.length === 14 && Object.keys(native.sourceSha256 || {}).length === 14,
    'Incomplete native qualification source set.');
  for (const [, file] of nativeFiles) {
    const relative = file.slice(nativeRoot.length + 1).split(sep).join('/');
    readPinned(file, native.sourceSha256[relative]);
  }
  readPinned(resolve(scope.workspace, 'integrations/qualify-relay-retained-startup.py'), relay.qualificationHelperSha256);
  const helpers = ['qualify-native-retained-startup.py', 'qualify-native-retained-peer.py', 'qualify-native-retained-recovery.py'];
  requireValue(same(Object.keys(native.helperSha256 || {}).sort(), helpers.slice().sort()), 'Incomplete native qualifier source set.');
  for (const helper of helpers) readPinned(resolve(scope.workspace, 'integrations', helper), native.helperSha256[helper]);
  return { status: 'matched_review_only', retainedRecords: 3, qualificationSources: 30,
    canRelease: false, workerRetirementEstablished: false,
    remaining: ['Later same-machine boot and actual offline worker leases', 'Exact owner quiet-window authorization', 'Live activation is not granted by this witness'] };
}

export function verifyReplayRecords(scope, targets) {
  requireValue(targets.length === 8 && new Set(targets.map(t => t.sendId)).size === 8 &&
    scope.bindings?.length === 8 && new Set(scope.bindings.map(t => t.sendId)).size === 8 &&
    scope.bindings.every(t => targets.some(original => original.sendId === t.sendId && original.agentId === t.agentId)), 'Replay bindings must cover exactly the eight original sends.');
  requireValue(scope.bindings.filter(t => t.agentId === 'echo').length === 6 &&
    scope.bindings.filter(t => t.agentId === 'dsh').length === 2, 'The reviewed six Echo / two DSH route is required.');
  let retained = null;
  if (scope.retainedReview) {
    requireValue(scope.schema === 'mesh/legacy-operator-scope/v2' && scope.containment === 'worker_services_offline',
      'Retained records require the reviewed offline v2 scope.');
    retained = verifyRetainedReview(scope);
  }
  // Workroom stores the rendered delivery separately from the user's short text.
  // Relay strips that delivery's outer whitespace before transport admission.
  const originalDeliveries = readonly(scope.databasePath, scope.databaseIdentity, db => new Map(scope.bindings.map(binding => {
    const rows = db.prepare('SELECT id,taskId,agentId,conversationId,payload FROM workroom_sends WHERE id=?').all(binding.sendId);
    const target = targets.find(t => t.sendId === binding.sendId), row = rows[0];
    requireValue(rows.length === 1 && row.taskId === target.taskId && row.agentId === binding.agentId &&
      row.conversationId === binding.conversationId && typeof row.payload === 'string' && normalizeRelayDelivery(row.payload).length > 0,
    'A binding does not match the original Workroom delivery.');
    return [binding.sendId, normalizeRelayDelivery(row.payload)];
  })));
  readonly(scope.relay.path, scope.relay.identity, db => {
    const states = db.prepare('SELECT DISTINCT state FROM outbox').all().map(row => row.state);
    requireValue(retained?.status === 'matched_review_only' || states.every(state => ['accepted', 'failed', 'dead'].includes(state)), 'Relay has unresolved queued deliveries; recovery stays blocked.');
    for (const binding of scope.bindings) {
      const rows = db.prepare('SELECT idem_key,agent_id,session_id,state,transport_ref,content FROM outbox WHERE idem_key=?').all(binding.sendId);
      requireValue(rows.length === 1 && rows[0].agent_id === binding.agentId && rows[0].session_id === binding.conversationId &&
        rows[0].state === 'accepted' && rows[0].transport_ref === null, 'An original Relay receipt changed.');
      requireValue(rows[0].content === originalDeliveries.get(binding.sendId), 'Relay text does not match the original delivery payload.');
    }
  });
  readonly(scope.hermes.path, scope.hermes.identity, db => {
    requireValue(retained?.status === 'matched_review_only' || db.prepare("SELECT COUNT(*) AS n FROM session_admissions WHERE status IS NULL OR status!='terminal'").get().n === 0,
      'Hermes has unresolved native admissions; recovery stays blocked.');
    for (const binding of scope.bindings.filter(t => t.agentId === 'echo')) {
      const rows = db.prepare('SELECT admission_id,request_id,target_session_id,payload_digest,status,outcome,owner_epoch,generation FROM session_admissions WHERE admission_id=?').all(binding.admissionId);
      requireValue(rows.length === 1 && rows[0].target_session_id === binding.conversationId && rows[0].status === 'terminal' &&
        rows[0].outcome === 'completed' && fingerprint(rows[0]) === binding.nativeFingerprint, 'An original Echo admission changed.');
      // Extract only this exact original request field, never its saved history.
      const request = db.prepare("SELECT json_extract(payload_json,'$.text') AS text FROM session_admissions WHERE admission_id=?").get(binding.admissionId);
      requireValue(request.text === originalDeliveries.get(binding.sendId), 'Echo request text does not match the original delivery payload.');
    }
  });
  const dsh = verifyDshSnapshot(scope.dsh, scope.bindings, originalDeliveries);
  return { exactAcceptedSends: 8, terminalEchoAdmissions: 6, ...dsh };
}

// Parse the same bytes whose hash is pinned by the separately reviewed scope.
// This freezes the task/origin association, not just each message in isolation.
export function verifyDshSnapshot(snapshot, bindings, originalDeliveries) {
  const bytes = readPinned(snapshot.path, snapshot.sha256, 16777216);
  return verifyDshOrigins(JSON.parse(bytes.toString('utf8')), bindings, originalDeliveries);
}

// Read-only association evidence, not writer retirement or dispatch permission.
export function verifyDshOrigins(records, bindings, originalDeliveries) {
  const selected = bindings.filter(binding => binding.agentId === 'dsh');
  requireValue(Array.isArray(records) && selected.length === 2 && new Set(selected.map(binding => binding.nativeTaskId)).size === 2 &&
    new Set(selected.map(binding => binding.originMessageId)).size === 2, 'Two distinct DSH origin bindings are required.');
  for (const binding of selected) {
    const matches = records.filter(row => row.id === binding.nativeTaskId);
    requireValue(matches.length === 1 && matches[0].contextId === binding.conversationId && matches[0].status?.state === 3 &&
      fingerprint({ id: matches[0].id, contextId: matches[0].contextId, status: matches[0].status }) === binding.nativeFingerprint,
    'An original DSH task is missing, changed or replayable.');
    // A task may include a later follow-up. Bind its reviewed originating message,
    // not any text match elsewhere in history or a claim of original-work success.
    const origin = matches[0].history?.[0];
    requireValue(typeof binding.originMessageId === 'string' && binding.originMessageId.length > 0 &&
      digest(binding.originFingerprint) && origin?.role === 1 && origin.messageId === binding.originMessageId &&
      (!origin.taskId || origin.taskId === binding.nativeTaskId) && fingerprint(origin) === binding.originFingerprint,
    'DSH origin is missing, changed or does not identify the reviewed request boundary.');
    const occurrences = records.flatMap(task => (task.history || []).filter(message => message.messageId === binding.originMessageId));
    requireValue(occurrences.length === 1, 'DSH origin occurs more than once in the task store.');
    requireValue(origin.parts?.length === 1 && origin.parts[0].content?.$case === 'text' &&
      origin.parts[0].content.value === originalDeliveries.get(binding.sendId),
    'DSH request text differs from the original delivery payload.');
  }
  return { completedDshTasks: 2, originalWorkOutcome: 'unknown' };
}

// Read-only OS query. Names are data in an environment variable, never shell code.
export function readWindowsStartupTasks(tasks) {
  requireValue(process.platform === 'win32', 'The live operator requires Windows.');
  const script = String.raw`$ErrorActionPreference='Stop'; $q=ConvertFrom-Json $env:MESH_RECOVERY_TASK_QUERY; $r=@(foreach($i in $q){$t=Get-ScheduledTask -TaskName $i.name -TaskPath $i.path -ErrorAction Stop; @{name=$t.TaskName;path=$t.TaskPath;enabled=[bool]$t.Settings.Enabled;state=[string]$t.State;actions=@($t.Actions|Select-Object Execute,Arguments,WorkingDirectory);principal=$t.Principal|Select-Object UserId,LogonType,RunLevel}}); ConvertTo-Json -InputObject $r -Compress -Depth 8`;
  return JSON.parse(execFileSync('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', script], {
    windowsHide: true, timeout: 5000, maxBuffer: 65536, encoding: 'utf8',
    env: { ...process.env, MESH_RECOVERY_TASK_QUERY: JSON.stringify(tasks.map(({ name, path }) => ({ name, path }))) },
  }).trim());
}

export function verifyStartupControls(scope, observations) {
  requireValue(scope.startup?.tasks?.length === 2 && scope.startup.shortcuts?.length === 3 && observations.length === 2,
    'Both scheduled restart owners and all three worker login shortcuts must be covered.');
  for (const task of scope.startup.tasks) {
    const matches = observations.filter(row => row.name === task.name && row.path === task.path);
    requireValue(matches.length === 1 && matches[0].enabled === false && matches[0].state === 'Disabled' &&
      fingerprint({ actions: matches[0].actions, principal: matches[0].principal }) === task.definitionFingerprint,
    'A reviewed scheduled restart owner is enabled, running or changed.');
  }
  for (const item of scope.startup.shortcuts) {
    requireValue(isAbsolute(item.original) && /[\\/]Start Menu[\\/]Programs[\\/]Startup[\\/][^\\/]+\.lnk$/i.test(item.original) &&
      !existsSync(item.original) && !/[\\/]Startup[\\/]/i.test(item.parked), 'A reviewed login shortcut remains active or is not safely parked.');
    readPinned(item.parked, item.sha256, 65536);
  }
  return { disabledTasks: 2, parkedShortcuts: 3 };
}

export function loadOperatorScope(scopePath, expectedSha256) {
  const scope = JSON.parse(readPinned(scopePath, expectedSha256));
  requireValue(scope.schema === 'mesh/legacy-operator-scope/v2' && scope.containment === 'worker_services_offline' && scope.owner === 'Eddie' &&
    scope.locality === 'desktop_echo_dsh_only', 'Reviewed owner, desktop-only scope and offline v2 containment are required.');
  requireValue(key(realpathSync.native(scope.workspace)) === key(resolve(scope.workspace)) &&
    key(realpathSync.native(process.cwd())) === key(scope.workspace), 'Run from the exact reviewed Mesh workspace.');
  localFile(scope.databasePath);
  requireValue(digest(scope.databaseIdentity) && databaseFileIdentity(scope.databasePath) === scope.databaseIdentity,
    'The original Workroom database identity is required.');
  requireValue(digest(scope.relay?.identity) && digest(scope.hermes?.identity), 'Replay database identities are required.');
  requireValue(digest(scope.dsh?.sha256), 'A separately reviewed DSH task-store snapshot hash is required.');
  requireValue(same(scope.startup.tasks.map(t => t.name).sort(), ['Hermes_Gateway', 'Onoes Deep Watchdog'].sort()) &&
    new Set(scope.startup.tasks.map(t => t.path + t.name)).size === 2 &&
    new Set(scope.startup.shortcuts.map(t => key(resolve(t.original)))).size === 3,
  'The exact reviewed startup owners are required.');
  requireValue(same(scope.startup.shortcuts.map(t => resolve(t.original).split(/[\\/]/).at(-1)).sort(),
    ['Onoes Deep (DSH A2A).lnk', 'Onoes DeepSeek Harness Web.lnk', 'Onoes Relay.lnk'].sort()), 'Both DSH login entries and the Relay login entry must be covered.');
  requireValue(scope.bindings?.length === 8 && scope.bindings.every(b => b.conversationId && digest(b.nativeFingerprint)) &&
    scope.bindings.every(b => typeof (b.agentId === 'echo' ? b.admissionId : b.nativeTaskId) === 'string' &&
      (b.agentId === 'echo' ? b.admissionId : b.nativeTaskId).length > 0) &&
    new Set(scope.bindings.filter(b => b.agentId === 'echo').map(b => b.admissionId)).size === 6 &&
    new Set(scope.bindings.filter(b => b.agentId === 'dsh').map(b => b.nativeTaskId)).size === 2,
  'Eight independently correlated native bindings are required.');
  const dshBindings = scope.bindings.filter(binding => binding.agentId === 'dsh');
  requireValue(dshBindings.every(binding => typeof binding.originMessageId === 'string' &&
    /^[A-Za-z0-9_-]{1,100}$/.test(binding.originMessageId) && digest(binding.originFingerprint)) &&
    new Set(dshBindings.map(binding => binding.originMessageId)).size === 2,
  'Both independently pinned DSH originating message boundaries are required.');
  const sourceFiles = { ...legacyRecoverySources(scope.workspace), operatorScope: scopePath, operatorRunner: fileURLToPath(import.meta.url),
    dshTaskStoreSnapshot: scope.dsh.path };
  if (scope.retainedReview) {
    const review = readPinnedObject(scope.retainedReview);
    readPinnedObject(review.qualifications?.relay); readPinnedObject(review.qualifications?.native);
    Object.assign(sourceFiles, {
      retainedReviewRecord: scope.retainedReview.path,
      retainedRelayQualification: review.qualifications.relay.path,
      retainedNativeQualification: review.qualifications.native.path,
      retainedRelayQualifier: resolve(scope.workspace, 'integrations/qualify-relay-retained-startup.py'),
      retainedNativeParent: resolve(scope.workspace, 'integrations/qualify-native-retained-startup.py'),
      retainedNativePeer: resolve(scope.workspace, 'integrations/qualify-native-retained-peer.py'),
      retainedNativeRecovery: resolve(scope.workspace, 'integrations/qualify-native-retained-recovery.py'),
    });
    retainedRelayFiles.forEach((file, index) => { sourceFiles['retainedRelayModule' + index] = resolve('D:/Dev/Onoes-Relay', file); });
  }
  for (const [name, path] of Object.entries(scope.additionalSources || {})) {
    requireValue(/^[a-zA-Z][a-zA-Z0-9]{0,63}$/.test(name) && !['constructor', 'prototype'].includes(name) &&
      !Object.hasOwn(sourceFiles, name), 'Source names cannot override the required recovery implementation.');
    localFile(path); sourceFiles[name] = path;
  }
  // Native lock/endpoint identity is also incorporated by the collector itself.
  return { scope, sourceFiles, checkScope: () => readPinned(scopePath, expectedSha256) };
}

// This deployed operator is intentionally confined to the already reviewed local
// service layout. A narrower arbitrary JSON resource list is not coverage proof.
export function verifyDeploymentScope(scope) {
  const at = suffix => resolve(homedir(), suffix);
  const exact = (actual, expected) => key(resolve(actual)) === key(expected);
  requireValue(exact(scope.databasePath, resolve(scope.workspace, 'data/workroom-preview/tasks.sqlite')) &&
    exact(scope.relay.path, resolve('D:/Dev/Onoes-Relay/.private/relay.sqlite3')) &&
    exact(scope.hermes.path, at('AppData/Local/hermes/state.db')) &&
    exact(scope.dsh.path, at('.dsh/a2a/runtime/tasks/a2a-tasks.json')), 'The deployed service/database layout does not match the reviewed operator.');
  requireValue(scope.nativeResources?.profileLocks?.length === 1 &&
    exact(scope.nativeResources.profileLocks[0], at('AppData/Local/hermes/gateway.lock')) &&
    same(scope.nativeResources.endpoints?.map(JSON.stringify).sort(),
      [3081, 4123, 8642, 8787].flatMap(port => [['127.0.0.1', port], ['::1', port]]).map(JSON.stringify).sort()),
  'The full reviewed native profile and eight worker loopback endpoints are required.');
  const startup = at('AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup');
  requireValue(scope.startup.shortcuts.every(item => exact(item.original, resolve(startup, item.original.split(/[\\/]/).at(-1)))) &&
    scope.startup.tasks.every(task => task.path === '\\'), 'The reviewed login and scheduled-task locations are required.');
}

// Import-only dependency injection permits disposable OS observations in tests;
// the CLI has no flag, environment switch or JSON field selecting these functions.
export async function runLegacyOperator({ action, scopePath, scopeSha256, planPath, authorizationPath, authorizationSha256 },
  { collect = observeLegacyRecovery, startupReader = readWindowsStartupTasks, validateDeployment = verifyDeploymentScope } = {}) {
  requireValue(['prepare', 'inspect', 'apply'].includes(action), 'Use prepare, inspect or apply.');
  const { scope, sourceFiles, checkScope } = loadOperatorScope(scopePath, scopeSha256);
  validateDeployment(scope);
  const sendIds = scope.bindings.map(binding => binding.sendId);
  const observe = () => collect({ ...scope, sendIds, sourceFiles });
  const checkControls = targets => {
    checkScope();
    verifyStartupControls(scope, startupReader(scope.startup.tasks));
    verifyReplayRecords(scope, targets);
  };
  const observation = await observe();
  if (action === 'prepare') {
    checkControls(observation.targets);
    const db = new DatabaseSync(scope.databasePath, { readOnly: true });
    try {
      const gate = createDispatchBarrier(db).status();
      requireValue(gate.state === 'paused' && !gate.held && gate.activeAdmissions === 0, 'Dispatch must already be paused, unheld and drained before freezing a preboot plan.');
    } finally { db.close(); }
    const plan = makeLegacyRecoveryPlan(observation);
    writeFileSync(planPath, JSON.stringify(plan, null, 2) + '\n', { flag: 'wx' });
    return { status: 'prepared_only', planHash: plan.planHash, canRelease: false };
  }
  const plan = JSON.parse(readFileSync((localFile(planPath, 1048576), planPath), 'utf8'));
  const assessment = assessLegacyRecovery(plan, observation);
  let controls;
  try { checkControls(plan.targets); controls = { status: 'verified' }; }
  catch (error) { controls = { status: 'blocked', reason: error.message }; }
  if (action === 'inspect') {
    let retainedReview;
    try { retainedReview = verifyRetainedReview(scope); }
    catch (error) { retainedReview = { status: 'blocked', reason: error.message, canRelease: false }; }
    return { ...assessment, controls, retainedRecords: inspectRetainedRecords(scope), retainedReview, canRelease: false };
  }
  requireValue(assessment.status === 'ready_for_operator_review' && controls.status === 'verified',
    'Recovery remains blocked: ' + [...assessment.reasons, controls.reason].filter(Boolean).join('; '));
  const baseAuthorize = await createLegacyAuthorizationReader({ recordPath: authorizationPath, expectedSha256: authorizationSha256,
    planHash: plan.planHash, host: observation.host, bootedAt: observation.bootedAt });
  const checkOwner = requestedPlanHash => {
    const owner = baseAuthorize.checkSync(requestedPlanHash);
    if (scope.retainedReview) {
      const record = readPinnedObject({ path: authorizationPath, sha256: authorizationSha256 });
      requireValue(record.maintenanceMode === 'worker_services_offline' && record.quietWorkspaceConfirmed === true &&
        record.retainedReviewSha256 === scope.retainedReview.sha256,
      'Exact owner quiet-window authority for this retained review is required.');
    }
    return owner;
  };
  const authorize = async requestedPlanHash => checkOwner(requestedPlanHash);
  Object.defineProperty(authorize, 'checkSync', { value: checkOwner });
  await authorize(plan.planHash);
  let nativeLease, meshLease, db;
  try {
    nativeLease = await holdWindowsNativeMaintenance(scope.nativeResources);
    db = new DatabaseSync(scope.databasePath);
    meshLease = createDispatchBarrier(db).hold();
    const boundary = (_plan, current) => {
      checkControls(_plan.targets);
      for (const [name, path] of Object.entries(sourceFiles)) {
        localFile(path);
        requireValue(sha(readFileSync(path)) === current.sources[name], 'A reviewed source changed during recovery.');
      }
      assertDispatchHold(meshLease, _plan, db);
      assertNativeMaintenanceHold(nativeLease, _plan);
      return { schema: 'mesh/legacy-local-fence/v1', planHash: _plan.planHash, host: current.host,
        bootedAt: current.bootedAt, machineIdentity: current.machineIdentity, sources: current.sources,
        dispatchPaused: true, coveredLocalWriters: true, activeWriterCount: 0, replayPrevented: true, uncoveredWriters: [] };
    };
    const permit = await issueLegacyRecoveryPermit({ plan, authorize, observe, verifyFence: boundary,
      commitGuard: (p, o) => ({ owner: authorize.checkSync(p.planHash), boundary: boundary(p, o) }), meshLease, nativeLease });
    return { ...await createLegacyRecoveryStore(db).commit(permit), dispatchRemainsPaused: true };
  } finally {
    try { meshLease?.release(); }
    finally { try { db?.close(); } finally { nativeLease?.release(); } }
  }
}

async function main() {
  const [action, scopePath, scopeSha256, planPath, authorizationPath, authorizationSha256, ...extra] = process.argv.slice(2);
  if (action === 'diagnose') {
    requireValue(process.argv.length === 3, 'Use diagnose with no scope, overrides or approval arguments.');
    const workspace = realpathSync.native(process.cwd());
    requireValue(key(workspace) === key(realpathSync.native(resolve(dirname(fileURLToPath(import.meta.url)), '..'))),
      'Run the read-only diagnostic from its Mesh workspace.');
    const databasePath = resolve(workspace, 'data/workroom-preview/tasks.sqlite');
    const relayPath = resolve('D:/Dev/Onoes-Relay/.private/relay.sqlite3'), hermesPath = resolve(homedir(), 'AppData/Local/hermes/state.db');
    const report = inspectRetainedRecords({ databasePath, databaseIdentity: databaseFileIdentity(databasePath),
      relay: { path: relayPath, identity: databaseFileIdentity(relayPath) },
      hermes: { path: hermesPath, identity: databaseFileIdentity(hermesPath) } });
    process.stdout.write(JSON.stringify(report) + '\n');
    return;
  }
  requireValue(action && scopePath && scopeSha256 && planPath && !extra.length &&
    (action === 'apply' ? authorizationPath && authorizationSha256 : !authorizationPath && !authorizationSha256),
  'Usage: diagnose (read-only), or <prepare|inspect|apply> <absolute-scope.json> <reviewed-scope-sha256> <plan.json> [<absolute-owner-record.json> <reviewed-owner-sha256>]. No pause, resume or restart action exists.');
  const result = await runLegacyOperator({ action, scopePath, scopeSha256, planPath, authorizationPath, authorizationSha256 });
  process.stdout.write(JSON.stringify(result) + '\n');
}
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(error => { process.stderr.write(error.message + '\n'); process.exitCode = 1; });
}
