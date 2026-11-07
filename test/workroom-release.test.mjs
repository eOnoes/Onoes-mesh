import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync,mkdirSync,copyFileSync,writeFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {randomUUID} from 'node:crypto';
import http from 'node:http';
import {DatabaseSync} from 'node:sqlite';
import {startApp} from '../server.mjs';

test('isolated backup restores through HTTP, preserves provenance and survives restart; session and stale edits fail closed',async()=>{
  const receipt=JSON.parse(readFileSync(resolve('../workroom-backup-latest.json'),'utf8'));
  const directory='data/workroom-restore-http-'+randomUUID();mkdirSync(directory,{recursive:true});
  copyFileSync(receipt.snapshot,join(directory,'tasks.sqlite'),1);
  let clock=Date.now();let app;let proof={};const originalLog=console.log;const logs=[];
  console.log=(...args)=>logs.push(args.join(' '));
  async function request(path,{method='GET',body,headers={}}={}){
    const response=await fetch(app.url+path,{method,headers:{Origin:app.url,'Content-Type':'application/json',...proof,...headers},...(body?{body:JSON.stringify(body)}:{})});
    const raw=await response.text();return {status:response.status,body:raw?JSON.parse(raw):null,cookie:response.headers.get('set-cookie')};
  }
  async function admit(){const r=await request('/api/trial-session/bootstrap',{method:'POST',body:{}});assert.equal(r.status,201);proof={Cookie:r.cookie.split(';')[0],'X-Trial-CSRF':r.body.csrfToken};}
  try{
    app=await startApp({dataDir:directory,relayEnabled:false,sessionNow:()=>clock});
    assert.equal((await request('/api/workroom')).status,401);await admit();
    const restored=(await request('/api/workroom')).body.tasks;assert.equal(restored.length,receipt.taskCount);
    const trial=restored.find(t=>t.id==='af28664b-fa63-4f3a-beca-453a66ccbf15');assert.ok(trial);assert.ok(trial.agentUpdates.some(r=>r.applied));const snapshotDb=new DatabaseSync(receipt.snapshot,{readOnly:true});try{assert.equal(trial.progress.decision,snapshotDb.prepare('SELECT decision FROM workroom_progress WHERE taskId=?').get(trial.id).decision);}finally{snapshotDb.close();}
    const created=await request('/api/tasks',{method:'POST',body:{title:'<long-title> '+ 'x'.repeat(147),description:'Description '.repeat(150),label:'Release rehearsal',status:'open'}});assert.equal(created.status,201);
    let task=(await request('/api/workroom/'+created.body.task.id)).body.task;
    const fields={project:'Release rehearsal',criteria:'No execution',owner:'',team:'local_build',stage:'ready',revision:task.workroom.revision};
    assert.equal((await request('/api/workroom/'+task.id,{method:'PATCH',body:fields})).status,200);
    assert.equal((await request('/api/workroom/'+task.id,{method:'PATCH',body:{...fields,stage:'working'}})).status,409);
    assert.equal((await request('/api/workroom/'+task.id,{method:'PATCH',body:fields,headers:{'X-Trial-CSRF':'invalid'}})).status,403);
    await new Promise((resolveRequest,reject)=>{const req=http.request(app.url+'/api/workroom?token=SECRET_MUST_NOT_LOG',{headers:{Origin:'https://SECRET_MUST_NOT_LOG.invalid',Host:'SECRET_MUST_NOT_LOG'}},res=>{res.resume();res.on('end',()=>{assert.equal(res.statusCode,403);resolveRequest();});});req.on('error',reject);req.end();});
    assert.ok(!logs.join('\n').includes('SECRET_MUST_NOT_LOG'));
    clock+=300001;assert.equal((await request('/api/workroom')).status,401);proof={};await admit();
    assert.ok((await request('/api/workroom')).body.tasks.some(t=>t.id===task.id));
    await app.close();app=await startApp({dataDir:directory,relayEnabled:false});proof={};await admit();
    const after=(await request('/api/workroom/'+task.id)).body.task;assert.equal(after.title,created.body.task.title);assert.equal(after.workroom.stage,'ready');
    const finalTrial=(await request('/api/workroom/'+trial.id)).body.task;assert.deepEqual(finalTrial.messages,trial.messages);assert.equal(finalTrial.replies.length,trial.replies.length);assert.deepEqual(finalTrial.progress,trial.progress);
    writeFileSync(join(directory,'rehearsal.json'),JSON.stringify({status:'PASS',at:new Date().toISOString(),sourceSnapshot:receipt.snapshot,restoredTaskCount:restored.length,createdTask:task.id,restart:'PASS',sessionExpiry:'PASS',staleEdit:'PASS',csrf:'PASS',logRedaction:'PASS',provenance:'PASS'},null,2));
  }finally{if(app)await app.close();console.log=originalLog;}
});
