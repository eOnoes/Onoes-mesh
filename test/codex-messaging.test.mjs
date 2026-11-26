import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,rm,readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import {randomUUID,createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {openCodexRequestStore} from '../lib/codex-request-store.mjs';
import {createCodexMessaging} from '../lib/codex-messaging.mjs';

const target='22222222-2222-4222-8222-222222222222',projectId='33333333-3333-4333-8333-333333333333',created='44444444-4444-4444-8444-444444444444';
const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
async function fixture(t,dispatch){
  const root=await mkdtemp(path.join(tmpdir(),'mesh-codex-receipts-'));const filename=path.join(root,'receipts.sqlite');
  const store=openCodexRequestStore(filename);const calls=[];
  const api=createCodexMessaging({store,scopeKey:'project-scope',verifyCaller:async()=>{},inspect:async id=>{if(![target,created].includes(id))throw Error('Wrong native scope');},
    project:async()=>({projectId}),transport:{async dispatch(...args){calls.push(args);return dispatch?dispatch(...args):{acknowledged:true,data:{threadId:target,hostId:'local'}};}}});
  t.after(async()=>{await api.close();store.close();assert.equal(path.dirname(root),path.resolve(tmpdir()));await rm(root,{recursive:true,force:true});});
  return {api,store,calls,filename};
}
const message=()=>({requestId:randomUUID(),threadId:target,text:'A synthetic message, not a live agent call.'});

test('duplicate and concurrent request IDs invoke native send only once',async t=>{
  const f=await fixture(t);const input=message();const results=await Promise.all([f.api.send(input,()=>true),f.api.send(input,()=>true)]);
  assert.equal(f.calls.length,1);assert.ok(results.every(r=>['dispatching','accepted'].includes(r.state)));
  const repeated=await f.api.send(input,()=>true);assert.equal(repeated.state,'accepted');assert.equal(f.calls.length,1);
  assert.deepEqual(f.calls[0][1],{threadId:target,hostId:'local',prompt:input.text});
});
test('lost native acknowledgement survives reopen and never resends the same request',async t=>{
  const f=await fixture(t,async()=>{throw Error('Synthetic response lost after possible delivery');});const input=message();
  assert.equal((await f.api.send(input,()=>true)).state,'unconfirmed');
  const second=openCodexRequestStore(f.filename);try{
    assert.equal(second.get('project-scope',input.requestId).state,'unconfirmed');
    assert.equal((await f.api.send(input,()=>true)).state,'unconfirmed');assert.equal(f.calls.length,1);
    await assert.rejects(f.api.send({...input,requestId:randomUUID()},()=>true),/unconfirmed send/);assert.equal(f.calls.length,1);
  }finally{second.close();}
});
test('a durable claim with no acknowledgement is not interpreted as retirement or a retry opportunity',async t=>{
  const f=await fixture(t);const input=message();
  f.store.claim('project-scope',{requestId:input.requestId,kind:'send',targetId:target,hash:hash(['send',target,input.text])});
  const result=await f.api.send(input,()=>true);assert.equal(result.state,'dispatching');assert.equal(f.calls.length,0);
});
test('reusing an ID for another message is refused without a second native call',async t=>{
  const f=await fixture(t);const input=message();await f.api.send(input,()=>true);
  await assert.rejects(f.api.send({...input,text:'Changed message'},()=>true),/already belongs/);assert.equal(f.calls.length,1);
});
test('session expiry and wrong native scope cannot dispatch',async t=>{
  const f=await fixture(t);await assert.rejects(f.api.send(message(),()=>false),/Reconnect/);
  await assert.rejects(f.api.send({...message(),threadId:randomUUID()},()=>true),/Wrong native scope/);assert.equal(f.calls.length,0);
});
test('a local before-dispatch refusal is retained as not sent, not as accepted',async t=>{
  const f=await fixture(t,async()=>{const error=Error('Access ended before native dispatch');error.nativeNotSent=true;throw error;});
  assert.equal((await f.api.send(message(),()=>true)).state,'not_sent');
});
test('native success without an acknowledgement or with a wrong target stays unconfirmed',async t=>{
  const f=await fixture(t,async()=>({acknowledged:true,data:{threadId:created}}));
  assert.equal((await f.api.send(message(),()=>true)).state,'unconfirmed');
  const missing=await fixture(t,async()=>null);assert.equal((await missing.api.send(message(),()=>true)).state,'unconfirmed');
});
test('New chat uses the approved project and local defaults without model or permission overrides',async t=>{
  const f=await fixture(t,async()=>({acknowledged:true,data:{threadId:created,hostId:'local'}}));
  const result=await f.api.create({requestId:randomUUID(),projectId,title:'  New idea  ',text:'Synthetic new-chat fixture'},()=>true);
  assert.equal(result.state,'accepted');assert.equal(result.nativeThreadId,created);
  assert.deepEqual(f.calls[0][1],{prompt:'Synthetic new-chat fixture',title:'New idea',target:{type:'project',projectId,environment:{type:'local'}}});
  await assert.rejects(f.api.create({requestId:randomUUID(),projectId:randomUUID(),title:'Wrong project',text:'Synthetic'},()=>true),/approved native project/);
  assert.equal(f.calls.length,1);
});
test('a queued client ID is never treated as a ready native thread ID',async t=>{
  const f=await fixture(t,async()=>({acknowledged:true,data:{clientThreadId:created}}));
  const result=await f.api.create({requestId:randomUUID(),projectId,title:'',text:'Synthetic pending setup'},()=>true);
  assert.equal(result.state,'accepted');assert.equal(result.nativeThreadId,null);assert.equal(result.clientThreadId,created);
});
test('HTTP-style input cannot add native model, host, caller, approval or branch settings',async t=>{
  const f=await fixture(t);
  for(const key of ['model','hostId','callerThreadId','approvalPolicy','target'])await assert.rejects(f.api.send({...message(),[key]:'untrusted'},()=>true));
  assert.equal(f.calls.length,0);
});
test('receipt persistence contains hashes and routing metadata, never message text',async t=>{
  const f=await fixture(t);const input={...message(),text:'synthetic_body_must_never_be_persisted_398f057a'};await f.api.send(input,()=>true);
  for(const file of [f.filename,f.filename+'-wal'])assert.equal((await readFile(file)).includes(Buffer.from(input.text)),false);
});
test('an unrelated SQLite store is rejected without rewriting it',async t=>{
  const root=await mkdtemp(path.join(tmpdir(),'mesh-codex-foreign-'));const filename=path.join(root,'other.sqlite');
  const db=new DatabaseSync(filename);db.exec('CREATE TABLE other(value TEXT); PRAGMA user_version=7;');db.close();const before=await readFile(filename);
  assert.throws(()=>openCodexRequestStore(filename),/Unrecognized/);assert.deepEqual(await readFile(filename),before);
  assert.equal(path.dirname(root),path.resolve(tmpdir()));await rm(root,{recursive:true,force:true});
});

test('online receipt backup and restored app preserve unresolved claims without replay',async t=>{
 const f=await fixture(t,async()=>{throw Error('Synthetic acknowledgement loss');});
 const input=message();await f.api.send(input,()=>true);
 const {backupCodexRequests}=await import('../lib/codex-request-backup.mjs');
 const receipt=await backupCodexRequests(f.filename,path.join(path.dirname(f.filename),'backup'));
 assert.equal(receipt.restore,'PASS');assert.equal(receipt.count,1);
 const restored=openCodexRequestStore(receipt.restored);
 try{assert.equal(restored.get('project-scope',input.requestId).state,'unconfirmed');}
 finally{restored.close();}
 assert.equal(f.calls.length,1);assert.match(receipt.note,/Never overwrite newer receipts/);
});

test('receipt recognition never admits an unrelated or changed native prompt',async t=>{
 const f=await fixture(t);const input=message();await f.api.send(input,()=>true);
 assert.equal(f.store.knowsNativePrompt('project-scope',target,'send_message_to_thread',input.text),true);
 assert.equal(f.store.knowsNativePrompt('project-scope',target,'send_message_to_thread','Different text'),false);
 assert.equal(f.store.knowsNativePrompt('other-scope',target,'send_message_to_thread',input.text),false);
 assert.equal(f.store.knowsNativePrompt('project-scope',created,'send_message_to_thread',input.text),false);
 assert.equal(f.store.knowsNativePrompt('project-scope',target,'read_file',input.text),false);
});
