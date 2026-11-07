import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {openTaskStore} from '../lib/task-store.mjs';
import {sendTaskHandoff} from '../lib/workroom.mjs';
import {startApp} from '../server.mjs';

test('lead creation is atomic, restricted to Nims/Echo and survives restart; legacy owners preserved',()=>{
 const file=join(mkdtempSync(join(tmpdir(),'mesh-lead-')),'tasks.sqlite');let store=openTaskStore(file);
 try{
  const a=store.create({title:'Nims project',owner:'nims'});const b=store.create({title:'Echo project',owner:'echo'});
  assert.equal(store.workroom.get(a.id).workroom.owner,'nims');assert.equal(store.workroom.get(b.id).workroom.owner,'echo');
  assert.throws(()=>store.create({title:'Bad owner',owner:'dsh'}),/Nims or Echo/);
  assert.throws(()=>store.update(a.id,{title:a.title,owner:'echo',revision:1}),/Invalid task fields/);
  const db=new DatabaseSync(file);db.exec("CREATE TRIGGER reject_lead BEFORE INSERT ON workroom_tasks BEGIN SELECT RAISE(ABORT,'lead fixture rejection'); END;");
  assert.throws(()=>store.create({title:'Must roll back',owner:'echo'}),/lead fixture rejection/);
  assert.equal(store.list().length,2);db.exec('DROP TRIGGER reject_lead');db.close();
  const old=store.create({title:'Legacy'});store.workroom.save(old.id,{project:'',criteria:'',owner:'me',team:'local_build',stage:'ready',revision:0});
  store.close();store=openTaskStore(file);assert.equal(store.workroom.get(a.id).workroom.owner,'nims');assert.equal(store.workroom.get(old.id).workroom.owner,'me');
 }finally{store.close();}
});

test('planning targets the lead; Nims never silently routes to another executor; policy frozen in receipt',async()=>{
 const file=join(mkdtempSync(join(tmpdir(),'mesh-lead-plan-')),'tasks.sqlite');const store=openTaskStore(file);let sends=0;
 const relay={nativeRead:async()=>({taskSessionBinding:1}),agents:async()=>[{id:'echo',backend:'hermes',status:'idle',conversation_id:'session'}],taskMessage:async()=>{sends++;return {status:'accepted'};}};
 try{
  const nims=store.create({title:'Nims plan',owner:'nims'});
  const body={id:randomUUID(),agentId:'echo',conversationId:'session',phase:'plan'};
  await assert.rejects(sendTaskHandoff({workroom:store.workroom,taskId:nims.id,body,relay,admitted:()=>true}),/Nims is the project lead/);assert.equal(sends,0);
  const echo=store.create({title:'Echo plan',owner:'echo'});
  await assert.rejects(sendTaskHandoff({workroom:store.workroom,taskId:echo.id,body:{...body,agentId:'dsh'},relay,admitted:()=>true}),/Echo is the project lead/);
  await sendTaskHandoff({workroom:store.workroom,taskId:echo.id,body,relay,admitted:()=>true});assert.equal(sends,1);
  const send=store.workroom.get(echo.id).messages[0];assert.match(send.text,/mesh-lead\/v1/);assert.match(send.text,/AGENTS.md/);assert.match(send.text,/until Eddie locks the scope/);
 }finally{store.close();}
});

test('actual admitted HTTP creation persists selected lead with no worker dispatch',async()=>{
 const dataDir='data/lead-http-'+randomUUID();let app=await startApp({dataDir,relayEnabled:false});
 async function admit(){const r=await fetch(app.url+'/api/trial-session/bootstrap',{method:'POST',headers:{Origin:app.url,'Content-Type':'application/json'},body:'{}'});const b=await r.json();return{Origin:app.url,'Content-Type':'application/json',Cookie:r.headers.get('set-cookie').split(';')[0],'X-Trial-CSRF':b.csrfToken};}
 try{
  assert.equal((await fetch(app.url+'/api/tasks',{method:'POST',headers:{Origin:app.url,'Content-Type':'application/json'},body:JSON.stringify({title:'blocked',owner:'echo'})})).status,401);
  let headers=await admit();const r=await fetch(app.url+'/api/tasks',{method:'POST',headers,body:JSON.stringify({title:'HTTP lead',owner:'echo'})});assert.equal(r.status,201);const {task}=await r.json();
  await app.close();app=await startApp({dataDir,relayEnabled:false});headers=await admit();const saved=await (await fetch(app.url+'/api/workroom/'+task.id,{headers})).json();assert.equal(saved.task.workroom.owner,'echo');assert.equal(saved.task.messages.length,0);
 }finally{await app.close();}
});
