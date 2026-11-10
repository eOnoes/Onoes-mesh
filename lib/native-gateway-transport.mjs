import {spawn} from 'node:child_process';
import {isAbsolute} from 'node:path';
import {fileURLToPath} from 'node:url';
import {TaskError} from './task-store.mjs';
import {localSessionProfile} from './workroom-local-sessions.mjs';

const methods=new Set(['session.create','prompt.submit','prompt.lookup']);
const limit=1024*1024;
const unavailable=()=>new TaskError(503,'Native transport unavailable. Reconcile the saved request; nothing was replayed.');
const helper=fileURLToPath(new URL('../integrations/native_gateway_transport.py',import.meta.url));

// Lazy, trusted process configuration. No discovery, authentication or child
// process until the first authorized binding RPC. Failure never reconnects.
export function createNativeGatewayTransport({nativeRoot,home,pythonExecutable,timeoutMs=30000,spawnImpl=spawn}={}) {
  if (![nativeRoot,home,pythonExecutable].every(value=>typeof value==='string'&&isAbsolute(value))
      || !Number.isSafeInteger(timeoutMs)||timeoutMs<1||timeoutMs>120000||typeof spawnImpl!=='function')
    throw new TaskError(400,'Explicit local native runtime paths and a bounded timeout are required.');
  let child,dead=false,closing,serial=0,buffer=Buffer.alloc(0),exited;
  const pending=new Map();
  function fail() {
    dead=true;
    for(const item of pending.values()){clearTimeout(item.timer);item.reject(unavailable());}
    pending.clear();child?.stdin.end();
  }
  function receive(chunk) {
    if(dead)return;
    buffer=Buffer.concat([buffer,chunk]);
    for(;;){
      const end=buffer.indexOf(10);
      if(end<0){if(buffer.length>limit)fail();return;}
      if(end>limit){fail();return;}
      const line=buffer.subarray(0,end);buffer=buffer.subarray(end+1);
      let frame;try{frame=JSON.parse(line.toString('utf8'));}catch{fail();return;}
      if(frame?.type==='fatal'){fail();return;}
      const item=pending.get(frame?.id);
      if(!item){fail();return;}
      const result=Object.hasOwn(frame,'result'),error=Object.hasOwn(frame,'error');
      if(result===error){fail();return;}
      pending.delete(frame.id);clearTimeout(item.timer);
      if(error)item.reject(unavailable());else item.resolve(frame.result);
    }
  }
  function start() {
    const allowed=new Set(['PATH','SYSTEMROOT','WINDIR','TEMP','TMP','USERPROFILE','LOCALAPPDATA','APPDATA']);
    const env=Object.fromEntries(Object.entries(process.env).filter(([key])=>allowed.has(key.toUpperCase())));
    Object.assign(env,{HERMES_HOME:home,PYTHONUTF8:'1'});
    child=spawnImpl(pythonExecutable,['-u',helper,'--native-root',nativeRoot,'--home',home],
      {windowsHide:true,shell:false,stdio:['pipe','pipe','pipe'],env});
    exited=new Promise(resolve=>child.once('close',()=>{fail();resolve();}));
    child.on('error',fail);child.stdin.on('error',fail);
    child.stdout.on('data',receive);
    // Native diagnostics may contain private details. Drain, never surface them.
    child.stderr.on('data',()=>{});
  }
  const waitExit=ms=>new Promise(resolve=>{
    const timer=setTimeout(()=>resolve(false),ms);
    exited.then(()=>{clearTimeout(timer);resolve(true);});
  });
  return Object.freeze({
    rpc(method,params) {
      if(!methods.has(method)||!params||typeof params!=='object'||Array.isArray(params))
        return Promise.reject(new TaskError(400,'Unsupported native transport request.'));
      if(dead)return Promise.reject(unavailable());
      if(pending.size>=32)return Promise.reject(new TaskError(503,'Native request capacity reached.'));
      const id=++serial;
      let frame;try{frame=Buffer.from(JSON.stringify({id,method,params})+'\n');}catch{return Promise.reject(new TaskError(400,'Invalid native request.'));}
      if(frame.length>limit)return Promise.reject(new TaskError(400,'Native request is too large.'));
      return new Promise((resolve,reject)=>{
        const timer=setTimeout(fail,timeoutMs);pending.set(id,{resolve,reject,timer});
        try{if(!child)start();child.stdin.write(frame);}catch{fail();}
      });
    },
    close() {
      if(closing)return closing;
      fail();
      return closing=(async()=>{
        if(!child)return;
        if(await waitExit(1000))return;
        child.kill(); // Only this bridge process, never the gateway or its workers.
        if(!await waitExit(5000))throw new TaskError(503,'Native bridge exit could not be confirmed.');
      })();
    },
  });
}

// Pass the result to startApp({nativeWorkerOptions: ...}) only after reviewing
// the enrollment. This helper does not activate the normal launcher or grant it.
export function nativeGatewayWorkerOptions({profile,authorized,...transportOptions}) {
  const fixed=localSessionProfile(profile);
  if(fixed.provider!=='openai-codex'||typeof authorized!=='function')
    throw new TaskError(400,'A reviewed native Codex profile and explicit authorization gate are required.');
  const transport=createNativeGatewayTransport(transportOptions);
  return {profile:fixed,authorized,rpc:transport.rpc,close:transport.close};
}
