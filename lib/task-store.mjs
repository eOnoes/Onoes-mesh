import { DatabaseSync } from 'node:sqlite';
import { existsSync, openSync, readSync, closeSync } from 'node:fs';
import { randomUUID, createHash } from 'node:crypto';
import path from 'node:path';
import { validateProposal, validateProposalRequest } from './command-proposals.mjs';
import { validateOwnedResult, EXECUTION_ROOT, GIT } from './command-execution.mjs';

export class TaskError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
const keys = ['title', 'description', 'label', 'status', 'revision'];
function validateRelayIdentity({ scope, conversationId, messageId }) {
  if (scope !== 'relay:mesh' || typeof conversationId !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(conversationId) ||
      typeof messageId !== 'string' || !/^[A-Za-z0-9_-]{1,80}$/.test(messageId)) throw new TaskError(400, 'Invalid Relay identity.');
}
export function validateTask(body, editing = false) {
  if (!body || typeof body !== 'object' || Array.isArray(body) ||
      Object.keys(body).some(k => !keys.includes(k))) throw new TaskError(400, 'Invalid task fields.');
  if (typeof body.title !== 'string' || !body.title.trim() || body.title.length > 160 || /[\u0000-\u001f]/u.test(body.title))
    throw new TaskError(400, 'Title must be 1–160 characters without control characters.');
  const description = body.description === undefined ? '' : body.description;
  const label = body.label === undefined ? '' : body.label;
  const status = body.status === undefined ? 'open' : body.status;
  if (typeof description !== 'string' || description.length > 4000 || description.includes('\0'))
    throw new TaskError(400, 'Description must be at most 4000 characters.');
  if (typeof label !== 'string' || label.length > 80 || /[\u0000-\u001f]/u.test(label))
    throw new TaskError(400, 'Label must be at most 80 characters without control characters.');
  if (!['open', 'done'].includes(status)) throw new TaskError(400, 'Status must be open or done.');
  if (editing ? !Number.isSafeInteger(body.revision) || body.revision < 1 : body.revision !== undefined)
    throw new TaskError(400, 'A valid current revision is required for edits only.');
  return { title: body.title.trim(), description, label: label.trim(), status, revision: body.revision };
}
const schema = `CREATE TABLE tasks (
 id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL, label TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('open','done')), revision INTEGER NOT NULL CHECK(revision > 0),
 createdAt TEXT NOT NULL, updatedAt TEXT NOT NULL
); PRAGMA user_version = 1;`;
const proposalSchema = `CREATE TABLE task_proposals (
 taskId TEXT PRIMARY KEY REFERENCES tasks(id), command TEXT NOT NULL,
 cwd TEXT NOT NULL CHECK(cwd = '.'), status TEXT NOT NULL CHECK(status = 'pending')
); PRAGMA user_version = 2;`;
const executionSchema = `CREATE TABLE task_executions (
 id TEXT PRIMARY KEY, taskId TEXT NOT NULL REFERENCES tasks(id), proposalRevision INTEGER NOT NULL,
 command TEXT NOT NULL, cwd TEXT NOT NULL, actualCwd TEXT NOT NULL, argv TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('approved','running','completed','failed')),
 startedAt TEXT NOT NULL, finishedAt TEXT, result TEXT
);
CREATE TABLE task_proposal_decisions (
 taskId TEXT PRIMARY KEY REFERENCES tasks(id), proposalRevision INTEGER NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pending','approved','running','completed','failed','denied')),
 executionId TEXT REFERENCES task_executions(id)
);
INSERT INTO task_proposal_decisions SELECT p.taskId,t.revision,'pending',NULL FROM task_proposals p JOIN tasks t ON t.id=p.taskId;
PRAGMA user_version = 3;`;
const replaySchema = `ALTER TABLE task_executions ADD COLUMN approvalRevision INTEGER NOT NULL DEFAULT 1;
UPDATE task_executions SET approvalRevision=proposalRevision;
PRAGMA user_version = 4;`;
const relaySchema = `CREATE TABLE relay_task_links (
 scope TEXT NOT NULL, conversationId TEXT NOT NULL, messageId TEXT NOT NULL,
 taskId TEXT NOT NULL REFERENCES tasks(id), messageHash TEXT NOT NULL,
 PRIMARY KEY(scope,conversationId,messageId)
); PRAGMA user_version = 5;`;
// Recovery records an absence of evidence, not an ownership-bridge result.
// Null fields must remain unknown: neither empty output nor false cleanup is
// an observation that startup can make about an interrupted command.
const interruptedResult = () => ({ status: 'UNKNOWN', outcome: 'unknown', reason: 'server_restart',
  rootPid: null, rootExitCode: null, timedOut: null, cleanupVerified: null,
  error: 'Execution interrupted by server restart; outcome and cleanup are unknown. No automatic retry.',
  stdout: null, stderr: null });
