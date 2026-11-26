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
