import test from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { writeFile, readFile } from 'node:fs/promises';
import path from 'node:path';
import { fixture, request, admit, mutate, retainProcesses } from './m4-link-fixture.mjs';

test('M4 actual HTTP guard: unadmitted, CSRF, origin, explicit intent and configuration denials create no tasks', async t => {
  const f = await fixture(t, 'denials'); const app = await f.boot(0, false); const proof = await admit(app);
  assert.equal((await request(app,'/relay')).status,404,'No new unauthenticated shell route');
  for (const route of ['/api/relay','/api/relay/shell','/api/relay/native/api/agents','/api/relay/static/slash-commands.json'])
    assert.equal((await request(app,route)).status,401,'All new Relay routes require Mesh admission');
  const body = { id:'denied',text:'Cannot create a task',conversationId:'00000000-0000-0000-0000-000000000000',meshIntent:'create_task' };
  for (const route of ['/api/relay/message','/api/relay/reconnect']) {
    const value = route.endsWith('message') ? body : {};
    assert.equal((await mutate(app, {}, route, value)).status,401);
    assert.equal((await mutate(app, { ...proof, 'X-Trial-CSRF':'x'.repeat(43) }, route, value)).status,403);
    assert.equal((await request(app, route, { method:'POST',headers:{...proof,Origin:'http://evil.test','Content-Type':'application/json'},body:JSON.stringify(value) })).status,403);
  }
  assert.equal((await mutate(app,proof,'/api/relay/message',{...body,command:'node --version'})).status,400);
  assert.equal((await mutate(app,proof,'/api/relay/message',{...body,meshIntent:'approve'})).status,400);
  assert.equal((await mutate(app,proof,'/api/relay/message',body)).status,503);
  assert.equal((await mutate(app,proof,'/api/relay/reconnect',{url:'http://127.0.0.1:8787',dbPath:'owner.sqlite',token:'untrusted'})).status,400);
  assert.deepEqual((await request(app,'/api/tasks',{headers:proof})).json().tasks,[]);
  const db = new DatabaseSync(f.filename,{readOnly:true});
  assert.equal(db.prepare('SELECT COUNT(*) AS n FROM relay_task_links').get().n,0); assert.equal(db.prepare('SELECT COUNT(*) AS n FROM task_executions').get().n,0); db.close();
  assert.doesNotMatch(app.output(),/mesh_relay_task_linked/);
  await writeFile(path.join(f.dir,'evidence.json'),JSON.stringify({denied:true,tasks:0,links:0,executions:0}));
});

