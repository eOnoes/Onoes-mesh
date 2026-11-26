import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {readFile,realpath} from 'node:fs/promises';
import {createHash,randomUUID} from 'node:crypto';
import path from 'node:path';
import {resolveCodexDesktopPipe} from './codex-desktop-pipe.mjs';

const READ_TOOLS=new Set(['list_projects','list_threads','read_thread']);
const uuid=value=>typeof value==='string'&&/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value);
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');

// Uses the installed first-party app-tools server, never another Codex engine.
// Enrollment is trusted process configuration; no browser can supply these fields.
export async function createCodexAppTransport(options,{allowMessaging=false}={}){
  const keys=['nodePath','serverPath','nodeSha256','serverSha256','pipePath','callerThreadId'];
  if(options?.discovery==='single_local_codex_desktop')keys.push('discovery');
  if(!options||Object.keys(options).sort().join(',')!==keys.sort().join(',')||!uuid(options.callerThreadId)||
    !/^\\\\\.\\pipe\\[A-Za-z0-9_.-]{1,180}$/.test(options.pipePath??''))throw Error('Invalid native Codex reader binding.');
  async function verifySources(){for(const kind of ['node','server']){
    const filename=options[kind+'Path'],expected=options[kind+'Sha256'];
    if(typeof filename!=='string'||!path.isAbsolute(filename)||!(/^[a-f0-9]{64}$/).test(expected??''))throw Error('Invalid native Codex source binding.');
    await realpath(filename);
    if(sha(await readFile(filename))!==expected)throw Error('Native Codex source changed; review its binding.');
  }
  }
  await verifySources();
  let child,ready,closed=false,sequence=0,broken=false,reconnecting;
  const discover=options.discovery==='single_local_codex_desktop';
  const pending=new Map();
  function failed(){
    broken=true;
    for(const p of pending.values()){clearTimeout(p.timer);p.reject(Error('Native Codex connection ended; no retry was made.'));}
    pending.clear();ready=null;
  }
  function rpc(method,params){
    if(closed||!child||child.exitCode!==null||child.signalCode!==null)return Promise.reject(Error('Native Codex connection unavailable.'));
    const id=++sequence;
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{broken=true;pending.delete(id);reject(Error('Native Codex read timed out; no retry was made.'));},15000);
      pending.set(id,{resolve,reject,timer});
      child.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n',error=>{
        if(!error)return;const item=pending.get(id);pending.delete(id);if(item){clearTimeout(item.timer);item.reject(Error('Native Codex request could not be delivered.'));}
      });
    });
  }
  async function connect(){
    if(closed)throw Error('Native Codex reader is closed.');
    if(ready)return ready;
    if(child)throw Error('Native Codex reader disconnected; deliberate reconnect is required.');
    ready=(async()=>{
    await verifySources();
    const pipePath=discover?await resolveCodexDesktopPipe(options.pipePath):options.pipePath;
    if(closed)throw Error('Native Codex reader is closed.');
    child=spawn(options.nodePath,[options.serverPath],{windowsHide:true,stdio:['pipe','pipe','pipe'],
      env:{...process.env,CODEX_APP_TOOLS_PIPE_PATH:pipePath,CODEX_APP_TOOLS_DEFERRED:'0'}});
    const owned=child;
    const ownedFailure=()=>{if(child===owned)failed();};
    owned.on('error',ownedFailure);owned.on('exit',ownedFailure);child.stdin.on('error',()=>{});
    child.stderr.resume(); // Never expose native stderr, endpoint or context to HTTP/logs.
    const lines=createInterface({input:child.stdout,crlfDelay:Infinity});
    lines.on('line',line=>{
      if(child!==owned)return;
      if(line.length>12*1024*1024){failed();return;}
      let message;try{message=JSON.parse(line);}catch{failed();return;}
      // Server requests have a separate ID space. This reader declares no
      // sampling/elicitation capability and must never answer them as approvals.
      if(typeof message.method==='string'){
        if(message.id!==undefined)child.stdin.write(JSON.stringify({jsonrpc:'2.0',id:message.id,error:{code:-32601,message:'Client requests are not supported by this read-only connection.'}})+'\n');
        return;
      }
      const item=pending.get(message.id);if(!item)return;
      pending.delete(message.id);clearTimeout(item.timer);
      if(message.error)item.reject(Error('Native Codex rejected the request.'));
      else item.resolve(message.result);
    });
      await rpc('initialize',{protocolVersion:'2025-06-18',capabilities:{},clientInfo:{name:'onoes-mesh-codex-reader',version:'0.1'}});
      child.stdin.write(JSON.stringify({jsonrpc:'2.0',method:'notifications/initialized'})+'\n');
      const listed=await rpc('tools/list',{});
      for(const name of [...READ_TOOLS,...allowMessaging?['send_message_to_thread','create_thread']:[]])if(!listed.tools?.some(tool=>tool.name===name))throw Error('Native Codex reader interface changed.');
    })();
    return ready;
  }
  async function retire(owned){
    if(!owned?.pid||owned.exitCode!==null||owned.signalCode!==null)return;
    const ended=new Promise(resolve=>{owned.once('exit',resolve);owned.once('error',resolve);});
    owned.stdin.end();const timer=setTimeout(()=>owned.kill(),2000);
    await ended;clearTimeout(timer);
  }
  // Recovery is initiated by a later READ only. A failed write is never replayed.
  async function recoverForRead(){
    if(closed)throw Error('Native Codex reader is closed.');
    if(reconnecting)return reconnecting;
    if(!broken||!discover)return;
    if(pending.size)throw Error('Native requests still need confirmation.');
    reconnecting=(async()=>{const owned=child;child=null;ready=null;await retire(owned);broken=false;})();
    try{await reconnecting;}finally{reconnecting=null;}
  }
  return {
    async read(name,args){
      if(!READ_TOOLS.has(name))throw Error('This Codex connection is read-only.');
      await recoverForRead();
      try{
      await connect();
      const reply=await rpc('tools/call',{name,arguments:args,_meta:{codex_thread_id:options.callerThreadId,callId:'mesh-codex-read-'+randomUUID()}});
      if(reply?.isError||!Array.isArray(reply?.content)||reply.content.length!==1||reply.content[0].type!=='text')throw Error('Native Codex read unavailable.');
      try{return JSON.parse(reply.content[0].text);}catch{throw Error('Native Codex returned an invalid read.');}
      }catch(error){broken=true;throw error;}
    },
    async dispatch(name,args,{requestId,admitted}={}){
      let invoked=false;
      try{
        if(broken||allowMessaging!==true||!['send_message_to_thread','create_thread'].includes(name)||!uuid(requestId)||typeof admitted!=='function')throw Error('Native messaging is not enabled.');
        await connect();
        if(!admitted())throw Error('Access ended before native dispatch.');
        invoked=true;
        const reply=await rpc('tools/call',{name,arguments:args,_meta:{codex_thread_id:options.callerThreadId,callId:'mesh-codex-request-'+requestId}});
        if(reply?.isError||!Array.isArray(reply?.content)||reply.content.length!==1||reply.content[0].type!=='text')throw Error('Native dispatch was not confirmed.');
        let data=null;try{data=JSON.parse(reply.content[0].text);}catch{}
        return {acknowledged:true,data};
      }catch(error){if(!invoked)error.nativeNotSent=true;else broken=true;throw error;}
    },
    async close(){
      closed=true;failed();
      await reconnecting;
      const owned=child;child=null;await retire(owned);
    }
  };
}
