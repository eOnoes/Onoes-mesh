import {createHash, randomUUID} from 'node:crypto';

const POLL_MS = 60_000;
const iso = value => new Date(value).toISOString();
const digest = value => createHash('sha256').update(value).digest('hex');
const human = value => String(value ?? '').slice(0, 500)
  .replace(/\bBearer\s+\S+/gi, 'Bearer [redacted]')
  .replace(/\b(?:api[_-]?key|token|password|secret)\s*[:=]\s*\S+/gi, '[redacted]');

export function createRookStore(db) {
  db.exec(`CREATE TABLE IF NOT EXISTS workroom_rook_runtime(
    id INTEGER PRIMARY KEY CHECK(id=1), ownerId TEXT NOT NULL DEFAULT '', ownerPid INTEGER,
    state TEXT NOT NULL DEFAULT 'not_configured', heartbeatAt TEXT, lastResult TEXT NOT NULL DEFAULT 'never',
    failureCode TEXT NOT NULL DEFAULT '');
    INSERT OR IGNORE INTO workroom_rook_runtime(id) VALUES(1);
    CREATE TABLE IF NOT EXISTS workroom_rook_reports(
    id TEXT PRIMARY KEY, eventKey TEXT NOT NULL UNIQUE, taskId TEXT NOT NULL,
    kind TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
    createdAt TEXT NOT NULL, deliveredAt TEXT);`);
  const snapshot = () => ({...db.prepare('SELECT * FROM workroom_rook_runtime WHERE id=1').get()});
  const owns = owner => snapshot().ownerId === owner;
  function transaction(fn) {
    if (db.isTransaction) throw Error('Rook lease requires its own transaction');
    db.exec('BEGIN IMMEDIATE');
    try { const result = fn(); db.exec('COMMIT'); return result; }
    catch (error) { db.exec('ROLLBACK'); throw error; }
  }
  return {
    snapshot, owns,
    acquire(owner, pid, at, previousOwnerGone) {
      if (!Number.isSafeInteger(pid) || pid < 1) throw Error('Invalid scheduler process identity');
      return transaction(() => {
        const old = snapshot();
        if (old.ownerId && old.ownerId !== owner && previousOwnerGone(old.ownerPid) !== true) return false;
        db.prepare("UPDATE workroom_rook_runtime SET ownerId=?,ownerPid=?,state=CASE WHEN failureCode!='' THEN 'failing' ELSE 'running' END,heartbeatAt=? WHERE id=1")
          .run(owner, pid, iso(at));
        return true;
      });
    },
    touch(owner, state, result, at, failureCode = '') {
      const changed = db.prepare('UPDATE workroom_rook_runtime SET state=?,lastResult=?,heartbeatAt=?,failureCode=? WHERE id=1 AND ownerId=?')
        .run(state, result, iso(at), failureCode, owner);
      if (changed.changes !== 1) throw Error('Rook scheduler owner changed');
    },
    release(owner, at) {
      db.prepare("UPDATE workroom_rook_runtime SET ownerId='',ownerPid=NULL,state='paused',heartbeatAt=? WHERE id=1 AND ownerId=?")
        .run(iso(at), owner);
    },
    enqueue(eventKey, payload, at) {
      const id = digest(eventKey);
      db.prepare('INSERT OR IGNORE INTO workroom_rook_reports(id,eventKey,taskId,kind,payload,createdAt) VALUES(?,?,?,?,?,?)')
        .run(id, eventKey, payload.taskId ?? '', payload.kind, JSON.stringify(payload), iso(at));
      return id;
    },
    reports({pending = false, newest = false, limit = 20} = {}) {
      if (!Number.isSafeInteger(limit) || limit < 1 || limit > 100) throw Error('Invalid report limit');
      return db.prepare(`SELECT * FROM workroom_rook_reports ${pending ? "WHERE state!='delivered'" : ''} ORDER BY rowid ${newest && !pending ? 'DESC' : 'ASC'} LIMIT ?`)
        .all(limit).map(row => ({...row, payload: JSON.parse(row.payload)}));
    },
    reportState(id, state, at) {
      if (!['sending', 'unknown', 'delivered'].includes(state)) throw Error('Invalid report state');
      db.prepare('UPDATE workroom_rook_reports SET state=?,deliveredAt=? WHERE id=?')
        .run(state, state === 'delivered' ? iso(at) : null, id);
    },
  };
}

