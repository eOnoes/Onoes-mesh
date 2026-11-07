import {randomUUID} from 'node:crypto';
import {TaskError} from './task-store.mjs';
import {NEMOTRON_MODEL} from './model-operation-store.mjs';
const exact=(v,keys)=>v&&Object.getPrototypeOf(v)===Object.prototype&&Object.keys(v).length===keys.length&&keys.every(k=>Object.hasOwn(v,k));
const sha=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const normalized=v=>typeof v==='string'?v.replaceAll('\\','/').toLowerCase():'';
const EXE='D:/models/nemotron/tools/llama-b11669-cuda12.4/llama-server.exe';
export function createSupervisedInference({operations,client,qualification,verifyResident,chatImpl,now=Date.now}={}){
  if(!['qualified_native','disposable_fixture'].includes(qualification?.source)||!sha(qualification.executableSha256)||!operations||!client||typeof verifyResident!=='function')throw Error('Qualified supervised model dependencies required');
  const profile=Object.freeze({nodeId:'this-pc',runtimeId:'nemotron-llama-b11669',id:'nemotron-bolt-local',model:'Nemotron 3.5 Bolt 74B A9B',executable:EXE,executableSha256:qualification.executableSha256});
  let runningWork=null;
  let busy=false,closed=false,state='UNKNOWN',reason='NATIVE_STATUS_REQUIRED',native=null,observedAt=null,proof=null,proposal=null,revision=0,signature='',inFlight=null;
  const requireAdmission=admitted=>{if(!admitted())throw new TaskError(401,'Model control admission expired.');};
  function owned(value){const i=value?.owner?.identity;return value?.owner?.state==='resident'&&value.owner.modelId===NEMOTRON_MODEL&&value.owner.ownerVerified===true&&
    Number.isSafeInteger(i?.pid)&&i.pid>0&&typeof i.createdAt==='string'&&Number.isFinite(Date.parse(i.createdAt))&&sha(i.argvHash)&&
    i.executableSha256===profile.executableSha256&&normalized(i.executable)===normalized(EXE)&&normalized(i.cwd)===normalized(EXE.slice(0,EXE.lastIndexOf('/')));}
  function dto(row){return row&&{id:row.id,action:row.binding.command.action,state:row.state,readBackVerified:row.envelope?.receipt.readBackVerified===true,
    reason:row.reason||row.envelope?.receipt.reason||null,updatedAt:row.updatedAt,history:row.events.map(e=>({state:e.state,source:e.source,at:e.at,reason:e.reason||null}))};}
  function snapshot(){
    const fresh=observedAt!==null&&now()>=observedAt&&now()-observedAt<5000;
    const pending=operations.unresolved().length>0,available=!closed&&!busy&&fresh&&!pending&&native?.active===null;
    const owner=owned(native),empty=native?.owner?.state==='empty'&&native.owner.clear===true&&native.owner.identity===null;
    return {schemaVersion:'mesh-local-inference/v1',nodeId:'this-pc',runtimeId:profile.runtimeId,profile,source:qualification.source,
      state:fresh?state:'UNKNOWN',revision,servedAt:new Date(now()).toISOString(),observedAt:fresh?new Date(observedAt).toISOString():null,
      freshness:fresh?'FRESH':'UNAVAILABLE',freshForMs:5000,
      runtime:owner&&fresh?{...native.owner.identity,status:state==='RUNNING'?'VERIFIED':'OWNED'}:{status:'UNKNOWN'},
      health:state==='RUNNING'&&fresh?'HEALTHY':'UNKNOWN',telemetry:{gpuMapping:fresh?proof?.gpuMapping||'UNKNOWN':'UNKNOWN',gpuUuids:fresh?proof?.gpuUuids||[]:[]},
      operation:dto(operations.latest()),controls:{load:Boolean(available&&empty&&native.load),stop:Boolean(available&&owner&&native.unload),
        unload:Boolean(available&&owner&&native.unload),chat:Boolean(available&&state==='RUNNING'&&typeof chatImpl==='function'),
        reason:closed?'MODEL_CONTROLLER_CLOSED':busy?'OPERATION_IN_PROGRESS':!fresh?'NATIVE_STATUS_REQUIRED':pending?'ORIGINAL_OPERATION_PENDING':reason}};
  }
  async function read(){
    native=null;proof=null;observedAt=null;
    const pending=operations.unresolved()[0];
    if(pending){
      try{operations.record(pending.id,await client.receipt(pending.binding));observedAt=now();}
      catch(error){operations.unknown(pending.id,error.code==='NATIVE_BOOT_CHANGED'?'NATIVE_BOOT_CHANGED':'RECEIPT_UNAVAILABLE');state='UNKNOWN';reason='ORIGINAL_OPERATION_UNCONFIRMED';return;}
      if(operations.unresolved().length){state=pending.binding.command.action==='load'?'STARTING':'STOPPING';reason='ORIGINAL_OPERATION_PENDING';return;}
    }
    try{
      const value=await client.status();
      const next=value.bootId+':'+value.expected;if(next!==signature){signature=next;revision++;}
      native=value;observedAt=now();reason=null;
      if(value.active!==null){state='UNKNOWN';reason='NATIVE_OPERATION_IN_PROGRESS';return;}
      if(value.owner?.state==='empty'&&value.owner.clear===true&&value.owner.identity===null){state='STOPPED';return;}
      if(!owned(value)){state='UNCERTAIN';reason='NATIVE_OWNER_UNVERIFIED';return;}
      try{proof=await verifyResident(value);}catch{proof={healthy:false,gpuMapping:'UNKNOWN'};}
      if(proof?.ownerChanged){native=null;state='UNCERTAIN';reason='NATIVE_OWNER_CHANGED';return;}
      state=proof?.healthy===true&&proof.gpuMapping==='VERIFIED'?'RUNNING':'OWNED';
      if(state!=='RUNNING')reason='MODEL_HEALTH_OR_GPU_UNVERIFIED';
    }catch(error){native=null;observedAt=null;state='UNKNOWN';reason=error.code||'NATIVE_STATUS_UNAVAILABLE';}
  }
  async function exclusive(work){if(closed)throw new TaskError(503,'Model controller closed');if(busy)throw new TaskError(409,'Model observation/control in progress');busy=true;const pending=Promise.resolve().then(work);runningWork=pending;
    try{return await pending;}finally{busy=false;if(runningWork===pending)runningWork=null;}}
  return Object.freeze({
    async status(){if(busy)return snapshot();if(inFlight)return inFlight;inFlight=exclusive(read);try{await inFlight;return snapshot();}finally{inFlight=null;}},
    async propose(action,body,session,admitted){
      if(!['load','stop','unload'].includes(action)||!exact(body,[]))throw new TaskError(400,'Fixed Nemotron control only');
      return exclusive(async()=>{await read();requireAdmission(admitted);const s=snapshot();
        const permitted=action==='load'?native?.load&&state==='STOPPED':native?.unload&&owned(native);
        if(!permitted||operations.unresolved().length||native?.active!==null||!s.observedAt)throw new TaskError(409,'Model control unavailable; refresh the original operation');
        proposal={id:randomUUID(),action,profile,revision,expiresAt:now()+30000,session,binding:{modelId:NEMOTRON_MODEL,bootId:native.bootId,moduleSha256:native.moduleSha256,supervisorSha256:native.supervisorSha256,
          command:{id:randomUUID(),action:action==='load'?'load':'unload',expected:native.expected}}};
        const {session:_session,binding:_binding,...publicProposal}=proposal;return {proposal:publicProposal};});
    },
    async approve(body,session,admitted){
      if(!exact(body,['proposalId','confirm'])||body.confirm!==true)throw new TaskError(400,'Explicit model confirmation required');
      return exclusive(async()=>{requireAdmission(admitted);const p=proposal;
        if(!p||p.id!==body.proposalId||p.session!==session||p.expiresAt<=now()||p.revision!==revision)throw new TaskError(409,'Model proposal expired or changed');
        proposal=null;const reserved=operations.reserve(p.binding);if(!reserved.created)throw new TaskError(409,'Original model operation already has a receipt; it was not resent');
        native=null;observedAt=null;proof=null;
        try{operations.record(p.binding.command.id,await client.command(p.binding,{admitted}));}
        catch(error){
          if(error.notSent){try{operations.refuseBeforeDispatch(p.binding.command.id,error.code);}catch{operations.unknown(p.binding.command.id);}}
          else if(error.nativeIdentityVerified&&error.status===409){try{operations.refuseNative(p.binding.command.id,error.envelope);}catch{operations.unknown(p.binding.command.id);}}
          else operations.unknown(p.binding.command.id);
          if(error.code==='ADMISSION_EXPIRED')throw new TaskError(401,'Model control admission expired; nothing sent');
        }
        const row=operations.get(p.binding.command.id);state=['ACCEPTED','RUNNING'].includes(row.state)?(p.action==='load'?'STARTING':'STOPPING'):'UNKNOWN';
        if(['ACCEPTED','RUNNING'].includes(row.state))observedAt=now();reason=row.reason||'REFRESH_MODEL_STATUS';
        return {receipt:dto(row),status:snapshot()};});
    },
    receipt(id){const row=operations.get(id);if(!row)throw new TaskError(404,'Model receipt unavailable');return {receipt:dto(row)};},
    async chat(body,admitted,signal){
      if(!exact(body,['prompt'])||typeof body.prompt!=='string'||!body.prompt.trim()||Buffer.byteLength(body.prompt)>3000)throw new TaskError(400,'Prompt must contain1..3000 UTF-8 bytes');
      return exclusive(async()=>{await read();requireAdmission(admitted);if(state!=='RUNNING'||!chatImpl||operations.unresolved().length)throw new TaskError(409,'Chat requires a verified running model');
        const original=signature;
        try{const response=await chatImpl(body.prompt,{signal,native});if(signal?.aborted)throw Error();await read();requireAdmission(admitted);
          if(signature!==original||state!=='RUNNING'||typeof response!=='string'||Buffer.byteLength(response)>16384)throw Error();return {nodeId:'this-pc',runtimeId:profile.runtimeId,response};}
        catch{native=null;observedAt=null;state='UNKNOWN';reason='CHAT_OUTCOME_UNKNOWN';throw new TaskError(503,'Chat outcome unknown. No automatic retry.');}});
    },
    async close(){closed=true;proposal=null;if(runningWork)await runningWork.catch(()=>{});},
  });
}
