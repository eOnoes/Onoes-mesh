import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
function request(url, route = '/', { method = 'GET', headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const req = http.request(url + route, { method, headers }, res => {
      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, text: Buffer.concat(chunks).toString() }));
    });
    req.on('error', reject);
    req.end(body);
  });
}

test('npm start serves actual PWA and phone-origin task requests from an isolated store', async t => {
  const dataDir = `test/app03-m2-approve-npm-start-${randomUUID()}`;
  const storePath = path.resolve(root, dataDir);
  assert.ok(storePath.startsWith(root + path.sep), 'Disposable store stays in this worktree');
  const npmCli = process.env.npm_execpath ?? path.join(path.dirname(process.execPath), 'node_modules/npm/bin/npm-cli.js');
  const child = spawn(process.execPath, [npmCli, 'start'], {
    cwd: root, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'],
    env: { ...process.env, MESH_DATA_DIR: dataDir, MESH_PREVIEW_PORT: '0' }
  });
  let ready;
  let output = '';
  let errors = '';
  child.stderr.on('data', chunk => { errors += chunk; });
  const exited = new Promise(resolve => child.once('exit', resolve));
  t.after(async () => {
    if (ready) { try { process.kill(ready.pid); } catch (error) { if (error.code !== 'ESRCH') throw error; } }
    if (child.exitCode === null) {
      let deadline;
      const stopped = await Promise.race([exited.then(() => true), new Promise(resolve => { deadline = setTimeout(() => resolve(false), 3000); })]);
      clearTimeout(deadline);
      if (!stopped) { child.kill(); await exited; }
    }
    // Retain this disposable store for M2 verification; no DB deletion.
  });
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`npm start timeout: ${output} ${errors}`)), 15000);
    child.once('error', error => { clearTimeout(timer); reject(error); });
    child.once('exit', code => { clearTimeout(timer); if (!ready) reject(new Error(`npm start exit ${code}: ${errors}`)); });
    child.stdout.on('data', chunk => {
      output += chunk;
      for (const line of output.split(/\r?\n/)) {
        if (line.startsWith('{') && line.includes('mesh_listening')) {
          ready = JSON.parse(line); clearTimeout(timer); resolve(); return;
        }
      }
    });
  });
  assert.equal(ready.dataDir, dataDir);
  for (const url of [ready.url, ready.previewUrl]) {
    for (const [route, file] of [['/', 'index.html'], ['/app.js', 'app.js'], ['/styles.css', 'styles.css'], ['/control.mjs','control.mjs'], ['/control-models.mjs','control-models.mjs']]) {
      const response = await request(url, route);
      assert.equal(response.status, 200);
      assert.equal(response.text, await readFile(path.join(root, 'public', file), 'utf8'));
    }
  }
  const phone = { Host: 'mesh.example.ts.net:8443', 'X-Forwarded-Proto': 'https' };
  assert.equal((await request(ready.previewUrl, '/', { headers: phone })).status, 200);
  const origin = 'https://mesh.example.ts.net:8443';
  const headers = { ...phone, Origin: origin, 'Content-Type': 'application/json', 'Sec-Fetch-Site': 'same-origin' };
  const admission = await request(ready.previewUrl, '/api/trial-session/bootstrap', { method: 'POST', headers, body: '{}' });
  assert.equal(admission.status, 201);
  const proof = { ...headers, Cookie: admission.headers['set-cookie'][0].split(';')[0], 'X-Trial-CSRF': JSON.parse(admission.text).csrfToken };
  const created = await request(ready.previewUrl, '/api/tasks', { method: 'POST', headers: proof, body: JSON.stringify({ title: 'M1 isolated HTTP proof' }) });
  assert.equal(created.status, 201);
  const listed = await request(ready.previewUrl, '/api/tasks', { headers: proof });
  assert.equal(listed.status, 200);
  assert.equal(JSON.parse(listed.text).tasks[0].title, 'M1 isolated HTTP proof');
  assert.equal((await request(ready.previewUrl, '/api/tasks', { headers: { ...proof, Origin: 'https://elsewhere.example' } })).status, 403);
  console.log(`HTTP proof: npm start; backend ${ready.url}; preview ${ready.previewUrl}; shell/app.js/styles.css 200 byte-identical; phone Host shell 200; bootstrap 201; task POST 201/GET 200; disposable store ${dataDir}`);
});