function ownerGone(pid) {
  if (!Number.isSafeInteger(pid) || pid < 1) return false;
  try { process.kill(pid, 0); return false; }
  catch (error) { return error.code === 'ESRCH'; }
}

/** Internal capability only. No credentials, model client, HTTP control or worker dispatch. */
export function createRookRuntime({store, flow, board, identity = null, verifyIdentity = () => false,
  enabled = false, transport = null, source = 'none', now = Date.now,
  schedule = setTimeout, cancel = clearTimeout, previousOwnerGone = ownerGone,
  ownerPid = process.pid} = {}) {
  const owner = randomUUID();
  let active = false, timer = null, busy = null, localFailure = '', closed = false;
  const clock = () => {
    const value = now();
    if (!Number.isSafeInteger(value) || !Number.isFinite(new Date(value).getTime())) throw Error('Invalid Rook clock');
    return value;
  };
  const approved = () => {
    try { return identity?.id === 'rook' && typeof identity.approvalRef === 'string'
      && identity.approvalRef.length > 0 && verifyIdentity(identity) === true; }
    catch { return false; }
  };
  const reportingReady = () => typeof transport?.send === 'function' && typeof transport?.lookup === 'function';
  const current = () => active && approved() && store.owns(owner);
  function failure(code) {
    localFailure = code;
    try {
      const old = store.snapshot();
      if (old.ownerId !== owner) return;
      if (!old.failureCode) store.enqueue(`failure:${owner}:${clock()}`,
        {kind: 'watcher_failed', summary: 'Rook needs attention; inspect its saved health status.'}, clock());
      store.touch(owner, 'failing', old.lastResult, clock(), code);
    } catch { /* Failure in the watcher must not bring down Mesh. */ }
  }
  function status() {
    const base = {id: 'rook', name: 'Rook', schema: 'mesh-rook-runtime/v1', source,
      scheduler: {kind: 'mesh_timer', installed: active, enabled: active && approved()},
      writerClearance: false};
    if (!approved()) return {...base, status: 'not_configured', reason: 'Rook identity is not verified.'};
    if (!reportingReady()) return {...base, status: 'unavailable', reason: 'Rook reporting is not configured.'};
    try {
      const row = store.snapshot();
      if (!active) return {...base, status: localFailure ? 'failing' : 'paused', reason: localFailure || 'Rook is paused.', lastResult: row.lastResult};
      if (row.ownerId !== owner) return {...base, status: 'unavailable', reason: 'Another scheduler owns this board.'};
      const age = clock() - Date.parse(row.heartbeatAt);
      if (!Number.isFinite(age) || age < 0 || age > 2 * POLL_MS) return {...base, status: 'unavailable', reason: 'Rook health observation expired.'};
      return {...base, status: row.state, ownerPid: row.ownerPid, heartbeatAt: row.heartbeatAt,
        lastResult: row.lastResult, reason: row.failureCode || '', pendingReports: store.reports({pending: true}).length};
    } catch { return {...base, status: 'unavailable', reason: 'Rook state is unavailable.'}; }
  }
  function observe(tasks, at) {
    for (const task of tasks) {
      const common = {taskId: task.id, title: human(task.title), lead: human(task.workroom?.owner)};
      if (task.flow?.claim) store.enqueue(`claim:${task.flow.claim.claimId}`,
        {...common, kind: 'claim_saved', claimId: task.flow.claim.claimId,
          summary: 'Claim saved; inspect the original intake and dispatch record.'}, at);
      if (task.flow?.state === 'clarification') store.enqueue(`question:${task.id}:${task.flow.revision}`,
        {...common, kind: 'needs_input', questionRevision: task.flow.revision,
          summary: 'Clarification requested. Answer the specific saved question on this card.'}, at);
      if (task.flow?.state === 'failed') store.enqueue(`failed:${task.id}:${task.flow.revision}`,
        {...common, kind: 'failed', summary: 'The original attempt needs reconciliation; no retry was authorized.'}, at);
      if (task.workroom?.stage === 'done' && task.progress?.decision === 'approved') store.enqueue(`done:${task.id}:${task.progress.revision}`,
        {...common, kind: 'ready_for_review', summary: task.flow?.ownerDecision === 'accepted'
          ? 'Eddie accepted the independently reviewed result.' : 'Independently reviewed result is ready for Eddie.'}, at);
    }
  }
  async function bounded(fn) {
    const controller = new AbortController();
    let timeout;
    try {
      return await Promise.race([Promise.resolve().then(() => fn(controller.signal)), new Promise((_, reject) => {
        timeout = setTimeout(() => { controller.abort(); reject(Error('Rook observation timed out')); }, 4000);
      })]);
    } finally { clearTimeout(timeout); }
  }
  async function flush() {
    for (const report of store.reports({pending: true, limit: 5})) {
      if (!current()) return;
      let ack;
      if (report.state !== 'pending') {
        ack = await bounded(signal => transport.lookup(report.id, {signal}));
      } else {
        store.reportState(report.id, 'sending', clock());
        try { ack = await bounded(signal => transport.send({id: report.id, ...report.payload}, {signal})); }
        catch { if (store.owns(owner)) store.reportState(report.id, 'unknown', clock()); throw Error('Report delivery uncertain'); }
      }
      if (!current()) return;
      if (ack?.id !== report.id || ack?.accepted !== true) {
        store.reportState(report.id, 'unknown', clock());
        throw Error('Report acknowledgement unverified');
      }
      store.reportState(report.id, 'delivered', clock());
    }
  }
  function tick() {
    if (busy) return busy;
    if (!current()) return active ? pause().then(() => ({status: 'paused'})) : Promise.resolve({status: 'paused'});
    const operation = Promise.resolve().then(async () => {
      let phase = 'sweep';
      try {
        if (!current()) return {status: 'paused'};
        const at = clock();
        const sweep = flow.scheduledSweep(at);
        const previous = store.snapshot();
        store.touch(owner, previous.state, sweep.status === 'not_due' ? previous.lastResult : sweep.status, at, previous.failureCode);
        phase = 'board';
        const tasks = await bounded(() => board());
        if (!current()) return {status: 'paused'};
        observe(tasks, at);
        phase = 'reports';
        await flush();
        if (!current()) return {status: 'paused'};
        const old = store.snapshot();
        if (old.failureCode) store.enqueue(`recovery:${owner}:${at}`,
          {kind: 'watcher_recovered', summary: 'Rook reporting recovered; original claims are unchanged.'}, at);
        store.touch(owner, 'running', sweep.status === 'not_due' ? old.lastResult : sweep.status, clock());
        localFailure = '';
        return sweep;
      } catch { failure(phase === 'reports' ? 'ROOK_REPORT_UNCERTAIN' : phase === 'board' ? 'ROOK_BOARD_UNAVAILABLE' : 'ROOK_SWEEP_FAILED'); return {status: 'failed'}; }
    });
    busy = operation;
    void operation.finally(() => {
      if (busy === operation) busy = null;
      if (active && !approved()) void pause().catch(() => {});
    }).catch(() => {});
    return operation;
  }
  function arm(delay) {
    if (!active || timer !== null) return;
    try {
      timer = schedule(() => {
        timer = null;
        void tick().finally(() => arm(POLL_MS)).catch(() => failure('ROOK_TIMER_FAILED'));
      }, delay);
      timer?.unref?.();
    } catch { active = false; failure('ROOK_TIMER_FAILED'); }
  }
  function start() {
    if (closed || active || !enabled || !approved() || !reportingReady()) return status();
    try {
      if (!store.acquire(owner, ownerPid, clock(), previousOwnerGone)) {
        localFailure = 'SCHEDULER_OWNER_UNAVAILABLE';
        return status();
      }
      active = true;
      arm(0);
    } catch { failure('ROOK_START_FAILED'); }
    return status();
  }
  async function pause() {
    active = false;
    if (timer !== null) { cancel(timer); timer = null; }
    await busy;
    try { store.release(owner, clock()); } catch { localFailure = 'ROOK_STATE_UNAVAILABLE'; }
    return status();
  }
  return {start, tick, status, pause, reports: () => store.reports({newest: true}),
    close: async () => { closed = true; return pause(); }};
}
