import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {mkdirSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {randomUUID} from 'node:crypto';
import {startApp} from '../server.mjs';
import {openTaskStore} from '../lib/task-store.mjs';

test('HTTP approval is CSRF guarded, rejects changed scope and captures a denied request result without approving task',async()=>{
  const directory='data/approval-route-'+randomUUID();mkdirSync(directory,{recursive:true});
  const keyPath=resolve(directory,'fixture-key');writeFileSync(keyPath,'fixture-only-key');
  let store=openTaskStore(resolve(directory,'tasks.sqlite'));const task=store.create({title:'Approval route fixture',description:'Read only the fixture'});const sendId=randomUUID();
  store.workroom.reserve(task.id,{id:sendId,agentId:'dsh',conversationId:'conversation',text:'Plan fixture'},'plan');store.workroom.settle(sendId,'accepted');store.close();
  let decisions=0;let pending={schema:'mesh-dsh-approval/v1',taskId:'peer',contextId:'conversation',sendId,workroomTaskId:task.id,requestId:'request',toolName:'read_file',arguments:'{"path":"fixture"}',reason:'Read fixture',canApprove:true};
  let completedTask=null;
  const native=http.createServer(async(req,res)=>{
    assert.equal(req.headers.authorization,'Bearer fixture-only-key');res.setHeader('Content-Type','application/json');
    if(req.method==='GET'){res.end(JSON.stringify({schema:'mesh-dsh-approval/v1',supported:true,pending,binding:{sendId,workroomTaskId:task.id,contextId:'conversation',taskId:'peer'},task:completedTask}));return;}
    let raw='';for await(const chunk of req)raw+=chunk;JSON.parse(raw);decisions++;pending=null;
    completedTask={id:'peer',contextId:'conversation',artifacts:[{parts:[{text:'Permission was denied; no file was read.'}]}]};
    req.socket.destroy(); // Decision happened, but its response was lost.
  });
  await new Promise(resolve=>native.listen(0,'127.0.0.1',resolve));let app;let proof={};
  const settings={MESH_RELAY_MODE:'http',MESH_DSH_APPROVAL_ORIGIN:'http://127.0.0.1:'+native.address().port,MESH_DSH_TOKEN_FILE:keyPath};const previous={};for(const [key,value] of Object.entries(settings)){previous[key]=process.env[key];process.env[key]=value;}
  async function api(route,method='GET',body,headers={}){const r=await fetch(app.url+route,{method,headers:{Origin:app.url,'Content-Type':'application/json',...proof,...headers},...(body?{body:JSON.stringify(body)}:{})});const raw=await r.text();return {status:r.status,body:raw?JSON.parse(raw):null,cookie:r.headers.get('set-cookie')};}
  try{
    app=await startApp({dataDir:directory,relayEnabled:true});const route='/api/workroom/'+task.id+'/approval';
    assert.equal((await api(route)).status,401);const boot=await api('/api/trial-session/bootstrap','POST',{});proof={Cookie:boot.cookie.split(';')[0],'X-Trial-CSRF':boot.body.csrfToken};
    assert.equal((await api(route)).body.pending.canApprove,true);
    const body={sendId,requestId:'request',decision:'allow_once'};
    assert.equal((await api(route,'POST',body,{'X-Trial-CSRF':'bad'})).status,403);assert.equal(decisions,0);
    let current=(await api('/api/workroom/'+task.id)).body.task;
    const {project,criteria,owner,team,revision}=current.workroom;
    await api('/api/workroom/'+task.id,'PATCH',{project,criteria:criteria+' changed',owner,team,revision,stage:'ready'});
    assert.equal((await api(route)).body.pending.canApprove,false);
    assert.equal((await api(route,'POST',body)).status,409);assert.equal(decisions,0);
    const denied=await api(route,'POST',{...body,decision:'reject'});assert.equal(denied.status,202,JSON.stringify(denied));assert.equal(denied.body.decisionStatus,'unconfirmed');assert.equal(decisions,1);
    const recovered=await api(route);assert.equal(recovered.status,200);assert.equal(recovered.body.task.progress.decision,'pending');assert.equal(recovered.body.task.replies.at(-1).text,'Permission was denied; no file was read.');assert.equal(decisions,1);
  }finally{if(app)await app.close();native.closeAllConnections();await new Promise(resolve=>native.close(resolve));for(const key of Object.keys(settings)){if(previous[key]===undefined)delete process.env[key];else process.env[key]=previous[key];}}
});
