import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import path from 'node:path';
import { copyFile } from 'node:fs/promises';
import { openTaskStore } from '../lib/task-store.mjs';
import { fixture, request, mutate, admit, get, propose, rows, observe, delay, identity, slow } from './m3-crash-compose-fixture.mjs';

test('M3 composed API Cancel awaits real root/descendant cleanup, fences targets, persists and reopens actual failure', async t => {
  const f = await fixture(t, 'cancel'); const first = await f.boot(); const proof = await admit(first);
  const catalog = (await request(first, '/api/commands', { headers: proof })).json().commands;
  assert.deepEqual(catalog, [{ id: 'node-version', command: 'node --version', cwd: '.' },
    { id: 'git-status', command: 'git status', cwd: '.' }, { id: 'm3-slow', ...slow }]);
  const saved = await propose(first, proof, 'Actual API Cancel'); const other = await propose(first, proof, 'Other proposal remains pending');
  const route = `/api/tasks/${saved.id}`; const start = performance.now();
  const approved = await mutate(first, proof, route + '/approve', { revision: saved.revision }); assert.equal(approved.status, 202, approved.text);
  const running = approved.json().task; assert.equal(running.proposalStatus, 'running'); assert.equal(running.execution.result, null);
  const observer = await observe(f, first, 'cancel'); await delay(250);
  const body = { revision: running.revision, runId: running.execution.id };
  for (const invalid of [{ revision: saved.revision, runId: body.runId }, { ...body, runId: other.id },
    { revision: body.revision }, { ...body, controller: true }]) {
    const res = await mutate(first, proof, route + '/cancel', invalid); assert.equal(res.status, Object.keys(invalid).length === 2 ? 409 : 400);
  }
  assert.equal((await mutate(first, proof, `/api/tasks/${other.id}/cancel`, body)).status, 409);
  assert.equal((await mutate(first, {}, route + '/cancel', body)).status, 401);
  assert.equal((await mutate(first, { ...proof, 'X-Trial-CSRF': 'x'.repeat(43) }, route + '/cancel', body)).status, 403);
  const wrongOrigin = await request(first, route + '/cancel', { method: 'POST', headers: { ...proof,
    Origin: 'http://127.0.0.1:1', 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); assert.equal(wrongOrigin.status, 403);
  assert.deepEqual(await get(first, proof, saved.id), running);
  const cancelled = await mutate(first, proof, route + '/cancel', body); assert.equal(cancelled.status, 200, cancelled.text);
  const done = cancelled.json().task; const verified = await observer.finish('wait');
  assert.equal(done.status, 'open'); assert.equal(done.proposalStatus, 'failed'); assert.equal(done.execution.id, body.runId);
  const result = done.execution.result;
  assert.equal(result.status, 'FAIL'); assert.equal(result.cancelled, true); assert.equal(result.cleanupVerified, true); assert.equal(result.timedOut, false);
  assert.notEqual(result.rootExitCode, 0); assert.equal(result.rootPid, observer.ready.identities.find(i => i.role === 'root').pid);
  assert.match(result.stdout, /M3 slow root .* started/); assert.match(result.stdout, /M3 slow descendant .* started/); assert.doesNotMatch(result.stdout, /completed/);
  const elapsedMs = performance.now() - start; assert.ok(elapsedMs < 9000, String(elapsedMs));
  assert.equal((await mutate(first, proof, route + '/cancel', { revision: done.revision, runId: body.runId })).status, 409);
  const before = rows(f.filename); await f.stop(first); const second = await f.boot(Number(new URL(first.url).port)); const secondProof = await admit(second);
  assert.equal(second.url, first.url); assert.deepEqual(await get(second, secondProof, saved.id), done);
  assert.deepEqual(await get(second, secondProof, other.id), other);
  for (const revision of [saved.revision, running.revision, done.revision]) {
    const replay = await mutate(second, secondProof, route + '/approve', { revision }); assert.equal(replay.status, 200); assert.deepEqual(replay.json().task, done);
  }
  assert.deepEqual(rows(f.filename), before); assert.doesNotMatch(second.errors(), /M3_COMPOSE_NATIVE_SPAWN/);
  // Existing validation still rejects arbitrary persisted script/argv/cwd.
  for (const [column, value] of [['argv', JSON.stringify([process.execPath, 'lib/slow-command.mjs'])], ['actualCwd', '.']]) {
    const bad = path.join(f.directory, `invalid-${column}.sqlite`); await copyFile(f.filename, bad);
    const db = new DatabaseSync(bad); db.prepare(`UPDATE task_executions SET ${column}=?`).run(value); db.close();
    assert.throws(() => openTaskStore(bad), /Invalid execution persistence/);
  }
  // An old runId cannot revoke an explicitly approved identical replacement,
  // even when supplied with that replacement's current task revision.
  const replacement = await mutate(second, secondProof, route + '/proposal', { proposal: slow, revision: done.revision });
  assert.equal(replacement.status, 200);
  const nextApproval = await mutate(second, secondProof, route + '/approve', { revision: replacement.json().task.revision });
  assert.equal(nextApproval.status, 202); const nextRunning = nextApproval.json().task;
  const nextObserver = await observe(f, second, 'replacement'); await delay(250);
  assert.equal((await mutate(second, secondProof, route + '/cancel', { revision: nextRunning.revision, runId: body.runId })).status, 409);
  assert.equal((await mutate(second, secondProof, route + '/cancel', { revision: running.revision, runId: nextRunning.execution.id })).status, 409);
  assert.deepEqual(await get(second, secondProof, saved.id), nextRunning);
  const nextCancelled = await mutate(second, secondProof, route + '/cancel', { revision: nextRunning.revision, runId: nextRunning.execution.id });
  assert.equal(nextCancelled.status, 200); assert.equal(nextCancelled.json().task.execution.result.cancelled, true);
  await nextObserver.finish('wait');
  const final = rows(f.filename);
  assert.deepEqual(final.task_executions.find(run => run.id === body.runId), before.task_executions[0]);
  assert.equal(final.task_executions.length, 2); assert.deepEqual(await get(second, secondProof, other.id), other);
  await f.save('proof.json', { dataDir: f.dataDir, url: first.url, servers: f.children.map(a => a.identity), running, done, verified, elapsedMs, replacement: nextCancelled.json().task });
  console.log('M3 COMPOSE CANCEL ' + JSON.stringify({ dataDir: f.dataDir, taskId: saved.id, runId: body.runId, result, elapsedMs }));
});

test('M3 actual ten-second server crash: original retained process handles exit, same store/URL recovers UNKNOWN with no replay', async t => {
  const f = await fixture(t, 'crash'); const first = await f.boot(); const proof = await admit(first);
  const saved = await propose(first, proof, 'Actual slow-command server crash'); const route = `/api/tasks/${saved.id}`;
  const start = performance.now(); const approval = await mutate(first, proof, route + '/approve', { revision: saved.revision });
  assert.equal(approval.status, 202, approval.text); const running = approval.json().task;
  const observer = await observe(f, first, 'crash'); await delay(250);
  assert.deepEqual(await get(first, proof, saved.id), running); assert.equal(running.execution.result, null);
  const before = rows(f.filename); await f.save('before-crash.json', { running, rows: before });
  assert.deepEqual(identity(first.child.pid), first.identity);
  const verified = await observer.finish('kill-caller'); await first.closed; await f.logs(first);
  const elapsedMs = performance.now() - start; assert.ok(elapsedMs < 9000, String(elapsedMs));
  assert.ok(verified.identities.every(i => i.exitSignaled));
  const second = await f.boot(Number(new URL(first.url).port)); assert.equal(second.url, first.url);
  assert.equal((await request(second, route, { headers: proof })).status, 401);
  const secondProof = await admit(second); const recovered = await get(second, secondProof, saved.id);
  assert.equal(recovered.status, 'open'); assert.equal(recovered.proposalStatus, 'failed'); assert.equal(recovered.execution.state, 'failed');
  assert.equal(recovered.execution.id, running.execution.id); assert.equal(recovered.revision, running.revision + 1);
  for (const field of ['taskId','proposalRevision','approvalRevision','command','cwd','actualCwd','argv','startedAt']) assert.deepEqual(recovered.execution[field], running.execution[field]);
  assert.equal(recovered.execution.result.status, 'UNKNOWN'); assert.equal(recovered.execution.result.reason, 'server_restart');
  for (const field of ['rootPid','rootExitCode','stdout','stderr','timedOut','cleanupVerified']) assert.equal(recovered.execution.result[field], null);
  const after = rows(f.filename);
  for (const revision of [saved.revision, running.revision, recovered.revision]) {
    const replay = await mutate(second, secondProof, route + '/approve', { revision }); assert.equal(replay.status, 200); assert.deepEqual(replay.json().task, recovered);
  }
  assert.deepEqual(rows(f.filename), after); assert.doesNotMatch(second.errors(), /M3_COMPOSE_NATIVE_SPAWN/);
  assert.equal((await mutate(second, secondProof, route + '/cancel', { revision: recovered.revision, runId: running.execution.id })).status, 409);
  await f.stop(second); const third = await f.boot(Number(new URL(first.url).port)); const thirdProof = await admit(third);
  assert.equal(third.url, first.url); assert.deepEqual(await get(third, thirdProof, saved.id), recovered);
  assert.deepEqual((await mutate(third, thirdProof, route + '/approve', { revision: saved.revision })).json().task, recovered);
  assert.deepEqual(rows(f.filename), after); assert.doesNotMatch(third.errors(), /M3_COMPOSE_NATIVE_SPAWN/);
  assert.equal(first.errors().split('M3_COMPOSE_NATIVE_SPAWN').length - 1, 1);
  await f.save('proof.json', { dataDir: f.dataDir, url: first.url, servers: f.children.map(a => a.identity), running, recovered, verified, elapsedMs, before, after });
  console.log('M3 COMPOSE CRASH ' + JSON.stringify({ dataDir: f.dataDir, taskId: saved.id, runId: running.execution.id, servers: f.children.map(a => a.identity), result: recovered.execution.result, verified, elapsedMs }));
});
