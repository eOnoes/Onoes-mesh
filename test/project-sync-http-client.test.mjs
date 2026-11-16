import test from 'node:test';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {createServer} from 'node:http';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
import {openTaskStore} from '../lib/task-store.mjs';
import {createWorkroomProjectSyncCandidate} from '../integrations/workroom-project-sync-candidate.mjs';
import {createProjectSyncHttpClient,ProjectSyncTransportError} from '../integrations/project-sync-http-client-candidate.mjs';
import {createProjectSyncRunner} from '../integrations/project-sync-runner-candidate.mjs';

const token='synthetic-service-token-0123456789';
const query={projectId:'project-A',eventId:'event-A'};
const absent={schema:'onoes-mind-project-absence/v1',storeId:'synthetic-store',scope:'project/onoes-mind/shared',
  principal:'mesh-project-sync',...query,found:false};

async function fake(t,handler){
  const server=createServer(handler);await new Promise(r=>server.listen(0,'127.0.0.1',r));
  t.after(async()=>{server.closeAllConnections();await new Promise(r=>server.close(r));});
  return `http://127.0.0.1:${server.address().port}/`;
}
function reply(res,body,status=200,extra={}){const bytes=Buffer.from(body);res.writeHead(status,{'Content-Type':'application/json','Content-Length':bytes.length,...extra});res.end(bytes);}
function client(baseUrl,extra={}){return createProjectSyncHttpClient({baseUrl,token,storeId:'synthetic-store',...extra});}

async function mind(t){
  const child=spawn('python',['-B',resolve('test/project-sync-http-fixture.py'),process.env.MIND_CANDIDATE_SOURCE||'D:/Dev/Onoes-Mind'],
    {windowsHide:true,stdio:['pipe','pipe','pipe']});
  const terminal=new Promise(r=>child.once('exit',code=>r(code)));let stderr='';child.stderr.on('data',x=>stderr+=x);
  const lines=createInterface({input:child.stdout}),iterator=lines[Symbol.asyncIterator]();
  const read=async()=>{const line=await iterator.next();assert.equal(line.done,false,stderr);return JSON.parse(line.value);};
  const options=await read();
  const rpc=async value=>{child.stdin.write(JSON.stringify(value)+'\n');return read();};
  t.after(async()=>{if(child.exitCode===null){await rpc({op:'close'});child.stdin.end();}await terminal;lines.close();});
  return {options,rpc,client:createProjectSyncHttpClient(options)};
}

test('real store transaction -> bounded HTTP -> canonical receipt; revocation holds next update',async t=>{
  const m=await mind(t),dir=mkdtempSync(join(tmpdir(),'mesh-http-sync-'));let controller;
  const store=openTaskStore(join(dir,'tasks.sqlite'),{projectSyncFactory:context=>controller=createWorkroomProjectSyncCandidate(context,{storeId:m.options.storeId,initialize:true})});
  t.after(()=>{store.close();rmSync(dir,{recursive:true,force:true});});
  const card=store.create({title:'Synthetic café card 🚀',description:'Not shared',label:'',status:'open',owner:'nims'});
  controller.link({cardId:card.id,projectId:'project-A',approvalRef:'synthetic-owner',fields:['title','stage']});
  assert.equal((await controller.outbox.drainOne(m.client)).state,'saved');
  assert.deepEqual(await m.rpc({op:'stats'}),{records:1,receipts:1});
  await m.rpc({op:'revoke'});
  store.update(card.id,{title:'Next revision',description:card.description,label:'',status:'open',revision:card.revision});
  assert.equal((await controller.outbox.drainOne(m.client)).state,'held');
  assert.equal(controller.outbox.status(card.id).at(-1).reason,'remote_refused');
  assert.deepEqual(await m.rpc({op:'stats'}),{records:1,receipts:1});
});

