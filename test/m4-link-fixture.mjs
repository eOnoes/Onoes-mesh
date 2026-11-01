import assert from 'node:assert/strict';
import http from 'node:http';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createInterface } from 'node:readline';
import { randomUUID } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
import { ROOT } from '../server.mjs';

export async function fixture(t, label = 'http') {
  const dataDir = `test/app03-m4-link-${label}-${randomUUID()}`;
  const dir = path.join(ROOT, dataDir); const children = [];
  await mkdir(dir, { recursive: true });
  async function stop(app) {
    if (app.child.exitCode !== null || app.child.signalCode !== null) return;
    const exited = once(app.child, 'exit'); app.child.kill(); await exited;
    assert.doesNotMatch(app.errors(), /M4_EXECUTION_TRIPWIRE/);
    await writeFile(path.join(dir, `mesh-${app.child.pid}.stdout.txt`), app.output());
    await writeFile(path.join(dir, `mesh-${app.child.pid}.stderr.txt`), app.errors());
  }
  t.after(async () => { for (const app of children) await stop(app); });
  async function boot(port = 0, relay = true) {
    const preloadPath = path.join(dir, `no-executor-${children.length}.mjs`);
    await writeFile(preloadPath, `import cp from 'node:child_process'; import {syncBuiltinESMExports} from 'node:module';
      const realSpawn = cp.spawn;
      cp.spawn = (exe, args, options) => {
        if (exe !== 'C:\\\\Python314\\\\python.exe' || args.length !== 5 || args[0] !== '-I' || args[1] !== '-S' || args[2] !== '-B' || args[3] !== '-c' || !args[4]?.includes('mesh_runtime')) {
          console.error('M4_EXECUTION_TRIPWIRE'); throw Error('M4 execution forbidden');
        }
        console.error(JSON.stringify({event:'M4_RELAY_RUNTIME_SPAWN',executable:exe,args,environmentKeys:Object.keys(options.env).sort()})); return realSpawn(exe,args,options);
      };
      for (const name of ['spawnSync','exec','execSync','execFile','execFileSync','fork']) cp[name] = () => { console.error('M4_EXECUTION_TRIPWIRE'); throw Error('M4 execution forbidden'); };
      syncBuiltinESMExports();`);
    const child = spawn(process.execPath, ['--import', pathToFileURL(preloadPath).href, 'server.mjs'], {
      cwd: ROOT, windowsHide: true, stdio: ['pipe','pipe','pipe'],
      env: { ...process.env, MESH_PORT: String(port), MESH_DATA_DIR: dataDir, MESH_RELAY: relay ? '1' : '0' }
    });
    let output = '', errors = ''; const app = { child, output: () => output, errors: () => errors }; children.push(app);
    child.stderr.on('data', b => { errors += b; });
    const info = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(Error('Mesh startup timed out: ' + errors)), 8000);
      child.once('error', e => { clearTimeout(timer); reject(e); });
      child.once('exit', code => { clearTimeout(timer); reject(Error(`Mesh exited ${code}: ${errors}`)); });
      child.stdout.on('data', b => {
        output += b;
        const line = output.split('\n').find(line => { try { return JSON.parse(line).event === 'mesh_listening'; } catch { return false; } });
        if (line) { clearTimeout(timer); resolve(JSON.parse(line)); }
      });
    });
    app.url = info.url; return app;
  }
  return { boot, stop, dir, dataDir, filename: path.join(dir, 'tasks.sqlite'), relayFilename: path.join(dir, 'relay', 'relay.sqlite') };
}
export function request(app, route, { method = 'GET', headers = {}, body } = {}) {
  return new Promise((resolve,reject) => {
    const req = http.request(app.url + route, { method, headers }, res => {
      const chunks = []; res.on('data', c => chunks.push(c));
      res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, text: Buffer.concat(chunks).toString(), json() { return JSON.parse(this.text); } }));
    }); req.on('error', reject); req.end(body);
  });
}
export async function admit(app) {
  const res = await request(app, '/api/trial-session/bootstrap', { method: 'POST', headers: { Origin: app.url, 'Content-Type': 'application/json' }, body: '{}' });
  assert.equal(res.status,201);
  return { Cookie: res.headers['set-cookie'][0].split(';')[0], 'X-Trial-CSRF': res.json().csrfToken };
}
export const mutate = (app, proof, route, body) => request(app, route, { method: 'POST', headers: { ...proof, Origin: app.url, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
export async function retainProcesses(t, f, app, label, includeMesh = false) {
  const relay = app.output().split('\n').flatMap(line=>{try{return [JSON.parse(line)]}catch{return []}}).filter(v=>v.event==='mesh_relay_listening').at(-1);
  const ids = [relay.pid, ...(includeMesh ? [app.child.pid] : [])];
  const observer = spawn('C:\\Python314\\python.exe', ['-I','-B',path.join(ROOT,'test','m4-link-process-observer.py'),...ids.map(String)], {cwd:ROOT,windowsHide:true,stdio:['pipe','pipe','pipe']});
  let errors='';observer.stderr.on('data',b=>{errors+=b});
  const lines=createInterface({input:observer.stdout}); const records=[];
  const exit=new Promise(resolve=>observer.once('exit',resolve));
  await new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(Error('Process handle acquisition deadline: '+errors)),3000);
    observer.once('error',e=>{clearTimeout(timer);reject(e)});
    observer.once('exit',()=>{clearTimeout(timer);reject(Error('Observer exited before holding identities: '+errors))});
    lines.on('line',line=>{const record=JSON.parse(line);records.push(record);if(record.event==='held'){clearTimeout(timer);resolve()}});
  });
  assert.equal(records[0].identities[0].pid,relay.pid);
  assert.equal(records[0].identities[0].executable.toLowerCase(),'c:\\python314\\python.exe');
  let verified=false;
  async function verify() {
    if(verified)return;verified=true;observer.stdin.end('\n');const code=await exit;
    await writeFile(path.join(f.dir,`process-${label}.json`),JSON.stringify({records,code,errors},null,2));
    assert.equal(code,0,errors);assert.equal(records.at(-1).event,'verified');assert.ok(records.at(-1).identities.every(v=>v.exitSignaled && v.exitCode !== 259));
  }
  t.after(verify);return verify;
}
