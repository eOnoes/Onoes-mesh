import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { mkdtempSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { randomUUID } from 'node:crypto';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { createServer } from 'node:http';
import { createDispatchBarrier, assertDispatchHold } from '../lib/workroom-dispatch-barrier.mjs';
import { openTaskStore } from '../lib/task-store.mjs';
import { sendTaskMessage } from '../lib/workroom.mjs';
import { dispatchLocalSession } from '../lib/workroom-local-sessions.mjs';
import { startApp } from '../server.mjs';
import { databaseFileIdentity } from '../lib/database-identity.mjs';

const fixture = () => {
  const path = join(mkdtempSync(join(tmpdir(), 'mesh-dispatch-')), 'fixture.sqlite');
  const db = new DatabaseSync(path);
  return { path, db, gate: createDispatchBarrier(db) };
};
const status = code => error => error.status === code;
const binding = path => ({ databasePath: path, databaseIdentity: databaseFileIdentity(path) });

test('held dispatch proof refuses a different database binding', () => {
  const f=fixture(), other=fixture();
  try {
    f.gate.pause();const held=f.gate.hold();
    assert.throws(()=>assertDispatchHold(held,{databasePath:other.path,databaseIdentity:'f'.repeat(64)}),/database/);
    assert.throws(()=>assertDispatchHold(held,{databasePath:other.path,databaseIdentity:binding(f.path).databaseIdentity}),/database/);
    assert.throws(()=>assertDispatchHold(held,{databasePath:f.path,databaseIdentity:'f'.repeat(64)}),/database/);
    assert.throws(()=>assertDispatchHold(held),/database binding/);
    assert.equal(assertDispatchHold(held,binding(f.path)).databaseIdentity,binding(f.path).databaseIdentity);
    held.release();
  } finally { f.db.close();other.db.close(); }
});

test('an in-memory database cannot mint a persistent maintenance hold', () => {
  const db=new DatabaseSync(':memory:'),gate=createDispatchBarrier(db);
  try {
    gate.pause();assert.throws(()=>gate.hold(),status(503));
    assert.equal(gate.status().state,'paused');assert.equal(gate.status().held,false);
  } finally { db.close(); }
});

test('barrier reads create no schema; pause persists across independent connections', async () => {
  const f = fixture(); let peer;
  try {
    assert.equal(f.gate.status().state, 'open');
    assert.equal(f.db.prepare("SELECT COUNT(*) AS n FROM sqlite_master WHERE type='table'").get().n, 0);
    const paused = f.gate.pause(); peer = new DatabaseSync(f.path);
    const other = createDispatchBarrier(peer);
    await assert.rejects(other.run(() => assert.fail('must not dispatch')), status(503));
    assert.deepEqual(other.pause(), paused);
    other.resume(paused.generation);
    assert.equal(await f.gate.run(() => 'normal dispatch'), 'normal dispatch');
  } finally { peer?.close(); f.db.close(); }
});

test('pause drains original admissions before a held lease; release never resumes automatically', async () => {
  const f = fixture(); let finish;
  try {
    const original = f.gate.run(() => new Promise(resolve => { finish = resolve; }));
    assert.equal(f.gate.pause().activeAdmissions, 1);
    assert.throws(() => f.gate.hold(), status(409));
    await assert.rejects(f.gate.run(() => assert.fail('new dispatch')), status(503));
    finish('accepted'); await original;
    const held = f.gate.hold();
    assert.equal(assertDispatchHold(held,binding(f.path)).scope, 'mesh_admissions_only');
    assert.throws(() => assertDispatchHold(JSON.parse(JSON.stringify(held)),binding(f.path)), status(503));
    assert.throws(() => f.gate.resume(f.gate.status().generation), status(409));
    held.release(); assert.equal(f.gate.status().state, 'paused');
    assert.throws(() => assertDispatchHold(held,binding(f.path)), status(409));
    assert.throws(() => f.gate.resume(f.gate.status().generation - 1), status(409));
  } finally { f.db.close(); }
});

test('a lost sender or maintenance owner stays unresolved after reopen; no timer clears it', async () => {
  const f = fixture();
  f.gate.pause(); const held = f.gate.hold(); f.db.close();
  const reopened = new DatabaseSync(f.path), gate = createDispatchBarrier(reopened);
  try {
    assert.equal(gate.status().held, true);
    assert.throws(() => gate.hold(), status(409));
    assert.throws(() => gate.resume(gate.status().generation), status(409));
    assert.throws(() => assertDispatchHold(held,binding(f.path)));
    // Separate synthetic crashed-sender database; no retirement is inferred.
    const lost = fixture();
    try {
      const paused=lost.gate.pause();lost.gate.resume(paused.generation);
      lost.db.prepare("INSERT INTO workroom_dispatch_admissions VALUES('lost','old-instance',999999,'admitted','2020-01-01',NULL)").run();
      assert.equal(createDispatchBarrier(lost.db).status().activeAdmissions, 1);
      await assert.rejects(createDispatchBarrier(lost.db).run(()=>assert.fail('old sender must block a replacement')),status(503));
      lost.gate.pause();
      assert.throws(() => lost.gate.hold(), status(409));
    } finally { lost.db.close(); }
  } finally { reopened.close(); }
});

test('failed sends drain admission only and never produce worker-retirement proof', async () => {
  const f = fixture();
  try {
    await assert.rejects(f.gate.run(() => { throw Error('uncertain transport'); }), /uncertain transport/);
    assert.equal(f.gate.status().activeAdmissions, 0);
    f.gate.pause(); const held = f.gate.hold();
    assert.equal(assertDispatchHold(held,binding(f.path)).writerQuiescence, undefined);
    assert.equal(assertDispatchHold(held,binding(f.path)).coveredLocalWriters, undefined);
    f.db.exec('BEGIN IMMEDIATE;');
    assert.throws(() => held.release(), status(409));
    assert.equal(assertDispatchHold(held,binding(f.path)).dispatchPaused, true);
    f.db.exec('ROLLBACK;'); held.release();
  } finally { f.db.close(); }
});

test('database contention retries only original admission bookkeeping, never the send', async () => {
  const f=fixture(), peer=new DatabaseSync(f.path);let finish, calls=0, timer;
  try {
    const original=f.gate.run(()=>{calls++;return new Promise(resolve=>{finish=resolve;});});
    f.gate.pause();peer.exec('BEGIN IMMEDIATE;');finish('one actual send');
    timer=setTimeout(()=>peer.exec('ROLLBACK;'),60);
    assert.equal(await original,'one actual send');assert.equal(calls,1);assert.equal(f.gate.status().activeAdmissions,0);
    const held=f.gate.hold();held.release();
  } finally { clearTimeout(timer);if(peer.isTransaction)peer.exec('ROLLBACK;');peer.close();f.db.close(); }
});

test('partial barrier schema fails closed rather than repairing itself open', async () => {
  const f = fixture();
  try {
    f.db.exec('CREATE TABLE workroom_dispatch_gate(id INTEGER);');
    assert.throws(() => f.gate.status(), status(503));
    await assert.rejects(f.gate.run(() => assert.fail('corrupt gate')), status(503));
  } finally { f.db.close(); }
});

test('paused real Workroom preserves cards and reaches neither legacy nor native transport', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'mesh-dispatch-store-')), store = openTaskStore(join(dir,'tasks.sqlite'));
  try {
    const task = store.create({ title: 'Keep this card', description: 'Synthetic request' }), before = store.get(task.id);
    let calls = 0;
    store.workroom.dispatch.pause();
    await assert.rejects(sendTaskMessage({ workroom: store.workroom, taskId: task.id, body: { id:'blocked',agentId:'echo' },
      relay: { nativeRead: async () => { calls++; }, taskMessage: async () => { calls++; } }, admitted: () => true }), status(503));
    await assert.rejects(dispatchLocalSession({ workroom: store.workroom, taskId: task.id,
      rpc: async () => { calls++; }, admitted: () => true }), status(503));
    assert.equal(calls, 0); assert.deepEqual(store.get(task.id), before);
    assert.deepEqual(store.workroom.get(task.id).messages, []);
  } finally { store.close(); }
});