function validateInterruptedResult(result) {
  const expected = interruptedResult();
  if (!result || typeof result !== 'object' || Array.isArray(result) ||
      Object.keys(result).sort().join(',') !== Object.keys(expected).sort().join(',') ||
      Object.entries(expected).some(([key, value]) => result[key] !== value))
    throw new Error('Invalid interrupted execution persistence.');
  return result;
}
function decisionRequest(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body) || Object.keys(body).join(',') !== 'revision' ||
      !Number.isSafeInteger(body.revision) || body.revision < 1)
    throw new TaskError(400, 'Provide exactly the current task revision.');
  return body.revision;
}
// Persistence admits only the same three exact product plans as the bridge.
function fixedArgv(command) {
  if (command === 'node --version') return [process.execPath, '--version'];
  if (command === 'git status') return [GIT, 'status'];
  if (command === 'node lib/slow-command.mjs') return [process.execPath, path.join(EXECUTION_ROOT, 'lib', 'slow-command.mjs')];
  return null;
}
function matchesArgv(command, argv) {
  const expected = fixedArgv(command);
  return expected && Array.isArray(argv) && argv.length === expected.length && expected.every((value, i) => argv[i] === value);
}
export function openTaskStore(filename) {
  // Inspect existing data read-only before additive migration.
  let version = 1;
  if (existsSync(filename)) {
    const fd = openSync(filename, 'r'); const header = Buffer.alloc(16);
    try { readSync(fd, header, 0, 16, 0); } finally { closeSync(fd); }
    if (header.toString() !== 'SQLite format 3\0') throw new Error('Invalid persistence.');
    const check = new DatabaseSync(filename, { readOnly: true });
    try {
      version = check.prepare('PRAGMA user_version').get().user_version;
      if (check.prepare('PRAGMA quick_check').get().quick_check !== 'ok' || ![1, 2, 3, 4, 5].includes(version) ||
          check.prepare('PRAGMA foreign_key_check').all().length)
        throw new Error('Invalid persistence.');
      const columns = check.prepare('PRAGMA table_info(tasks)').all().map(x => x.name);
      if (columns.join(',') !== 'id,title,description,label,status,revision,createdAt,updatedAt') throw new Error('Invalid persistence.');
      for (const row of check.prepare('SELECT * FROM tasks').all()) {
        validateTask({ title: row.title, description: row.description, label: row.label, status: row.status, revision: row.revision }, true);
        if (!/^[0-9a-f-]{36}$/.test(row.id) || !Number.isFinite(Date.parse(row.createdAt)) || !Number.isFinite(Date.parse(row.updatedAt))) throw new Error('Invalid persistence.');
      }
      if (version >= 2) {
        if (check.prepare('PRAGMA table_info(task_proposals)').all().map(x => x.name).join(',') !== 'taskId,command,cwd,status')
          throw new Error('Invalid proposal persistence.');
        for (const row of check.prepare('SELECT * FROM task_proposals').all()) {
          validateProposal({ command: row.command, cwd: row.cwd });
          if (row.status !== 'pending' || !check.prepare('SELECT id FROM tasks WHERE id=?').get(row.taskId))
            throw new Error('Invalid proposal persistence.');
        }
      } else if (check.prepare("SELECT name FROM sqlite_master WHERE name='task_proposals'").get()) {
        throw new Error('Unexpected proposal persistence.');
      }
      if (version >= 3) {
        if (check.prepare('PRAGMA table_info(task_executions)').all().map(x => x.name).join(',') !== 'id,taskId,proposalRevision,command,cwd,actualCwd,argv,state,startedAt,finishedAt,result' + (version >= 4 ? ',approvalRevision' : '') ||
            check.prepare('PRAGMA table_info(task_proposal_decisions)').all().map(x => x.name).join(',') !== 'taskId,proposalRevision,status,executionId') throw new Error('Invalid execution persistence.');
        for (const run of check.prepare('SELECT * FROM task_executions').all()) {
          validateProposal({ command: run.command, cwd: run.cwd });
          const argv = JSON.parse(run.argv);
          if (!matchesArgv(run.command, argv) || run.actualCwd !== EXECUTION_ROOT ||
              !Number.isSafeInteger(run.proposalRevision) || run.proposalRevision < 1 ||
              (version >= 4 && (!Number.isSafeInteger(run.approvalRevision) || run.approvalRevision < run.proposalRevision)) ||
              !['approved','running','completed','failed'].includes(run.state) || !Number.isFinite(Date.parse(run.startedAt))) throw new Error('Invalid execution persistence.');
          if (['completed','failed'].includes(run.state)) {
            const saved = JSON.parse(run.result);
            const result = saved?.status === 'UNKNOWN' ? validateInterruptedResult(saved) : validateOwnedResult(saved);
            if (!Number.isFinite(Date.parse(run.finishedAt)) ||
                (result.status === 'UNKNOWN' ? run.state !== 'failed' : result.status !== (run.state === 'completed' ? 'PASS' : 'FAIL')))
              throw new Error('Invalid execution result persistence.');
          } else if (run.result !== null || run.finishedAt !== null) throw new Error('Invalid active execution persistence.');
        }
        for (const row of check.prepare('SELECT * FROM task_proposal_decisions').all()) {
          const proposal = check.prepare('SELECT * FROM task_proposals WHERE taskId=?').get(row.taskId);
          const run = row.executionId ? check.prepare('SELECT * FROM task_executions WHERE id=?').get(row.executionId) : null;
          if (!proposal || !Number.isSafeInteger(row.proposalRevision) || row.proposalRevision < 1 ||
              !['pending','approved','running','completed','failed','denied'].includes(row.status) ||
              (['pending','denied'].includes(row.status) ? row.executionId !== null :
                !run || run.taskId !== row.taskId || run.proposalRevision !== row.proposalRevision || run.state !== row.status || run.command !== proposal.command || run.cwd !== proposal.cwd))
            throw new Error('Invalid proposal decision persistence.');
        }
        if (check.prepare('SELECT taskId FROM task_proposals EXCEPT SELECT taskId FROM task_proposal_decisions').all().length)
          throw new Error('Missing proposal decision persistence.');
      } else if (check.prepare("SELECT name FROM sqlite_master WHERE name IN ('task_executions','task_proposal_decisions')").get()) throw new Error('Unexpected execution persistence.');
      if (version >= 5) {
        if (check.prepare('PRAGMA table_info(relay_task_links)').all().map(x => x.name).join(',') !== 'scope,conversationId,messageId,taskId,messageHash') throw new Error('Invalid Relay link persistence.');
        for (const row of check.prepare('SELECT * FROM relay_task_links').all()) {
          validateRelayIdentity(row);
          if (!/^[0-9a-f]{64}$/.test(row.messageHash) || !check.prepare('SELECT id FROM tasks WHERE id=?').get(row.taskId)) throw new Error('Invalid Relay reference.');
        }
      } else if (check.prepare("SELECT name FROM sqlite_master WHERE name='relay_task_links'").get()) throw new Error('Unexpected Relay persistence.');
    } finally { check.close(); }
  }
  const fresh = !existsSync(filename);
  const db = new DatabaseSync(filename);
  try {
    db.exec('PRAGMA busy_timeout = 2000; PRAGMA foreign_keys = ON;');
    db.exec('BEGIN IMMEDIATE;');
    if (fresh) db.exec(schema);
    if (version === 1) db.exec(proposalSchema);
    if (version < 3) db.exec(executionSchema);
    if (version < 4) db.exec(replaySchema);
    if (version < 5) db.exec(relaySchema);
    // Before the server can admit requests, retire every active attempt with no
    // recorded result. Keep its identity/replay interval and terminalize once.
    // finishedAt is the recovery record time, not an observed process exit.
    const interrupted = db.prepare("SELECT id,taskId FROM task_executions WHERE state IN ('approved','running') AND result IS NULL").all();
    const now = new Date().toISOString();
    for (const run of interrupted) {
      db.prepare("UPDATE task_executions SET state='failed',finishedAt=?,result=? WHERE id=?")
        .run(now, JSON.stringify(interruptedResult()), run.id);
      db.prepare("UPDATE task_proposal_decisions SET status='failed' WHERE taskId=? AND executionId=? AND status IN ('approved','running')")
        .run(run.taskId, run.id);
    }
    for (const taskId of new Set(interrupted.map(run => run.taskId)))
      db.prepare('UPDATE tasks SET revision=revision+1,updatedAt=? WHERE id=?').run(now, taskId);
    db.exec('COMMIT;');
  }
  catch (e) { db.close(); throw e; }
  const withProposal = task => {
    if (!task) return task;
    const row = db.prepare('SELECT command,cwd,status FROM task_proposals WHERE taskId=?').get(task.id);
    if (!row) return task;
    const decision = db.prepare('SELECT * FROM task_proposal_decisions WHERE taskId=?').get(task.id);
    const run = decision.executionId ? db.prepare('SELECT * FROM task_executions WHERE id=?').get(decision.executionId) : null;
    return { ...task, proposal: { command: row.command, cwd: row.cwd }, proposalStatus: decision.status,
      execution: run ? { ...run, argv: JSON.parse(run.argv), result: run.result ? JSON.parse(run.result) : null } : null };
  };
  const get = id => withProposal(db.prepare('SELECT * FROM tasks WHERE id = ?').get(id));
  const approvalReplay = (id, body) => {
    const revision = decisionRequest(body);
    const task = get(id);
    if (!task) throw new TaskError(404, 'Task not found.');
    // Only the current proposal's recorded execution can be replayed. A saved
    // replacement clears executionId, even when its command tuple is identical.
    if (task.execution && revision >= task.execution.approvalRevision && revision <= task.revision) return task;
    if (task.revision !== revision || task.proposalStatus !== 'pending')
      throw new TaskError(409, 'Proposal changed or already decided. Reload current task.');
    return null;
  };
  return {
    list: () => db.prepare('SELECT * FROM tasks ORDER BY createdAt, id').all().map(withProposal),
    get,
    approvalReplay,
    relayReference({ scope, conversationId, messageId }) {
      validateRelayIdentity({ scope, conversationId, messageId });
      return db.prepare('SELECT taskId FROM relay_task_links WHERE scope=? AND conversationId=? AND messageId=?').get(scope, conversationId, messageId)?.taskId ?? null;
    },
    // Trusted adapter only: one SQLite transaction owns identity and task creation.
    // No proposal, decision or execution field is accepted by this interface.
    linkRelay({ scope, conversationId, messageId, text }) {
      validateRelayIdentity({ scope, conversationId, messageId });
      if (typeof text !== 'string' || !text.trim() || text.length > 4000 || text.includes('\0')) throw new TaskError(400, 'Invalid Relay message.');
      const messageHash = createHash('sha256').update(text).digest('hex');
      const title = text.replace(/[\u0000-\u001f]/gu, ' ').trim().slice(0, 160);
      const t = validateTask({ title, description: text, label: 'Relay' });
      db.exec('BEGIN IMMEDIATE;');
      try {
        const previous = db.prepare('SELECT taskId,messageHash FROM relay_task_links WHERE scope=? AND conversationId=? AND messageId=?').get(scope, conversationId, messageId);
        if (previous && previous.messageHash !== messageHash) throw new TaskError(409, 'Relay message identity already used with different text.');
        let taskId = previous?.taskId;
        if (!taskId) {
          taskId = randomUUID(); const now = new Date().toISOString();
          db.prepare('INSERT INTO tasks VALUES (?,?,?,?,?,1,?,?)').run(taskId, t.title, t.description, t.label, t.status, now, now);
          db.prepare('INSERT INTO relay_task_links VALUES (?,?,?,?,?)').run(scope, conversationId, messageId, taskId, messageHash);
        }
        db.exec('COMMIT;');
        return { taskId, duplicate: Boolean(previous) };
      } catch (error) { db.exec('ROLLBACK;'); throw error; }
    },
    cancelTarget(id, body) {
      if (!body || typeof body !== 'object' || Array.isArray(body) ||
          Object.keys(body).sort().join(',') !== 'revision,runId' || typeof body.runId !== 'string')
        throw new TaskError(400, 'Provide exactly the current revision and runId.');
      const revision = decisionRequest({ revision: body.revision });
      const task = get(id);
      if (!task) throw new TaskError(404, 'Task not found.');
      if (task.revision !== revision || task.proposalStatus !== 'running' ||
          task.execution?.state !== 'running' || task.execution.id !== body.runId)
        throw new TaskError(409, 'Run changed or already finished. Reload current task.');
      return task.execution.id;
    },
    create(body) {
      const t = validateTask(body); const id = randomUUID(); const now = new Date().toISOString();
      db.prepare('INSERT INTO tasks VALUES (?,?,?,?,?,1,?,?)').run(id, t.title, t.description, t.label, t.status, now, now);
      return get(id);
    },
    update(id, body) {
      const t = validateTask(body, true);
      const result = db.prepare('UPDATE tasks SET title=?, description=?, label=?, status=?, revision=revision+1, updatedAt=? WHERE id=? AND revision=?')
        .run(t.title, t.description, t.label, t.status, new Date().toISOString(), id, t.revision);
      if (!result.changes) throw new TaskError(get(id) ? 409 : 404, get(id) ? 'Task changed. Reload current task before editing.' : 'Task not found.');
      return get(id);
    },
    propose(id, body) {
      const { proposal, revision } = validateProposalRequest(body);
      db.exec('BEGIN IMMEDIATE;');
      try {
        if (['approved','running'].includes(get(id)?.proposalStatus)) throw new TaskError(409, 'Command is busy. Reload the current task.');
        const result = db.prepare('UPDATE tasks SET revision=revision+1, updatedAt=? WHERE id=? AND revision=?')
          .run(new Date().toISOString(), id, revision);
        if (!result.changes) throw new TaskError(get(id) ? 409 : 404,
          get(id) ? 'Task changed. Reload current task before proposing.' : 'Task not found.');
        db.prepare("INSERT INTO task_proposals VALUES (?,?,?,'pending') ON CONFLICT(taskId) DO UPDATE SET command=excluded.command,cwd=excluded.cwd,status='pending'")
          .run(id, proposal.command, proposal.cwd);
        db.prepare("INSERT INTO task_proposal_decisions VALUES (?,?,'pending',NULL) ON CONFLICT(taskId) DO UPDATE SET proposalRevision=excluded.proposalRevision,status='pending',executionId=NULL")
          .run(id, revision + 1);
        db.exec('COMMIT;');
      } catch (error) { db.exec('ROLLBACK;'); throw error; }
      return get(id);
    },
    decide(id, body, approved, plan) {
      const revision = decisionRequest(body);
      db.exec('BEGIN IMMEDIATE;');
      try {
        if (approved) {
          const replay = approvalReplay(id, body);
          if (replay) { db.exec('COMMIT;'); return { task: replay, replayed: true }; }
        }
        const task = get(id);
        if (!task) throw new TaskError(404, 'Task not found.');
        if (task.revision !== revision || task.proposalStatus !== 'pending') throw new TaskError(409, 'Proposal changed or already decided. Reload current task.');
        validateProposal(task.proposal);
        const decision = db.prepare('SELECT * FROM task_proposal_decisions WHERE taskId=?').get(id);
        const now = new Date().toISOString(); const runId = approved ? randomUUID() : null;
        if (approved) {
          if (!plan || plan.cwd !== EXECUTION_ROOT || !matchesArgv(task.proposal.command, plan.argv)) throw new TaskError(503, 'Ownership bridge unavailable.');
          db.prepare("INSERT INTO task_executions VALUES (?,?,?,?,?,?,?,'approved',?,NULL,NULL,?)")
            .run(runId, id, decision.proposalRevision, task.proposal.command, task.proposal.cwd, plan.cwd, JSON.stringify(plan.argv), now, revision);
        }
        db.prepare('UPDATE task_proposal_decisions SET status=?,executionId=? WHERE taskId=?').run(approved ? 'approved' : 'denied', runId, id);
        db.prepare('UPDATE tasks SET revision=revision+1,updatedAt=? WHERE id=?').run(now, id);
        db.exec('COMMIT;');
      } catch (error) { db.exec('ROLLBACK;'); throw error; }
      return { task: get(id), replayed: false };
    },
    running(id, runId) {
      db.exec('BEGIN IMMEDIATE;');
      try {
        if (!db.prepare("UPDATE task_executions SET state='running' WHERE id=? AND taskId=? AND state='approved'").run(runId, id).changes ||
            !db.prepare("UPDATE task_proposal_decisions SET status='running' WHERE taskId=? AND executionId=? AND status='approved'").run(id, runId).changes)
          throw new TaskError(503, 'Execution state unavailable.');
        db.exec('COMMIT;');
      } catch (error) { db.exec('ROLLBACK;'); throw error; }
    },
    finish(id, runId, result) {
      validateOwnedResult(result);
      const state = result.status === 'PASS' && result.rootExitCode === 0 && result.cleanupVerified === true && result.timedOut === false && result.error === null ? 'completed' : 'failed';
      db.exec('BEGIN IMMEDIATE;');
      try {
        if (!db.prepare('UPDATE task_executions SET state=?,finishedAt=?,result=? WHERE id=? AND taskId=? AND state=\'running\'')
          .run(state, new Date().toISOString(), JSON.stringify(result), runId, id).changes ||
            !db.prepare("UPDATE task_proposal_decisions SET status=? WHERE taskId=? AND executionId=? AND status='running'").run(state, id, runId).changes)
          throw new TaskError(503, 'Execution result persistence unavailable.');
        db.prepare('UPDATE tasks SET revision=revision+1,updatedAt=? WHERE id=?').run(new Date().toISOString(), id);
        db.exec('COMMIT;');
      } catch (error) { db.exec('ROLLBACK;'); throw error; }
      return get(id);
    },
    close: () => db.close()
  };
}
