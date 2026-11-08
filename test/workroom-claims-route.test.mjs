import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdirSync} from 'node:fs';
import {resolve} from 'node:path';
import {randomUUID} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {startApp} from '../server.mjs';
import {openTaskStore} from '../lib/task-store.mjs';

test('HTTP claim race has one winner; guarded readback survives restart without dispatch or fake Rook health',async()=>{
 const directory='data/rook-claims-'+randomUUID();mkdirSync(directory,{recursive:true});const path=resolve(directory,'tasks.sqlite');
 const store=openTaskStore(path);const task=store.create({title:'Rook disposable claim',description:'Never dispatch a real worker'});store.close();
 const db=new DatabaseSync(path);db.prepare('UPDATE tasks SET createdAt=? WHERE id=?').run('2020-01-01T00:00:00.000Z',task.id);db.close();
 const old=process.env.MESH_SIMPLE_FLOW;process.env.MESH_SIMPLE_FLOW='1';let app,proof={};
 async function api(route,method='GET',body,extra={}){const r=await fetch(app.url+route,{method,headers:{Origin:app.url,'Content-Type':'application/json',...proof,...extra},...(body===undefined?{}:{body:JSON.stringify(body)})});const raw=await r.text();return {status:r.status,body:raw?JSON.parse(raw):null,cookie:r.headers.get('set-cookie')};}
 async function admit(){const b=await api('/api/trial-session/bootstrap','POST',{});assert.equal(b.status,201);proof={Cookie:b.cookie.split(';')[0],'X-Trial-CSRF':b.body.csrfToken};}
 try{
  app=await startApp({dataDir:directory,relayEnabled:false});const route='/api/workroom/'+task.id+'/claim';
  assert.equal((await api(route)).status,401);assert.equal((await api('/api/workroom/rook')).status,401);await admit();
  const current=(await api('/api/workroom/'+task.id)).body.task;const body={revision:0,taskRevision:current.revision,briefRevision:current.workroom.revision,progressRevision:current.progress.revision};
  assert.equal((await api(route,'POST',body,{'X-Trial-CSRF':'bad'})).status,403);
  assert.equal((await api(route,'POST',body,{Origin:'http://untrusted.invalid'})).status,403);
  assert.equal((await api(route)).body.flow,null);
  const race=await Promise.all([api(route,'POST',body),api(route,'POST',body)]);assert.deepEqual(race.map(x=>x.status).sort(),[200,409]);
  const saved=(await api(route)).body.flow;assert.equal(saved.sendId,saved.claim.dispatchId);assert.equal(saved.claim.trigger,'aged');
  assert.equal((await api('/api/workroom/'+task.id)).body.task.messages.length,0);
  const status=(await api('/api/workroom/rook')).body;assert.equal(status.connection.status,'not_configured');assert.equal(status.sweep.schedulerInstalled,false);assert.equal(status.sweep.schedulerEnabled,false);assert.equal(status.sweep.lastResult,'never');assert.equal(status.cards.length,1);assert.equal(status.cards[0].flow.claim.claimId,saved.claim.claimId);
  assert.equal((await api('/api/workroom/rook','POST',{})).status,404);
  await app.close();app=null;proof={};app=await startApp({dataDir:directory,relayEnabled:false});await admit();
  assert.deepEqual((await api(route)).body.flow,saved);assert.equal((await api(route,'POST',body)).status,409);
  assert.equal((await api('/api/workroom/'+task.id)).body.task.messages.length,0);
 }finally{if(app)await app.close();if(old===undefined)delete process.env.MESH_SIMPLE_FLOW;else process.env.MESH_SIMPLE_FLOW=old;}
});