test('admitted backend Relay mutations refuse maintenance while board reads remain available', async () => {
  const oldStandalone=process.env.MESH_STANDALONE,oldMode=process.env.MESH_RELAY_MODE;
  process.env.MESH_STANDALONE='1';process.env.MESH_RELAY_MODE='child';let app;
  try {
    app=await startApp({dataDir:'test/app03-dispatch-http-'+randomUUID(),relayEnabled:false});
    const headers={Origin:app.url,'Content-Type':'application/json'};
    const boot=await fetch(app.url+'/api/trial-session/bootstrap',{method:'POST',headers,body:'{}'});
    assert.equal(boot.status,201);const proof=await boot.json();headers.Cookie=boot.headers.get('set-cookie').split(';')[0];headers['X-Trial-CSRF']=proof.csrfToken;
    app.dispatch.pause();
    for(const route of ['/api/relay/message','/api/relay/reconnect'])assert.equal((await fetch(app.url+route,{method:'POST',headers,body:'{}'})).status,503);
    assert.equal((await fetch(app.url+'/api/workroom',{headers})).status,200);
  } finally {
    await app?.close();
    if(oldStandalone===undefined)delete process.env.MESH_STANDALONE;else process.env.MESH_STANDALONE=oldStandalone;
    if(oldMode===undefined)delete process.env.MESH_RELAY_MODE;else process.env.MESH_RELAY_MODE=oldMode;
  }
});

