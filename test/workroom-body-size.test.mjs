import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {mkdirSync} from 'node:fs';
import {resolve} from 'node:path';
import {randomUUID} from 'node:crypto';
import {startApp} from '../server.mjs';
import {openTaskStore} from '../lib/task-store.mjs';

test('valid maximum Workroom progress round-trips while rich bodies retain auth, schema and byte bounds',async()=>{
 const dataDir='data/workroom-size-'+randomUUID();mkdirSync(dataDir,{recursive:true});const store=openTaskStore(resolve(dataDir,'tasks.sqlite'));const task=store.create({title:'Disposable large-document fixture',description:''});
 let done=store.workroom.get(store.create({title:'Disposable feedback fixture',description:''}).id);done=store.workroom.save(done.id,{project:'Fixture',criteria:'Fixture only',owner:'nims',team:'local_build',stage:'ready',revision:done.workroom.revision});done=store.workroom.saveProgress(done.id,{goal:'Fixture result',checklist:[{id:'one',text:'Fixture check',status:'done'}],result:'Synthetic result',evidence:'Synthetic evidence',reviewer:'Fixture reviewer',decision:'approved',revision:done.progress.revision,taskRevision:done.revision,briefRevision:done.workroom.revision});done=store.workroom.save(done.id,{...Object.fromEntries(['project','criteria','owner','team','revision'].map(k=>[k,done.workroom[k]])),stage:'done'});
 store.close();const app=await startApp({dataDir,relayEnabled:false});let proof={};
 const api=async(path,method='GET',body,extra={})=>{const r=await fetch(app.url+path,{method,headers:{Origin:app.url,'Content-Type':'application/json',...proof,...extra},...(body===undefined?{}:{body:typeof body==='string'?body:JSON.stringify(body)})});const raw=await r.text();return {status:r.status,body:raw?JSON.parse(raw):null,cookie:r.headers.get('set-cookie')};};
 const route='/api/workroom/'+task.id+'/progress';
 try{
  assert.equal((await api(route,'PATCH','x'.repeat(5000))).status,401);
  const boot=await api('/api/trial-session/bootstrap','POST',{});assert.equal(boot.status,201);proof={Cookie:boot.cookie.split(';')[0],'X-Trial-CSRF':boot.body.csrfToken};
  const t=(await api('/api/workroom/'+task.id)).body.task;
  const body={goal:'\u001f'.repeat(2000),checklist:Array.from({length:30},(_,i)=>({id:String(i).padStart(3,'0')+'s'.repeat(97),text:'\u001f'.repeat(300),status:'pending'})),result:'\u001f'.repeat(4000),evidence:'\u001f'.repeat(4000),reviewer:'\u001f'.repeat(100),decision:'pending',revision:t.progress.revision,taskRevision:t.revision,briefRevision:t.workroom.revision};
  assert.ok(Buffer.byteLength(JSON.stringify(body))>100000);
  assert.equal((await api(route,'PATCH',body,{'X-Trial-CSRF':'wrong'})).status,403);
  assert.equal((await api(route,'PATCH',body,{Origin:'http://foreign.invalid'})).status,403);
  assert.equal((await api(route,'PATCH',body)).status,200);
  let saved=(await api('/api/workroom/'+task.id)).body.task;
  assert.deepEqual(saved.progress.checklist,body.checklist);assert.equal(saved.progress.goal,body.goal);assert.equal(saved.progress.result,body.result);assert.equal(saved.progress.evidence,body.evidence);
  const invalid={...body,result:'x'.repeat(4001),revision:saved.progress.revision};assert.equal((await api(route,'PATCH',invalid)).status,400);
  assert.equal((await api(route,'PATCH',' '.repeat(128*1024+1))).status,413);
  const chunked=await new Promise((resolve,reject)=>{const r=http.request(app.url+route,{method:'PATCH',headers:{Origin:app.url,'Content-Type':'application/json',...proof}},res=>{res.resume();res.on('end',()=>resolve(res.statusCode));});r.on('error',reject);r.write(Buffer.alloc(128*1024,32));r.end(' ');});assert.equal(chunked,413);
  assert.equal((await api('/api/tasks','POST',{title:'Unrelated legacy bound',description:'x'.repeat(5000)})).status,413);
  assert.equal((await api(route,'PATCH',{...body,revision:saved.progress.revision,capabilities:['write']})).status,403);
  const brief={project:'\u001f'.repeat(160),criteria:'\u001f'.repeat(4000),owner:'n'.repeat(100),team:'local_build',stage:'ready',revision:saved.workroom.revision};
  assert.equal((await api('/api/workroom/'+task.id,'PATCH',brief)).status,200);
  assert.equal((await api('/api/workroom/'+task.id,'PATCH',' '.repeat(32*1024+1))).status,413);
  const owner={decision:'changes_requested',note:'\u001f'.repeat(2000),revision:0,taskRevision:done.revision,briefRevision:done.workroom.revision,progressRevision:done.progress.revision};
  assert.equal((await api('/api/workroom/'+done.id+'/owner-review','POST',owner)).status,200);
  assert.equal((await api('/api/workroom/'+done.id)).body.task.flow.ownerNote,owner.note);
  assert.equal((await api('/api/workroom/'+done.id+'/owner-review','POST',' '.repeat(16*1024+1))).status,413);
  const after=(await api('/api/workroom/'+task.id)).body.task;assert.equal(after.progress.revision,saved.progress.revision);assert.equal(after.status,'open');assert.equal(after.messages.length,0);
 }finally{await app.close();}
});
