import assert from 'node:assert/strict';
import http from 'node:http';
import { spawn, execFileSync } from 'node:child_process';
import { once } from 'node:events';
import { createInterface } from 'node:readline';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';
import { ROOT } from '../server.mjs';

export const slow = { command: 'node lib/slow-command.mjs', cwd: '.' };
export const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
export function identity(pid) {
  return JSON.parse(execFileSync('powershell.exe', ['-NoProfile', '-Command',
    `$composeProcess = Get-Process -Id ${pid} -ErrorAction Stop; [pscustomobject]@{pid=$composeProcess.Id; createdAt=$composeProcess.StartTime.ToUniversalTime().ToString('o'); executable=$composeProcess.Path} | ConvertTo-Json -Compress`],
  { windowsHide: true, encoding: 'utf8' }));
}
export async function fixture(t, label, existingDataDir) {
  const dataDir = existingDataDir ?? `test/app03-m3-crash-compose-${label}-${randomUUID()}`;
  assert.match(dataDir, /^test\/app03-m3-crash-compose-[a-zA-Z0-9_-]+$/);
  const directory = path.join(ROOT, dataDir); await mkdir(directory, { recursive: true });
  const filename = path.join(directory, 'tasks.sqlite');
  const save = (name, value) => writeFile(path.join(directory, name), JSON.stringify(value, null, 2));
  const children = [];
  // Observe real launches without delaying, replacing or fabricating results.
  const preload = path.join(directory, 'launch-log.mjs');
  await writeFile(preload, `import cp from 'node:child_process'; import {syncBuiltinESMExports} from 'node:module';
    const original = cp.spawn; cp.spawn = (...args) => { const child = original(...args);
      console.error('M3_COMPOSE_NATIVE_SPAWN ' + child.pid); return child; }; syncBuiltinESMExports();`);
  async function logs(app) {
    await writeFile(path.join(directory, `server-${app.child.pid}.log`), app.output() + '\n' + app.errors());
  }
  async function stop(app) {
    if (app.child.exitCode === null && app.child.signalCode === null) {
      assert.deepEqual(identity(app.child.pid), app.identity, 'Terminate only our recorded server PID/create identity');
      app.child.kill('SIGKILL'); await app.closed;
    }
    await logs(app);
  }
  t?.after(async () => { for (const app of children) await stop(app); });
  async function boot(port = 0) {
    const child = spawn(process.execPath, ['--import', pathToFileURL(preload).href, 'server.mjs'], {
      cwd: ROOT, windowsHide: true, stdio: ['ignore','pipe','pipe'],
      env: { ...process.env, MESH_PORT: String(port), MESH_DATA_DIR: dataDir }
    });
    let output = ''; let errors = '';
    child.stderr.on('data', chunk => { errors += chunk; });
    const app = { child, closed: once(child, 'close'), output: () => output, errors: () => errors };
    children.push(app);
    const info = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error('Startup timed out: ' + errors)), 5000);
      child.once('error', error => { clearTimeout(timer); reject(error); });
      child.stdout.on('data', chunk => { output += chunk;
        const line = output.split('\n').find(line => line.startsWith('{') && line.endsWith('}'));
        if (line) { clearTimeout(timer); resolve(JSON.parse(line)); }
      });
    });
    assert.equal(info.pid, child.pid); assert.equal(info.dataDir, dataDir);
    app.url = info.url; app.identity = identity(child.pid);
    await save(`server-${child.pid}-identity.json`, app.identity);
    return app;
  }
  return { dataDir, directory, filename, save, boot, stop, logs, children };
}
export function request(app, route, { method = 'GET', headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request(app.url + route, { method, headers }, res => {
      const chunks = []; res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers,
        text: Buffer.concat(chunks).toString(), json() { return JSON.parse(this.text); } }));
    }); req.on('error', reject); req.end(body);
  });
}
export async function admit(app) {
  const res = await request(app, '/api/trial-session/bootstrap', { method: 'POST',
    headers: { Origin: app.url, 'Content-Type': 'application/json' }, body: '{}' });
  assert.equal(res.status, 201, res.text);
  return { Cookie: res.headers['set-cookie'][0].split(';')[0], 'X-Trial-CSRF': res.json().csrfToken };
}
export const mutate = (app, proof, route, body) => request(app, route, { method: 'POST',
  headers: { ...proof, Origin: app.url, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
export async function get(app, proof, id) {
  const res = await request(app, `/api/tasks/${id}`, { headers: proof }); assert.equal(res.status, 200, res.text); return res.json().task;
}
export async function propose(app, proof, title) {
  const created = await mutate(app, proof, '/api/tasks', { title }); assert.equal(created.status, 201);
  const task = created.json().task;
  const proposed = await mutate(app, proof, `/api/tasks/${task.id}/proposal`, { proposal: slow, revision: task.revision });
  assert.equal(proposed.status, 200); return proposed.json().task;
}
export function rows(filename) {
  const db = new DatabaseSync(filename, { readOnly: true });
  try { return Object.fromEntries(['tasks','task_proposals','task_executions','task_proposal_decisions']
    .map(table => [table, db.prepare(`SELECT * FROM ${table} ORDER BY rowid`).all()])); }
  finally { db.close(); }
}
export async function observe(f, app, label) {
  // Reuse the existing retained native handles. For cancellation the server
  // remains live; wait on bridge/root/descendant only. Crash kills its exact
  // retained caller object and also verifies that caller exit.
  const code = `import json,sys,time\nfrom test.test_owned_cancel import Observer\no=Observer()\ntry:\n found=o.tree(int(sys.argv[1]))\n print(json.dumps(dict(event='ready',identities=[i for h,i in found])),flush=True)\n action=json.loads(sys.stdin.readline())['action']\n start=time.monotonic()\n if action=='kill-caller':\n  h,i=found[0]\n  assert o.api.WaitForSingleObject(h,0)==258\n  assert o.api.TerminateProcess(h,1),i\n else:\n  assert action=='wait'\n  found=found[1:]\n identities=[]\n for h,i in found:\n  state=o.api.WaitForSingleObject(h,5000)\n  identities.append(dict(i,exitSignaled=state==0))\n print(json.dumps(dict(event='verified',action=action,identities=identities,elapsedMs=(time.monotonic()-start)*1000)),flush=True)\n assert all(i['exitSignaled'] for i in identities)\nfinally:\n o.close()\n`;
  const child = spawn('C:\\Python314\\python.exe', ['-B','-c',code,String(app.child.pid)], {
    cwd: ROOT, windowsHide: true, stdio: ['pipe','pipe','pipe']
  });
  const closed = once(child, 'close'); let errors = '';
  child.stderr.on('data', chunk => { errors += chunk; });
  const lines = createInterface({ input: child.stdout })[Symbol.asyncIterator]();
  const readyLine = await lines.next(); assert.equal(readyLine.done, false, errors);
  const ready = JSON.parse(readyLine.value); assert.equal(ready.event, 'ready');
  await f.save(`${label}-live-identities.json`, ready);
  return { ready, async finish(action) {
    child.stdin.end(JSON.stringify({ action }) + '\n');
    const line = await lines.next(); assert.equal(line.done, false, errors);
    const verified = JSON.parse(line.value); const [code] = await closed;
    assert.equal(code, 0, errors); assert.ok(verified.identities.every(i => i.exitSignaled));
    await f.save(`${label}-handle-exits.json`, verified); return verified;
  } };
}

// Live-browser supervisor: no UI simulation or auto-approval. UI creates and
// approves tasks. Retain native handles immediately when its durable run starts.
if (process.argv.includes('--browser')) {
  const f = await fixture(null, 'browser', process.env.M3_BROWSER_STORE); let app = await f.boot(Number(process.env.M3_BROWSER_PORT ?? 0)); let mode = 'cancel'; let stopping = false;
  console.log(JSON.stringify({ event: 'browser_ready', url: app.url, dataDir: f.dataDir, server: app.identity }));
  const input = createInterface({ input: process.stdin });
  input.on('line', line => { if (line === 'crash') mode = 'crash'; if (line === 'stop') stopping = true; });
  const seen = new Set();
  try {
    while (!stopping) {
      try {
        const control = await readFile(path.join(f.directory, 'browser-control'), 'utf8');
        if (control.trim() === 'crash') mode = 'crash';
        if (control.trim() === 'stop') { stopping = true; continue; }
      } catch (error) { if (error.code !== 'ENOENT') throw error; }
      const snapshot = rows(f.filename);
      const run = snapshot.task_executions.find(run => run.state === 'running' && !seen.has(run.id));
      if (!run) { await delay(20); continue; }
      seen.add(run.id); const selectedMode = mode;
      const observer = await observe(f, app, `browser-${selectedMode}-${run.id}`);
      await delay(250);
      await f.save(`browser-${selectedMode}-${run.id}-before.json`, rows(f.filename));
      console.log(JSON.stringify({ event: 'browser_live', mode: selectedMode, taskId: run.taskId, runId: run.id, identities: observer.ready.identities }));
      if (selectedMode === 'crash') {
        assert.deepEqual(identity(app.child.pid), app.identity);
        await observer.finish('kill-caller'); await app.closed; await f.logs(app);
        app = await f.boot(Number(new URL(app.url).port));
        await f.save(`browser-crash-${run.id}-reopened.json`, rows(f.filename));
        console.log(JSON.stringify({ event: 'browser_restarted', url: app.url, server: app.identity, runId: run.id }));
      } else {
        const end = Date.now() + 20000;
        while (rows(f.filename).task_executions.find(row => row.id === run.id).state === 'running' && Date.now() < end) await delay(20);
        await observer.finish('wait');
        const after = rows(f.filename); const result = JSON.parse(after.task_executions.find(row => row.id === run.id).result);
        await f.save(`browser-cancel-${run.id}-result.json`, after);
        assert.equal(result.cancelled, true); assert.equal(result.status, 'FAIL'); assert.equal(result.cleanupVerified, true);
        assert.match(result.stdout, /M3 slow descendant .* started/); assert.doesNotMatch(result.stdout, /completed/);
        console.log(JSON.stringify({ event: 'browser_cancel_observed', runId: run.id }));
      }
    }
  } finally { for (const child of f.children) await f.stop(child); input.close(); }
}