async function stop(child) {
  if (child && child.exitCode === null && child.signalCode === null) {
    const ended = once(child,'exit'); child.kill('SIGTERM');
    const timer = setTimeout(() => child.kill('SIGKILL'), 3000);
    try { await ended; } finally { clearTimeout(timer); }
  }
}
async function preview(env) {
  const child = spawn(process.execPath, ['serve.mjs'], { cwd:resolve('.'), env, windowsHide:true, stdio:['ignore','pipe','pipe'] });
  let output = '';
  const url = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(Error('Owned preview did not start: '+output.slice(-500))), 15000);
    child.stdout.on('data', data => {
      output += data;
      for (const line of output.split('\n')) {
        try { const value = JSON.parse(line); if (value.previewUrl?.startsWith('http://127.0.0.1:')) { clearTimeout(timer); resolve(value.previewUrl); } } catch {}
      }
    });
    child.once('error', error => { clearTimeout(timer); reject(error); });
    child.once('exit', code => { clearTimeout(timer); reject(Error('Owned preview exited '+code+': '+output.slice(-500))); });
  }).catch(async error => { await stop(child); throw error; });
  return { child, url };
}

test('actual Relay proxy drains sends, preserves GET access and remains paused after app restart', async () => {
  const dataDir = 'test/app03-dispatch-'+randomUUID(), dir=resolve(dataDir); mkdirSync(dir,{recursive:true});
  const token='synthetic-dispatch-test-key', key=join(dir,'fixture.key'); writeFileSync(key,token);
  const store=openTaskStore(join(dir,'tasks.sqlite'));const task=store.create({title:'Persistent card',description:'Synthetic fixture'});store.close();
  const db=new DatabaseSync(join(dir,'tasks.sqlite')), gate=createDispatchBarrier(db);
  const before=db.prepare('SELECT * FROM tasks WHERE id=?').get(task.id);
  let sent=0, release, arrived;
  const incoming=new Promise(resolve=>{arrived=resolve;});
  const upstream=createServer(async(req,res)=>{
    for await (const _ of req) {}
    if(req.method==='POST'){sent++;if(sent===1){arrived();await new Promise(resolve=>{release=resolve;});}}
    res.writeHead(200,{'Content-Type':'application/json'});res.end('{"ok":true}');
  });
  await new Promise(resolve=>upstream.listen(0,'127.0.0.1',resolve));
  const env={...process.env};for(const key of Object.keys(env))if(key.startsWith('MESH_'))delete env[key];delete env.NODE_TEST_CONTEXT;
  Object.assign(env,{MESH_STANDALONE:'1',MESH_DATA_DIR:dataDir,MESH_PREVIEW_PORT:'0',MESH_GATE_KEY_FILE:key,
    MESH_RELAY_ORIGIN:'http://127.0.0.1:'+upstream.address().port,MESH_RELAY_MODE:'child'});
  let app;
  try {
    app=await preview(env);
    const request=(method)=>fetch(app.url+'/relay/api/fixture',{method,headers:{Authorization:'Bearer '+token,Origin:app.url,'Content-Type':'application/json'},
      ...(method==='POST'?{body:'{}'}:{}),signal:AbortSignal.timeout(10000)});
    const first=request('POST');let arrivalTimer;
    try {
      await Promise.race([incoming, first.then(response=>{throw Error('Mock upstream not reached: HTTP '+response.status);}),
        new Promise((_,reject)=>{arrivalTimer=setTimeout(()=>reject(Error('Mock request did not arrive')),5000);})]);
    } finally { clearTimeout(arrivalTimer); }
    const paused=gate.pause();assert.equal(paused.activeAdmissions,1);assert.throws(()=>gate.hold(),status(409));
    assert.equal((await request('POST')).status,503);assert.equal(sent,1);
    release();assert.equal((await first).status,200);
    const held=gate.hold();assert.equal((await request('GET')).status,200);
    await stop(app.child);app=await preview(env);
    assert.equal((await request('POST')).status,503);assert.equal(sent,1);
    assert.equal(assertDispatchHold(held,binding(join(dir,'tasks.sqlite'))).dispatchPaused,true);
    held.release();gate.resume(paused.generation);
    assert.equal((await request('POST')).status,200);assert.equal(sent,2);
    assert.deepEqual(db.prepare('SELECT * FROM tasks WHERE id=?').get(task.id),before);
  } finally {
    release?.();await stop(app?.child);upstream.closeAllConnections();await new Promise(resolve=>upstream.close(resolve));db.close();
  }
});
