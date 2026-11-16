// Trusted native configuration only; no CLI, environment, browser or enrollment.
import {statSync,realpathSync} from 'node:fs';
import path from 'node:path';
import {createProjectSyncHttpClient} from './project-sync-http-client-candidate.mjs';
import {createWorkroomProjectSyncCandidate} from './workroom-project-sync-candidate.mjs';
import {createProjectSyncRunner} from './project-sync-runner-candidate.mjs';
import {validateProjectPeer} from '../lib/project-sync-peer.mjs';

export const captureSyncSchema='onoes-mesh-native-project-capture/v1';
export const nativeSyncSchema='onoes-mesh-native-project-sync/v2';
const exact=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&
  Object.keys(value).length===keys.length&&keys.every(key=>Object.hasOwn(value,key));
const id=value=>typeof value==='string'&&/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(value);
const fields=['title','goal','owner','stage','result','blocker'];
const fail=()=>new Error('Native project-sync binding could not be verified.');
const require=ok=>{if(!ok)throw fail();};

function validateSharing(v){
    require(exact(v.source,['databasePath','fileDevice','fileInode'])&&
      typeof v.source.databasePath==='string'&&path.isAbsolute(v.source.databasePath)&&
      v.source.databasePath===path.resolve(v.source.databasePath)&&
      ['fileDevice','fileInode'].every(k=>typeof v.source[k]==='string'&&/^(0|[1-9][0-9]{0,19})$/.test(v.source[k])));
    require(Array.isArray(v.links)&&v.links.length>=1&&v.links.length<=32);
    const cards=new Set();
    for(const link of v.links){
      require(exact(link,['cardId','projectId','approvalRef','fields'])&&id(link.cardId)&&id(link.projectId)&&
        !cards.has(link.cardId)&&typeof link.approvalRef==='string'&&link.approvalRef.trim()===link.approvalRef&&
        link.approvalRef.length>=1&&link.approvalRef.length<=300&&!/[\x00-\x1f\x7f]/.test(link.approvalRef)&&
        Array.isArray(link.fields)&&link.fields.includes('title')&&link.fields.includes('stage')&&
        new Set(link.fields).size===link.fields.length&&link.fields.every(f=>fields.includes(f)));
      cards.add(link.cardId);
    }
}

export function validateNativeProjectCapture(value){
  try{
    require(exact(value,['schema','source','storeId','links'])&&value.schema===captureSyncSchema);
    const raw=JSON.stringify(value);require(Buffer.byteLength(raw)<=12288);
    const v=JSON.parse(raw);require(id(v.storeId));validateSharing(v);return v;
  }catch{throw fail();}
}

export function prepareNativeProjectCapture(options,context={}){
  if(options===undefined)return null;
  return prepareProjectRuntime(validateNativeProjectCapture(options),context,true);
}

export function validateNativeProjectSync(value){
  try{
    require(exact(value,['schema','source','destination','links'])&&value.schema===nativeSyncSchema);
    const raw=JSON.stringify(value);require(Buffer.byteLength(raw)<=12288);
    const v=JSON.parse(raw);
    validateSharing(v);
    require(exact(v.destination,['baseUrl','token','storeId','peer']));
    validateProjectPeer(v.destination.peer);
    createProjectSyncHttpClient(v.destination); // Constructor only; no network.
    return v;
  }catch{throw fail();}
}

export function prepareNativeProjectSync(options,{filename,standalone}={}){
  if(options===undefined)return null;
  return prepareProjectRuntime(validateNativeProjectSync(options),{filename,standalone},false);
}

function prepareProjectRuntime(approved,{filename,standalone},captureOnly){
  require(standalone===false);
  const storeId=captureOnly?approved.storeId:approved.destination.storeId;
  const source=()=>{
    require(path.resolve(filename)===approved.source.databasePath&&realpathSync(filename)===approved.source.databasePath);
    const stat=statSync(filename,{bigint:true});
    require(stat.isFile()&&stat.dev.toString()===approved.source.fileDevice&&stat.ino.toString()===approved.source.fileInode);
  };
  source();
  let runner=null,attached=false;
  return {
    factory(context){
      require(!attached);source();
      // Owner preparation must already have created the schema, approved links
      // and first baseline events. Startup never initializes or repairs them.
      function verify(){
      source();
      const rows=context.db.prepare('SELECT * FROM mind_project_links ORDER BY cardId').all();
      require(rows.length===approved.links.length);
      require(context.db.prepare('SELECT count(*) AS n FROM mind_project_capture_policy').get().n===rows.length);
      for(const row of rows){
        const link=approved.links.find(link=>link.cardId===row.cardId);
        const policy=context.db.prepare('SELECT fields FROM mind_project_capture_policy WHERE cardId=?').get(row.cardId);
        require(link&&row.projectId===link.projectId&&row.storeId===storeId&&
          row.approvalRef===link.approvalRef&&policy);
        const selected=JSON.parse(policy.fields);
        require(Array.isArray(selected)&&selected.length===link.fields.length&&
          selected.every(f=>link.fields.includes(f))&&new Set(selected).size===selected.length);
      }
      }
      verify();
      const controller=createWorkroomProjectSyncCandidate(context,{storeId});
      const client=captureOnly?null:createProjectSyncHttpClient(approved.destination);
      const guarded=method=>async value=>{
        try{verify();}catch{throw Object.assign(fail(),{projectSyncLocalBinding:true});}
        return client[method](value);
      };
      if(!captureOnly)runner=createProjectSyncRunner({outbox:controller.outbox,transport:{lookup:guarded('lookup'),submit:guarded('submit')}});
      attached=true;
      return {...controller,
        capture(cardId,kind){
          if(approved.links.some(link=>link.cardId===cardId)||context.db.prepare('SELECT 1 FROM mind_project_links WHERE cardId=?').get(cardId))verify();
          return controller.capture(cardId,kind);
        },
        status(cardId){
          if(approved.links.some(link=>link.cardId===cardId)||context.db.prepare('SELECT 1 FROM mind_project_links WHERE cardId=?').get(cardId))verify();
          const value=controller.status(cardId);
          return captureOnly&&['pending','uncertain','saved'].includes(value.state)?{state:'offline'}:value;
        },
      };
    },
    start(){require(attached);source();runner?.start();},
    async close(){await runner?.stop();},
  };
}
