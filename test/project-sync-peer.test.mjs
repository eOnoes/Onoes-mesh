import test from 'node:test';
import assert from 'node:assert/strict';
import {createServer} from 'node:http';
import {spawn} from 'node:child_process';
import {createProjectSyncHttpClient} from '../integrations/project-sync-http-client-candidate.mjs';
import {projectProcessCreationTicks} from '../lib/project-sync-peer.mjs';

const token='synthetic-pinned-client-token-0123456789';
const query={projectId:'project-A',eventId:'event-A'};
const peer=(pid,creationTicks)=>({pid,creationTicks,runId:'0'.repeat(32),profileSha256:'0'.repeat(64)});
const client=(port,owner)=>createProjectSyncHttpClient({baseUrl:`http://127.0.0.1:${port}/`,token,storeId:'synthetic-store',peer:owner,timeoutMs:1500});

async function listener(port=0){
  const source=`import net from 'node:net';let bytes=0;const sockets=new Set();
const server=net.createServer(s=>{sockets.add(s);s.on('close',()=>sockets.delete(s));s.on('data',b=>bytes+=b.length);});
server.listen(Number(process.argv[1]),'127.0.0.1',()=>console.log(JSON.stringify({port:server.address().port,pid:process.pid})));
process.on('message',m=>{if(m==='bytes')process.send(bytes);if(m==='close'){for(const s of sockets)s.destroy();server.close(()=>process.exit(0));}});`;
  const child=spawn(process.execPath,['--input-type=module','-e',source,String(port)],{windowsHide:true,stdio:['ignore','pipe','pipe','ipc']});
  const terminal=new Promise(r=>child.once('exit',r));let output='';
  try{
    const ready=await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(Error('Owned listener did not start')),5000);
      child.once('error',e=>{clearTimeout(timer);reject(e);});
      child.stdout.on('data',b=>{output+=b;if(output.includes('\n')){clearTimeout(timer);try{resolve(JSON.parse(output));}catch(e){reject(e);}}});
    });
    assert.equal(ready.pid,child.pid);
    return {child,port:ready.port,
      async bytes(){return new Promise(r=>{child.once('message',r);child.send('bytes');});},
      async close(){if(child.exitCode===null&&child.signalCode===null)child.send('close');await terminal;}};
  }catch(error){child.kill();await terminal;throw error;}
}

test('Windows established-socket owner succeeds; wrong creation stamp sends no HTTP request',{skip:process.platform!=='win32'},async t=>{
  let received=0;
  const server=createServer((req,res)=>{
    received++;assert.equal(req.headers.authorization,'Bearer '+token);req.resume();
    const body=JSON.stringify({schema:'onoes-mind-project-absence/v1',storeId:'synthetic-store',principal:'mesh-project-sync',scope:'project/onoes-mind/shared',...query,found:false});
    res.writeHead(200,{'Content-Type':'application/json','Content-Length':Buffer.byteLength(body)});res.end(body);
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));t.after(async()=>{server.closeAllConnections();await new Promise(r=>server.close(r));});
  const stamp=await projectProcessCreationTicks(process.pid),port=server.address().port;
  assert.equal((await client(port,peer(process.pid,stamp)).lookup(query)).found,false);
  await assert.rejects(client(port,peer(process.pid,(BigInt(stamp)+1n).toString())).lookup(query),e=>e.projectSyncHeld===true);
  assert.equal(received,1);
});

test('foreign listener receives zero credential/header/body bytes',{skip:process.platform!=='win32'},async t=>{
  const foreign=await listener();t.after(()=>foreign.close());
  const stamp=await projectProcessCreationTicks(process.pid);
  await assert.rejects(client(foreign.port,peer(process.pid,stamp)).lookup(query),e=>e.projectSyncLocalBinding===true);
  assert.equal(await foreign.bytes(),0);
});

test('a reused service port cannot receive credentials after the expected process exits',{skip:process.platform!=='win32'},async t=>{
  const first=await listener(),stamp=await projectProcessCreationTicks(first.child.pid),port=first.port;
  const expected=peer(first.child.pid,stamp);await first.close();
  const replacement=await listener(port);t.after(()=>replacement.close());
  await assert.rejects(client(port,expected).lookup(query));
  assert.equal(await replacement.bytes(),0);
});
