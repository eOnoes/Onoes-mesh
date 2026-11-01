import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import { DatabaseSync } from 'node:sqlite';
import path from 'node:path';
import { openTaskStore } from '../lib/task-store.mjs';
import { ROOT } from '../server.mjs';

test('M3 startup retires approved and running attempts atomically once, without executing or inventing observations', async () => {
  const directory = path.join(ROOT, `test/app03-m3-crash-recovery-store-${randomUUID()}`);
  await mkdir(directory, { recursive: true }); const filename = path.join(directory, 'tasks.sqlite');
  let store = openTaskStore(filename); const active = [];
  for (const state of ['approved','running']) {
    const task = store.create({ title: 'Interrupted ' + state });
    const pending = store.propose(task.id, { proposal: { command: 'node --version', cwd: '.' }, revision: task.revision });
    const claimed = store.decide(task.id, { revision: pending.revision }, true, { argv: [process.execPath, '--version'], cwd: ROOT }).task;
    if (state === 'running') store.running(task.id, claimed.execution.id);
    active.push(store.get(task.id));
  }
  store.close(); store = openTaskStore(filename);
  const recovered = active.map(task => store.get(task.id));
  for (let i = 0; i < active.length; i++) {
    const before = active[i]; const after = recovered[i];
    assert.equal(after.execution.state, 'failed'); assert.equal(after.proposalStatus, 'failed');
    assert.equal(after.status, 'open'); assert.equal(after.execution.id, before.execution.id);
    assert.equal(after.revision, before.revision + 1); assert.equal(after.execution.result.outcome, 'unknown');
    for (const field of ['rootPid','rootExitCode','stdout','stderr','cleanupVerified','timedOut']) assert.equal(after.execution.result[field], null);
    assert.deepEqual(store.approvalReplay(after.id, { revision: before.execution.approvalRevision }), after);
  }
  store.close(); store = openTaskStore(filename); assert.deepEqual(store.list(), recovered); store.close();
  // Unknown recovery is a strict local persistence variant. A fabricated
  // observation must fail the read-only preflight without changing any data.
  let db = new DatabaseSync(filename);
  const result = { ...recovered[0].execution.result, cleanupVerified: true };
  db.prepare('UPDATE task_executions SET result=? WHERE id=?').run(JSON.stringify(result), recovered[0].execution.id); db.close();
  assert.throws(() => openTaskStore(filename), /Invalid interrupted execution persistence/);
  db = new DatabaseSync(filename, { readOnly: true });
  assert.deepEqual(JSON.parse(db.prepare('SELECT result FROM task_executions WHERE id=?').get(recovered[0].execution.id).result), result);
  assert.equal(db.prepare('SELECT revision FROM tasks WHERE id=?').get(recovered[0].id).revision, recovered[0].revision);
  db.close();
});