test('M4 actual copied Relay HTTP/process/SQLite: message, retries, reconnect and restart both preserve one canonical task', async t => {
  const f = await fixture(t, 'actual'); let app = await f.boot(); let proof = await admit(app);
  let snapshot = (await request(app,'/api/relay',{headers:proof})).json();
  await writeFile(path.join(f.dir,'startup-evidence.json'),JSON.stringify({status:snapshot,events:app.output(),runtime:'C:\\Python314\\python.exe',dependencies:'test/app03-m4-link-runtime/Lib/site-packages',flags:['-I','-S','-B'],dependencyHandoff:'test/app03-m4-link-runtime/Scripts/python.exe -m pip install fastapi uvicorn httpx cryptography'},null,2));
  assert.equal(snapshot.status,'fresh','Actual Relay startup failed. Verify fixed C:/Python314/python.exe and confined test/app03-m4-link-runtime/Lib/site-packages dependencies; evidence retained in '+f.dataDir);
  const startupEvents = app.output().split('\n').flatMap(line=>{try{return [JSON.parse(line)]}catch{return []}});
  const spawned = startupEvents.find(v=>v.event==='mesh_relay_spawned');
  const listening = startupEvents.find(v=>v.event==='mesh_relay_listening');
  assert.equal(spawned.executable,'C:\\Python314\\python.exe');
  assert.equal(listening.pid,spawned.pid,'Actual listener must be the exact created native process');
  const launch = app.errors().split('\n').flatMap(line=>{try{return [JSON.parse(line)]}catch{return []}}).find(v=>v.event==='M4_RELAY_RUNTIME_SPAWN');
  assert.deepEqual(launch.args.slice(0,4),['-I','-S','-B','-c']);
  assert.equal(launch.args[4],`import sys; sys.path[:0]=[${JSON.stringify(path.resolve('service_roots/relay'))},${JSON.stringify(path.resolve('test/app03-m4-link-runtime/Lib/site-packages'))}]; import mesh_runtime`);
  assert.deepEqual(launch.environmentKeys,['MESH_RELAY_CAPABILITY','RELAY_CONFIG_PATH','RELAY_SESSION_DB','SystemRoot','TEMP','TMP']);
  await writeFile(path.join(f.dir,'launcher-evidence.json'),JSON.stringify(launch,null,2));
  const relayPort = listening.port;
  const direct = await request({url:`http://127.0.0.1:${relayPort}`},'/api/agents/mesh/message',{method:'POST',headers:{Origin:`http://127.0.0.1:${relayPort}`,'Content-Type':'application/json'},body:JSON.stringify({id:'unadmitted',text:'Direct request cannot create tasks'})});
  assert.equal(direct.status,403); assert.deepEqual((await request(app,'/api/tasks',{headers:proof})).json().tasks,[]);
  const actualShell = await request(app,'/api/relay/shell',{headers:proof}); assert.equal(actualShell.status,200);
  assert.equal(actualShell.json().html,await readFile(new URL('../service_roots/relay/static/index.html',import.meta.url),'utf8'));
  assert.equal((await request(app,'/api/relay/native/api/agents/mesh/stop',{method:'POST',headers:{...proof,Origin:app.url,'Content-Type':'application/json'},body:'{}'})).status,403);
  const body = {id:'actual_message_1',text:'node --version\nReal Relay message; create task only.',conversationId:snapshot.conversationId,meshIntent:'create_task'};
  const verifyRelayRecoveryExit = await retainProcesses(t,f,app,'reference-recovery');
  // Simulate the real cross-store gap: canonical commit succeeds, Relay's
  // reference write fails. Reboot must only recover that reference, never create.
  const fault = new DatabaseSync(f.relayFilename);
  fault.exec("CREATE TRIGGER fail_reference BEFORE UPDATE OF task_id ON mesh_task_references BEGIN SELECT RAISE(ABORT,'test reference write failure'); END;");
  const failed = await mutate(app,proof,'/api/relay/message',body); assert.equal(failed.status,503);
  const committed = (await request(app,'/api/tasks',{headers:proof})).json().tasks;
  assert.equal(committed.length,1);
  assert.equal(fault.prepare('SELECT task_id FROM mesh_task_references').get().task_id,null);
  fault.exec('DROP TRIGGER fail_reference;'); fault.close();
  const recovered = await mutate(app,proof,'/api/relay/reconnect',{}); assert.equal(recovered.status,200);
  await verifyRelayRecoveryExit();
  assert.deepEqual(recovered.json().links,[{messageId:body.id,taskId:committed[0].id}]);
  const first = await mutate(app,proof,'/api/relay/message',body); assert.equal(first.status,200,first.text); const ref = first.json();
  assert.equal(ref.ok,true); assert.equal(ref.duplicate,true); assert.equal(ref.taskId,committed[0].id);
  const replies = await Promise.all(Array.from({length:5},()=>mutate(app,proof,'/api/relay/message',body)));
  for (const reply of replies) { assert.equal(reply.status,200,reply.text); assert.equal(reply.json().taskId,ref.taskId); assert.equal(reply.json().duplicate,true); }
  assert.equal((await mutate(app,proof,'/api/relay/message',{...body,text:'changed'})).status,409);
  assert.equal((await mutate(app,proof,'/api/relay/message',{...body,conversationId:'00000000-0000-0000-0000-000000000000'})).status,400);
  assert.equal((await mutate(app,proof,'/api/relay/message',{...body,command:'git status'})).status,400);
  const verifyReconnectExit = await retainProcesses(t,f,app,'reconnect');
  await mutate(app,proof,'/api/relay/reconnect',{}); await verifyReconnectExit();
  snapshot = (await request(app,'/api/relay',{headers:proof})).json();
  assert.equal(snapshot.conversationId,body.conversationId); assert.deepEqual(snapshot.links,[{messageId:body.id,taskId:ref.taskId}]);
  assert.equal((await mutate(app,proof,'/api/relay/message',body)).json().taskId,ref.taskId);
  const verifyRestartExit = await retainProcesses(t,f,app,'both-restart',true);
  const port = Number(new URL(app.url).port); await f.stop(app); await verifyRestartExit(); app = await f.boot(port);
  assert.equal((await mutate(app,proof,'/api/relay/message',body)).status,401); proof = await admit(app);
  snapshot = (await request(app,'/api/relay',{headers:proof})).json(); assert.equal(snapshot.status,'fresh');
  assert.equal(snapshot.conversationId,body.conversationId); assert.deepEqual(snapshot.links,[{messageId:body.id,taskId:ref.taskId}]);
  assert.equal((await mutate(app,proof,'/api/relay/message',body)).json().taskId,ref.taskId);
  const tasks = (await request(app,'/api/tasks',{headers:proof})).json().tasks; assert.equal(tasks.length,1); assert.equal(tasks[0].id,ref.taskId); assert.equal(tasks[0].proposal,undefined); assert.equal(tasks[0].description,body.text);
  const verifyFinalExit = await retainProcesses(t,f,app,'final-cleanup',true);
  const db = new DatabaseSync(f.filename,{readOnly:true});
  assert.equal(db.prepare('SELECT COUNT(*) AS n FROM relay_task_links').get().n,1);
  for (const name of ['task_executions','task_proposals','task_proposal_decisions']) assert.equal(db.prepare(`SELECT COUNT(*) AS n FROM ${name}`).get().n,0); db.close();
  const relayDb = new DatabaseSync(f.relayFilename,{readOnly:true});
  assert.deepEqual(relayDb.prepare('PRAGMA table_info(mesh_task_references)').all().map(r=>r.name),['conversation_id','message_id','task_id','message_hash']);
  const refs=relayDb.prepare('SELECT * FROM mesh_task_references').all(); assert.equal(refs.length,1); assert.equal(refs[0].task_id,ref.taskId);
  assert.equal(relayDb.prepare('SELECT COUNT(*) AS n FROM messages').get().n,1); assert.equal(relayDb.prepare('SELECT COUNT(*) AS n FROM outbox').get().n,0); relayDb.close();
  await writeFile(path.join(f.dir,'evidence.json'),JSON.stringify({ref,snapshot,tasks,relayReferences:refs,retries:5,reconnect:true,recoveredAfterReferenceWriteFailure:true,restartSamePort:port,executions:0,events:app.output(),sourceManifest:await readFile(new URL('../service_roots/relay/SOURCE.md',import.meta.url),'utf8')},null,2));
  await f.stop(app); await verifyFinalExit();
});
