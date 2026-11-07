import {randomUUID} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createModelOperationStore,NEMOTRON_MODEL,nativeCommandFingerprint} from '../lib/model-operation-store.mjs';
import {createSupervisedInference} from '../lib/supervised-inference.mjs';
export function supervisedModelFixture(){
  const db=new DatabaseSync(join(mkdtempSync(join(tmpdir(),'mesh-supervised-')),'tasks.sqlite'));
  const operations=createModelOperationStore(db);let at=Date.now();
  const metadata={schemaVersion:'mesh-supervisor-control/v1',moduleSha256:'a'.repeat(64),supervisorSha256:'b'.repeat(64),bootId:randomUUID(),modelId:NEMOTRON_MODEL};
  let native={...metadata,expected:'c'.repeat(64),owner:{state:'empty',identity:null,clear:true},active:null,load:true,unload:false};
  const receipts=new Map(),calls=[];let deliveryLost=false,readLost=false,unverified=false;
  const client={status:async()=>structuredClone(native),command:async(binding,{admitted})=>{
    if(!admitted())throw Object.assign(Error(),{code:'ADMISSION_EXPIRED',notSent:true});
    calls.push(binding);const envelope={...metadata,receipt:{id:binding.command.id,action:binding.command.action,fingerprint:nativeCommandFingerprint(binding.command),state:'ACCEPTED',readBackVerified:false,ownerCallStarted:false}};
    receipts.set(binding.command.id,envelope);native={...native,expected:'d'.repeat(64),active:binding.command.id};
    if(deliveryLost)throw Object.assign(Error(),{code:'BRIDGE_UNAVAILABLE'});return structuredClone(envelope);
  },receipt:async binding=>{if(readLost)throw Object.assign(Error(),{code:'BRIDGE_UNAVAILABLE'});return structuredClone(receipts.get(binding.command.id));}};
  function finish(id){const e=receipts.get(id);e.receipt={...e.receipt,state:'COMPLETED',readBackVerified:true,ownerCallStarted:true};
    const loaded=e.receipt.action==='load';native={...native,expected:'e'.repeat(64),active:null,load:!loaded,unload:loaded,
      owner:loaded?{state:'resident',modelId:NEMOTRON_MODEL,ownerVerified:true,identity:{pid:123,createdAt:'2026-11-07T12:00:00Z',executable:'D:/models/nemotron/tools/llama-b11669-cuda12.4/llama-server.exe',executableSha256:'f'.repeat(64),argvHash:'1'.repeat(64),cwd:'D:/models/nemotron/tools/llama-b11669-cuda12.4'}}:{state:'empty',identity:null,clear:true}};}
  const options={client,qualification:{source:'disposable_fixture',executableSha256:'f'.repeat(64)},now:()=>at,
    verifyResident:async()=>({healthy:!unverified,gpuMapping:unverified?'UNKNOWN':'VERIFIED',gpuUuids:['GPU-fixture']}),chatImpl:async()=> 'Fixture answer'};
  const make=()=>createSupervisedInference({...options,operations});
  return {db,operations,client,calls,receipts,make,finish,options,advance:n=>{at+=n;},loseDelivery:()=>{deliveryLost=true;},loseRead:v=>{readLost=v;},unverify:()=>{unverified=true;},setNative:v=>{native=v;},getNative:()=>native};
}
