import test from 'node:test';
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { DatabaseSync } from 'node:sqlite';
import path from 'node:path';
import { openTaskStore } from '../lib/task-store.mjs';
import { ROOT } from '../server.mjs';

test('M4 canonical SQLite: scoped idempotence, changed-message refusal, no execution and two-store reopen', async () => {
  const dir = path.join(ROOT, `test/app03-m4-link-store-${randomUUID()}`); await mkdir(dir);
  const filename = path.join(dir, 'tasks.sqlite');
  const identity = { scope: 'relay:mesh', conversationId: randomUUID(), messageId: 'message_1', text: 'node --version\nThis is a message, with no command approval.' };
  let store = openTaskStore(filename); const first = store.linkRelay(identity);
  assert.equal(first.duplicate, false);
  const second = openTaskStore(filename);
  assert.deepEqual(second.linkRelay(identity), { taskId: first.taskId, duplicate: true }); second.close();
  assert.equal(store.relayReference(identity), first.taskId);
  assert.equal(store.relayReference({...identity,messageId:'unadmitted'}),null);
  assert.throws(() => store.linkRelay({ ...identity, text: 'Changed message' }), e => e.status === 409);
  assert.throws(() => store.linkRelay({ ...identity, scope: 'other' }), e => e.status === 400);
  const task = store.get(first.taskId); assert.equal(task.status, 'open'); assert.equal(task.revision, 1); assert.equal(task.description, identity.text); assert.equal(task.proposal, undefined);
  store.close(); store = openTaskStore(filename);
  assert.deepEqual(store.linkRelay(identity), { taskId: first.taskId, duplicate: true });
  assert.equal(store.list().length, 1); store.close();
  const db = new DatabaseSync(filename);
  for (const name of ['task_proposals','task_proposal_decisions','task_executions']) assert.equal(db.prepare(`SELECT COUNT(*) AS n FROM ${name}`).get().n, 0);
  const rows = db.prepare('SELECT * FROM relay_task_links').all(); assert.equal(rows.length, 1); assert.equal(rows[0].taskId, first.taskId); db.close();
  await writeFile(path.join(dir, 'evidence.json'), JSON.stringify({ identity, task, rows, sameIdAfterReopen: true, executions: 0 }, null, 2));
});

test('M4 canonical SQLite: failed reference insert rolls back task and version4 migrates without changing existing task bytes', async () => {
  const dir = path.join(ROOT, `test/app03-m4-link-rollback-${randomUUID()}`); await mkdir(dir);
  const filename = path.join(dir, 'tasks.sqlite'); let store = openTaskStore(filename);
  const task = store.create({ title: 'Existing M3 task' }); store.close();
  const db = new DatabaseSync(filename);
  db.exec('DROP TABLE relay_task_links; PRAGMA user_version=4;'); db.close();
  store = openTaskStore(filename); assert.deepEqual(store.get(task.id), task);
  const hostile = new DatabaseSync(filename);
  hostile.exec("CREATE TRIGGER fail_link BEFORE INSERT ON relay_task_links BEGIN SELECT RAISE(ABORT,'test disk-like write failure'); END;");
  assert.throws(() => store.linkRelay({ scope:'relay:mesh',conversationId:randomUUID(),messageId:'rollback',text:'Must not leave an orphan task' }));
  assert.deepEqual(store.list(), [task]);
  assert.equal(hostile.prepare('SELECT COUNT(*) AS n FROM relay_task_links').get().n,0);
  hostile.close(); store.close();
});
