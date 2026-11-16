// Inactive native entry. Only a separately approved owner launcher may supply
// the secret frame through its inherited pipe. A review reference is not consent.
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {configureMindRecall} from '../lib/mind-recall.mjs';
import {startApp} from '../server.mjs';
import {validateNativeProjectSync} from './project-sync-native-candidate.mjs';

export const frameSchema='onoes-mesh-native-recall-input/v1';
export const meshFrameSchema='onoes-mesh-native-input/v2';
const refusal=()=>new Error('Native Mesh input could not be verified.');
const exact=(value,keys)=>value && typeof value==='object' && !Array.isArray(value)
  && Object.keys(value).length===keys.length && keys.every(key=>Object.hasOwn(value,key));

function readNativeInput(input,{timeoutMs=10000,allowProjectSync=false}={}){
  // Require EOF, not merely a newline, so a second frame cannot be ignored.
  // Never put this input in arguments, environment, files, diagnostics or UI.
  return new Promise((resolve,reject)=>{
    let chunks=[],size=0,settled=false;
    const finish=(error,value)=>{
      if(settled)return;settled=true;clearTimeout(timer);
      input.off('data',data);input.off('end',end);input.off('error',errorEvent);
      input.pause();for(const chunk of chunks)chunk.fill(0);chunks=[];
      if(error)reject(refusal());else resolve(value);
    };
    const data=chunk=>{
      const copy=Buffer.from(chunk);size+=copy.length;
      if(size>16384){copy.fill(0);finish(true);return;}chunks.push(copy);
    };
    const end=()=>{
      let bytes;
      try{
        bytes=Buffer.concat(chunks);const value=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
        const legacy=exact(value,['schema','mindRecallOptions'])&&value.schema===frameSchema;
        const combined=allowProjectSync&&exact(value,['schema','mindRecallOptions','projectSyncOptions'])&&value.schema===meshFrameSchema;
        if(!legacy&&!combined)throw refusal();
        configureMindRecall({standalone:false,approvedOptions:value.mindRecallOptions});
        const approved={mindRecallOptions:value.mindRecallOptions};
        if(combined)approved.projectSyncOptions=validateNativeProjectSync(value.projectSyncOptions);
        finish(false,approved);
      }catch{finish(true);}finally{bytes?.fill(0);}
    };
    const errorEvent=()=>finish(true);
    const timer=setTimeout(()=>finish(true),timeoutMs);
    input.on('data',data);input.once('end',end);input.once('error',errorEvent);
    input.resume();
  });
}

export async function readNativeRecallInput(input,options){
  return (await readNativeInput(input,{...options,allowProjectSync:false})).mindRecallOptions;
}
export function readNativeMeshInput(input,options){
  return readNativeInput(input,{...options,allowProjectSync:true});
}

export async function startNativeMesh({input=process.stdin,appOptions={},inputTimeoutMs}={}){
  if(['mindRecallOptions','mindRecallTestOptions','projectSyncOptions','projectSyncTestOptions'].some(key=>Object.hasOwn(appOptions,key)))throw refusal();
  const approved=await readNativeMeshInput(input,{timeoutMs:inputTimeoutMs});
  // Existing startApp owns all Mesh components. The reader is an independent
  // dependency: its failure, exit or pipe closure must not close this app.
  return startApp({...appOptions,...approved});
}

export async function nativeMain(){
  try{
    if(process.argv.length!==2)throw refusal();
    const app=await startNativeMesh({appOptions:{
      port:Number(process.env.MESH_PORT ?? 3000),
      dataDir:process.env.MESH_DATA_DIR ?? 'data/mesh',
      relayEnabled:process.env.MESH_RELAY==='1',
    }});
    console.log(JSON.stringify({event:'mesh_native_listening',pid:process.pid,url:app.url,mode:app.mode}));
    let stopping=false;
    for(const signal of ['SIGINT','SIGTERM'])process.once(signal,async()=>{
      if(stopping)return;stopping=true;
      try{await app.close();}catch{process.exitCode=1;}
    });
  }catch{
    console.log(JSON.stringify({event:'mesh_native_refused'}));process.exitCode=1;
  }
}

if(process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url))await nativeMain();
