import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {createCodexAppTransport} from '../lib/codex-app-transport.mjs';

test('native MCP client separates request directions, declines sampling, forbids writes and never relaunches after close',{skip:process.platform!=='win32'},async()=>{
  const hash=async p=>createHash('sha256').update(await readFile(p)).digest('hex');
  const serverPath=fileURLToPath(new URL('./fixtures/codex-app-tools-fixture.mjs',import.meta.url));
  const callerThreadId='11111111-1111-4111-8111-111111111111';
  const client=await createCodexAppTransport({nodePath:process.execPath,serverPath,nodeSha256:await hash(process.execPath),serverSha256:await hash(serverPath),
    pipePath:'\\\\.\\pipe\\mesh-codex-synthetic-only',callerThreadId});
  try{
    await assert.rejects(client.read('send_message_to_thread',{}),/read-only/);
    const result=await client.read('read_thread',{threadId:callerThreadId,includeTurns:false});
    assert.equal(result.clientRequestDeclined,true);assert.equal(result.callerThreadId,callerThreadId);
  }finally{await client.close();}
  await assert.rejects(client.read('read_thread',{threadId:callerThreadId}),/closed/);
});

test('a runtime that cannot launch rejects the read and cleanup settles without a restart',{skip:process.platform!=='win32'},async()=>{
  const serverPath=fileURLToPath(new URL('./fixtures/codex-app-tools-fixture.mjs',import.meta.url));
  const hash=createHash('sha256').update(await readFile(serverPath)).digest('hex');
  const client=await createCodexAppTransport({nodePath:serverPath,serverPath,nodeSha256:hash,serverSha256:hash,pipePath:'\\\\.\\pipe\\mesh-codex-synthetic-only',callerThreadId:'11111111-1111-4111-8111-111111111111'});
  await assert.rejects(client.read('list_projects',{}));
  let timer;try{await Promise.race([client.close(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Native cleanup did not settle')),1000);})]);}finally{clearTimeout(timer);}
});

test('native dispatch requires explicit messaging mode and rechecks admission after connection',async()=>{
 const hash=async p=>createHash('sha256').update(await readFile(p)).digest('hex');
 const serverPath=fileURLToPath(new URL('./fixtures/codex-chat-app-fixture.mjs',import.meta.url));
 const callerThreadId='11111111-1111-4111-8111-111111111111';
 const options={nodePath:process.execPath,serverPath,nodeSha256:await hash(process.execPath),serverSha256:await hash(serverPath),pipePath:'\\\\.\\pipe\\mesh-synthetic-only',callerThreadId};
 const args={threadId:callerThreadId,hostId:'local',prompt:'Synthetic admission check'};
 const controls={requestId:'22222222-2222-4222-8222-222222222222',admitted:()=>true};
 const reader=await createCodexAppTransport(options);
 try{await assert.rejects(reader.dispatch('send_message_to_thread',args,controls),e=>e.nativeNotSent===true);}
 finally{await reader.close();}
 const writer=await createCodexAppTransport(options,{allowMessaging:true});
 try{
  await assert.rejects(writer.dispatch('send_message_to_thread',args,{...controls,admitted:()=>false}),e=>e.nativeNotSent===true);
  const accepted=await writer.dispatch('send_message_to_thread',args,controls);assert.equal(accepted.acknowledged,true);assert.equal(accepted.data.threadId,callerThreadId);
 }finally{await writer.close();}
});

test('desktop discovery preserves a pinned instance and refuses ambiguity without exposing endpoints',async()=>{
 const {resolveCodexDesktopPipe}=await import('../lib/codex-desktop-pipe.mjs');
 const prefix=String.raw`\\.\pipe`+'\\';
 const original='codex-app-tools-11111111-1111-4111-8111-111111111111',next='codex-app-tools-22222222-2222-4222-8222-222222222222';
 assert.equal(await resolveCodexDesktopPipe(prefix+original,{list:async()=>[original,next]}),prefix+original);
 assert.equal(await resolveCodexDesktopPipe(prefix+original,{list:async()=>['unrelated',next]}),prefix+next);
 await assert.rejects(resolveCodexDesktopPipe(prefix+original,{list:async()=>[]}),/unavailable or ambiguous/);
 await assert.rejects(resolveCodexDesktopPipe(prefix+original,{list:async()=>[next,'codex-app-tools-33333333-3333-4333-8333-333333333333']}),/unavailable or ambiguous/);
 await assert.rejects(resolveCodexDesktopPipe('unapproved-endpoint',{list:async()=>[next]}),/reviewed local endpoint/);
});

test('after a failed synthetic native call a later read may reconnect, but the write is never replayed',{skip:!process.env.CODEX_APP_TOOLS_PIPE_PATH},async()=>{
 const hash=async p=>createHash('sha256').update(await readFile(p)).digest('hex');
 const serverPath=fileURLToPath(new URL('./fixtures/codex-chat-app-fixture.mjs',import.meta.url));
 const callerThreadId='11111111-1111-4111-8111-111111111111';
 const client=await createCodexAppTransport({nodePath:process.execPath,serverPath,nodeSha256:await hash(process.execPath),serverSha256:await hash(serverPath),pipePath:process.env.CODEX_APP_TOOLS_PIPE_PATH,callerThreadId,discovery:'single_local_codex_desktop'},{allowMessaging:true});
 try{
  await client.read('read_thread',{threadId:callerThreadId,includeTurns:false});
  await assert.rejects(client.dispatch('send_message_to_thread',{threadId:callerThreadId,hostId:'local',prompt:'SYNTHETIC_LOST_ACK'},{requestId:'22222222-2222-4222-8222-222222222222',admitted:()=>true}),e=>!e.nativeNotSent);
  const result=await client.read('read_thread',{threadId:callerThreadId,includeTurns:true});
  assert.deepEqual(result.turns[0].items,[],'the new synthetic peer received no replay of the earlier write');
 }finally{await client.close();}
});

test('a persistent local namespace discovers one instance and refuses two without saving an endpoint',async()=>{
 const {resolveCodexDesktopPipe,CODEX_DESKTOP_NAMESPACE}=await import('../lib/codex-desktop-pipe.mjs');
 const a='codex-app-tools-11111111-1111-4111-8111-111111111111',b='codex-app-tools-22222222-2222-4222-8222-222222222222';
 const selected=await resolveCodexDesktopPipe(CODEX_DESKTOP_NAMESPACE,{list:async()=>[a]});assert.ok(selected.endsWith(a));
 await assert.rejects(resolveCodexDesktopPipe(CODEX_DESKTOP_NAMESPACE,{list:async()=>[a,b]}),/unavailable or ambiguous/);
});