test('private Rook status exposes exact writer holds without changing receipts or clearing assignments',async()=>{
 const directory='data/rook-holds-'+randomUUID();mkdirSync(directory,{recursive:true});const filename=resolve(directory,'tasks.sqlite');
 const store=openTaskStore(filename);const task=store.create({title:'Original writer fixture',description:'Synthetic only'});store.close();
 const db=new DatabaseSync(filename);
 db.prepare('INSERT INTO workroom_sends(id,taskId,agentId,conversationId,text,fingerprint,state,at,payload,basis,phase) VALUES(?,?,?,?,?,?,?,?,?,?,?)')
  .run('held-send',task.id,'echo','fixture-session','Synthetic held writer','fixture-hash','accepted',new Date().toISOString(),'{}','','work');
 const before=JSON.stringify(db.prepare('SELECT * FROM workroom_sends').all());let app;
 try{
  app=await startApp({dataDir:directory,relayEnabled:false});
  assert.equal((await fetch(app.url+'/api/workroom/rook')).status,401);
  const b=await fetch(app.url+'/api/trial-session/bootstrap',{method:'POST',headers:{Origin:app.url,'Content-Type':'application/json'},body:'{}'});
  const proof=await b.json(),headers={Origin:app.url,Cookie:b.headers.get('set-cookie').split(';')[0],'X-Trial-CSRF':proof.csrfToken};
  for(let n=0;n<2;n++){
   const response=await fetch(app.url+'/api/workroom/rook',{headers});assert.equal(response.status,200);const status=await response.json();
   assert.deepEqual(status.assignmentHolds,[{taskId:task.id,sendId:'held-send',state:'accepted',reason:'writer_quiescence_unproven',title:task.title}]);
  }
  assert.equal(JSON.stringify(db.prepare('SELECT * FROM workroom_sends').all()),before);
  assert.equal(db.prepare('SELECT count(*) AS n FROM workroom_claims').get().n,0);
 }finally{await app?.close();db.close();}
});

test('scheduled claim endpoint stays inert until explicitly called, enforces auth and a durable five-hour gate',async()=>{
 const directory='data/rook-scheduled-'+randomUUID();mkdirSync(directory,{recursive:true});const path=resolve(directory,'tasks.sqlite');
 const store=openTaskStore(path);const task=store.create({title:'Rook scheduled fixture',description:'No real worker or Relay'});store.close();
 const db=new DatabaseSync(path);db.prepare('UPDATE tasks SET createdAt=? WHERE id=?').run('2020-01-01T00:00:00.000Z',task.id);db.close();
 const old=process.env.MESH_SIMPLE_FLOW;delete process.env.MESH_SIMPLE_FLOW;let app,proof={};
 async function api(route,method='GET',body,extra={}){const r=await fetch(app.url+route,{method,headers:{Origin:app.url,'Content-Type':'application/json',...proof,...extra},...(body===undefined?{}:{body:JSON.stringify(body)})});const raw=await r.text();return {status:r.status,body:raw?JSON.parse(raw):null,cookie:r.headers.get('set-cookie')};}
 async function admit(){const b=await api('/api/trial-session/bootstrap','POST',{});assert.equal(b.status,201);proof={Cookie:b.cookie.split(';')[0],'X-Trial-CSRF':b.body.csrfToken};}
 try{
  app=await startApp({dataDir:directory,relayEnabled:false});assert.equal((await api('/api/workroom/claim-next','POST',{})).status,401);await admit();
  assert.equal((await api('/api/workroom/claim-next','POST',{})).status,409);
  assert.equal((await api('/api/workroom/rook')).body.sweep.schedulerEnabled,false);
  process.env.MESH_SIMPLE_FLOW='1';
  const races=await Promise.all([api('/api/workroom/claim-next','POST',{}),api('/api/workroom/claim-next','POST',{})]);assert.deepEqual(races.map(x=>x.status),[200,200]);
  const claimed=races.filter(x=>x.body.sweep.status==='claimed');assert.equal(claimed.length,1);assert.equal(races.filter(x=>x.body.sweep.status==='not_due').length,1);
  const first=claimed[0];assert.equal(first.body.sweep.taskId,task.id);
  assert.equal((await api('/api/workroom/claim-next','POST',{at:0})).status,400);
  const status=(await api('/api/workroom/rook')).body;assert.equal(status.sweep.schedulerInstalled,false);assert.equal(status.sweep.schedulerEnabled,false);assert.equal(status.sweep.lastResult,'claimed');
  assert.equal((await api('/api/workroom/'+task.id)).body.task.messages.length,0,'explicit claim does not itself dispatch');
 }finally{if(app)await app.close();if(old===undefined)delete process.env.MESH_SIMPLE_FLOW;else process.env.MESH_SIMPLE_FLOW=old;}
});