test('delivery runtime reconciles a committed lost reply after task-store reopen without resending',async t=>{
  const m=await mind(t),dir=mkdtempSync(join(tmpdir(),'mesh-runner-sync-')),filename=join(dir,'tasks.sqlite');
  let controller,store,runner,submits=0,lookups=0;
  const open=initialize=>openTaskStore(filename,{projectSyncFactory:context=>controller=
    createWorkroomProjectSyncCandidate(context,{storeId:m.options.storeId,initialize})});
  t.after(async()=>{await runner?.stop();store?.close();rmSync(dir,{recursive:true,force:true});});
  store=open(true);
  const card=store.create({title:'Synthetic recovery card',description:'Unshared text',label:'',status:'open',owner:'nims'});
  const eventId=controller.link({cardId:card.id,projectId:'project-A',approvalRef:'synthetic-owner',fields:['title','stage']});
  const transport={
    async lookup(query){lookups++;return m.client.lookup(query);},
    async submit(event){submits++;await m.client.submit(event);throw Error('Synthetic lost acknowledgement');},
  };
  runner=createProjectSyncRunner({outbox:controller.outbox,transport});
  await runner.runOnce();assert.equal(controller.status(card.id).state,'uncertain');
  assert.equal(submits,1);assert.equal(lookups,1);
  assert.deepEqual(await m.rpc({op:'stats'}),{records:1,receipts:1});
  await runner.stop();store.close();store=null;
  store=open(false);
  runner=createProjectSyncRunner({outbox:controller.outbox,transport});
  await runner.runOnce();
  assert.equal(controller.status(card.id).state,'saved');
  assert.equal(controller.outbox.status(card.id)[0].eventId,eventId);
  assert.equal(submits,1);assert.equal(lookups,2);
  assert.deepEqual(await m.rpc({op:'stats'}),{records:1,receipts:1});
  await runner.stop();
});

test('client rejects public hosts, credentials in URL, path overrides and unbounded timers',()=>{
  for(const baseUrl of ['https://127.0.0.1:1234/','http://localhost:1234/','http://example.invalid:1234/',
    'http://user:pass@127.0.0.1:1234/','http://127.0.0.1:1234/path','http://127.0.0.1:1234/?x=1']){
    assert.throws(()=>client(baseUrl));
  }
  assert.throws(()=>client('http://127.0.0.1:1234/',{timeoutMs:0}));
});

test('strict UTF-8, duplicate JSON keys and oversized replies are refused',async t=>{
  const duplicate=JSON.stringify(absent).replace('"found":false','"found":true,"found":false');
  for(const body of [duplicate,Buffer.from([0xff]),'x'.repeat(5000)]){
    const url=await fake(t,(_req,res)=>reply(res,body));
    await assert.rejects(client(url).lookup(query),error=>error instanceof ProjectSyncTransportError&&error.projectSyncHeld===true);
  }
});

test('wrong identity and forged or nested response shapes never confirm absence',async t=>{
  for(const body of [{...absent,storeId:'wrong'}, {...absent,scope:'agent/echo/private'}, {...absent,extra:{}}, {...absent,found:true}]){
    const url=await fake(t,(_req,res)=>reply(res,JSON.stringify(body)));
    await assert.rejects(client(url).lookup(query),error=>error.projectSyncHeld===true);
  }
});

test('redirects are not followed and never forward the service credential',async t=>{
  let forwarded=0;const target=await fake(t,(_req,res)=>{forwarded++;reply(res,JSON.stringify(absent));});
  const url=await fake(t,(_req,res)=>reply(res,'{}',302,{Location:target}));
  await assert.rejects(client(url).lookup(query));assert.equal(forwarded,0);
});

test('whole-response timeout includes a stalled body and remains uncertain',async t=>{
  const url=await fake(t,(_req,res)=>{res.writeHead(200,{'Content-Type':'application/json','Content-Length':100});res.write('{');});
  const start=Date.now();await assert.rejects(client(url,{timeoutMs:50}).lookup(query),error=>error.projectSyncHeld===false);
  assert.ok(Date.now()-start<2000);
});

test('verified 503 is unavailable while authorization errors are held',async t=>{
  for(const [status,code,held] of [[503,'unavailable',false],[401,'unauthorized',true],[409,'event_conflict',true]]){
    const url=await fake(t,(_req,res)=>reply(res,JSON.stringify({schema:'onoes-mind-project-error/v1',code}),status));
    await assert.rejects(client(url).lookup(query),error=>error.projectSyncHeld===held);
  }
});
