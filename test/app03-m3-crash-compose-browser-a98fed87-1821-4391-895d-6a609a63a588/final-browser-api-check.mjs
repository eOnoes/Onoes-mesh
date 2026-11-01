import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { admit, mutate, get, rows } from '../m3-crash-compose-fixture.mjs';
const directory = new URL('.', import.meta.url);
const snapshot = rows(new URL('tasks.sqlite', directory).pathname.slice(1));
const afterCrash = JSON.parse(await readFile(new URL('browser-crash-1a0f2b96-9f59-4f52-8f76-355f09d40628-reopened.json', directory), 'utf8'));
assert.deepEqual(JSON.parse(JSON.stringify(snapshot)), afterCrash, 'Second actual browser-server restart preserves every original row');
const app = { url: 'http://127.0.0.1:61474' }; const proof = await admit(app);
const cancelled = await get(app, proof, '56bc18f9-f4d9-47ca-828f-7909083cb96d');
const recovered = await get(app, proof, '5802d13c-02ff-4512-b038-83465d0eae5f');
assert.equal(cancelled.execution.result.cancelled, true); assert.equal(cancelled.execution.result.cleanupVerified, true);
assert.equal(recovered.execution.id, '1a0f2b96-9f59-4f52-8f76-355f09d40628');
assert.equal(recovered.revision, 4); assert.equal(recovered.execution.result.status, 'UNKNOWN');
for (const revision of [2,3,4]) {
  const res = await mutate(app, proof, `/api/tasks/${recovered.id}/approve`, { revision });
  assert.equal(res.status, 200); assert.deepEqual(res.json().task, recovered);
}
assert.deepEqual(rows(new URL('tasks.sqlite', directory).pathname.slice(1)), snapshot);
const hashes = {};
for (const name of ['server.mjs','lib/task-store.mjs','lib/command-proposals.mjs','public/app.js','public/index.html','lib/command-execution.mjs','lib/owned-command.py','lib/owned_job.py','lib/slow-command.mjs']) {
  hashes[name] = createHash('sha256').update(await readFile(new URL('../../' + name, directory))).digest('hex');
}
await writeFile(new URL('browser-proof.json', directory), JSON.stringify({ url: app.url, dataDir: directory.pathname,
  cancelled, recovered, repeatedRestartRowsUnchanged: true, replayRevisions: [2,3,4], beforeAndAfterReplayRowsEqual: true, hashes,
  cancelHandles: JSON.parse(await readFile(new URL('browser-cancel-ab80dc11-3370-4a5e-bee1-e38c6f5a2866-handle-exits.json', directory))),
  crashHandles: JSON.parse(await readFile(new URL('browser-crash-1a0f2b96-9f59-4f52-8f76-355f09d40628-handle-exits.json', directory))) }, null, 2));
console.log('Actual browser-store repeated restart/replay validation PASS; unchanged 2 runs, cancelled failure and UNKNOWN preserved.');
