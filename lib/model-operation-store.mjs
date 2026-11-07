import {createHash} from 'node:crypto';
export const NEMOTRON_MODEL='nemotron-3.5-bolt-74b-a9b';
const uuid=value=>typeof value==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value);
const sha=value=>typeof value==='string'&&/^[0-9a-f]{64}$/.test(value);
const exact=(value,keys)=>value&&Object.getPrototypeOf(value)===Object.prototype&&Object.keys(value).length===keys.length&&keys.every(k=>Object.hasOwn(value,k));
const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const terminal=state=>['COMPLETED','REFUSED','UNKNOWN'].includes(state);
const finalNative=row=>terminal(row?.envelope?.receipt?.state)||row?.events.at(-1)?.source==='native_fence'||row?.state==='REFUSED'&&['app_no_dispatch','native_refusal'].includes(row.events.at(-1)?.source);
export function nativeCommandFingerprint(command){return hash({action:command.action,expected:command.expected,id:command.id});}
function refuse(message){throw Object.assign(new Error(message),{status:409});}
export function createModelOperationStore(db,{now=Date.now}={}){
  db.exec(`CREATE TABLE IF NOT EXISTS model_operations (
    id TEXT PRIMARY KEY, binding TEXT NOT NULL, bindingHash TEXT NOT NULL,
    state TEXT NOT NULL, envelope TEXT, reason TEXT, events TEXT NOT NULL, createdAt TEXT NOT NULL, updatedAt TEXT NOT NULL
  )`);
  const decode=row=>row&&({...row,binding:JSON.parse(row.binding),envelope:row.envelope?JSON.parse(row.envelope):null,events:JSON.parse(row.events)});
  const get=id=>decode(db.prepare('SELECT * FROM model_operations WHERE id=?').get(id));
  const unresolved=()=>db.prepare('SELECT * FROM model_operations ORDER BY createdAt,id').all().map(decode).filter(row=>!finalNative(row));
  function transaction(work){db.exec('BEGIN IMMEDIATE');try{const value=work();db.exec('COMMIT');return value;}catch(error){db.exec('ROLLBACK');throw error;}}
  function timestamp(){const at=now();if(!Number.isSafeInteger(at))throw Error('Invalid model operation clock');return new Date(at).toISOString();}
  return Object.freeze({
    get,unresolved,latest:()=>decode(db.prepare('SELECT * FROM model_operations ORDER BY rowid DESC LIMIT 1').get()),
    reserve(binding){
      if(!exact(binding,['modelId','bootId','moduleSha256','supervisorSha256','command'])||binding.modelId!==NEMOTRON_MODEL||!uuid(binding.bootId)||!sha(binding.moduleSha256)||!sha(binding.supervisorSha256)||
        !exact(binding.command,['id','action','expected'])||!uuid(binding.command.id)||!['load','unload'].includes(binding.command.action)||!sha(binding.command.expected))throw Object.assign(new Error('Invalid fixed model operation binding'),{status:400});
      const canonical={modelId:binding.modelId,bootId:binding.bootId,moduleSha256:binding.moduleSha256,supervisorSha256:binding.supervisorSha256,
        command:{id:binding.command.id,action:binding.command.action,expected:binding.command.expected}};
      return transaction(()=>{
        const existing=get(canonical.command.id),bindingHash=hash(canonical);
        if(existing){if(existing.bindingHash!==bindingHash)refuse('Model operation ID has a different binding');return {created:false,operation:existing};}
        if(unresolved().length)refuse('A prior model operation still needs its original receipt; no new command was reserved');
        const at=timestamp();
        db.prepare('INSERT INTO model_operations(id,binding,bindingHash,state,events,createdAt,updatedAt) VALUES(?,?,?,?,?,?,?)').run(canonical.command.id,JSON.stringify(canonical),bindingHash,'PREPARED',JSON.stringify([{state:'PREPARED',source:'app_reservation',at}]),at,at);
        return {created:true,operation:get(canonical.command.id)};
      });
    },
    unknown(id,reason='DELIVERY_UNKNOWN'){
      if(!['DELIVERY_UNKNOWN','NATIVE_BOOT_CHANGED','RECEIPT_UNAVAILABLE','APP_RESTART'].includes(reason))throw Error('Invalid unknown reason');
      return transaction(()=>{const row=get(id);if(!row)refuse('Unknown model operation');if(!finalNative(row)&&(row.state!=='UNKNOWN'||row.reason!==reason)){const at=timestamp();db.prepare("UPDATE model_operations SET state='UNKNOWN',reason=?,events=?,updatedAt=? WHERE id=?").run(reason,JSON.stringify([...row.events,{state:'UNKNOWN',source:'app_observation',reason,at}]),at,id);}return get(id);});
    },
    refuseBeforeDispatch(id,reason){
      if(!['OWNER_CHANGED','ACTION_UNAVAILABLE','BRIDGE_UNAVAILABLE','BRIDGE_IDENTITY_MISMATCH','BRIDGE_REPLY_INVALID','BRIDGE_REDIRECT_REFUSED','NATIVE_BOOT_CHANGED','OWNER_BUSY','ADMISSION_EXPIRED'].includes(reason))throw Error('Invalid no-dispatch reason');
      return transaction(()=>{const row=get(id);if(!row||row.state!=='PREPARED'||row.envelope)refuse('Only a never-dispatched reservation may be refused locally');
        const at=timestamp();db.prepare("UPDATE model_operations SET state='REFUSED',reason=?,events=?,updatedAt=? WHERE id=?").run(reason,JSON.stringify([...row.events,{state:'REFUSED',source:'app_no_dispatch',reason,at}]),at,id);return get(id);});
    },
    refuseNative(id,envelope){
      return transaction(()=>{const row=get(id),b=row?.binding;
        if(!b||row.state!=='PREPARED'||row.envelope||!exact(envelope,['schemaVersion','moduleSha256','supervisorSha256','bootId','modelId','error'])||envelope.schemaVersion!=='mesh-supervisor-control/v1'||envelope.moduleSha256!==b.moduleSha256||envelope.supervisorSha256!==b.supervisorSha256||envelope.bootId!==b.bootId||envelope.modelId!==b.modelId||!['OWNER_CHANGED','OWNER_BUSY','OPERATION_IN_PROGRESS','ACTION_UNAVAILABLE','INVALID_COMMAND','COMMAND_ID_CONFLICT'].includes(envelope.error))refuse('Unbound native refusal');
        const at=timestamp();db.prepare("UPDATE model_operations SET state='REFUSED',reason=?,events=?,updatedAt=? WHERE id=?").run(envelope.error,JSON.stringify([...row.events,{state:'REFUSED',source:'native_refusal',reason:envelope.error,proof:envelope,at}]),at,id);return get(id);});
    },
    fence(id,envelope,currentBootId){
      return transaction(()=>{const row=get(id),b=row?.binding,r=envelope?.recovery;
        if(!b||!uuid(currentBootId)||!exact(envelope,['schemaVersion','moduleSha256','supervisorSha256','bootId','modelId','recovery'])||envelope.schemaVersion!=='mesh-supervisor-control/v1'||
          envelope.moduleSha256!==b.moduleSha256||envelope.supervisorSha256!==b.supervisorSha256||envelope.modelId!==b.modelId||envelope.bootId!==currentBootId||
          !exact(r,['id','fingerprint','originalBootId','checkedExpected','state','outcome','active'])||r.id!==id||r.fingerprint!==nativeCommandFingerprint(b.command)||
          r.originalBootId!==b.bootId||!sha(r.checkedExpected)||r.state!=='FENCED'||r.outcome!=='UNKNOWN'||r.active!==null)refuse('Unbound native recovery proof');
        if(finalNative(row)){if(row.events.at(-1)?.source==='native_fence'&&row.events.at(-1).proofHash===hash(envelope))return row;refuse('Final model outcome cannot be replaced with recovery');}
        const at=timestamp();db.prepare("UPDATE model_operations SET state='UNKNOWN',reason='OUTCOME_FENCED',events=?,updatedAt=? WHERE id=?").run(
          JSON.stringify([...row.events,{state:'UNKNOWN',source:'native_fence',reason:'OUTCOME_FENCED',proof:envelope,proofHash:hash(envelope),at}]),at,id);
        return get(id);
      });
    },
    record(id,envelope){
      return transaction(()=>{
        const row=get(id);if(!row)refuse('Unknown model operation');
        const b=row.binding,r=envelope?.receipt;
        if(!exact(envelope,['schemaVersion','moduleSha256','supervisorSha256','bootId','modelId','receipt'])||envelope.modelId!==b.modelId||envelope?.schemaVersion!=='mesh-supervisor-control/v1'||envelope.bootId!==b.bootId||envelope.moduleSha256!==b.moduleSha256||envelope.supervisorSha256!==b.supervisorSha256||
          r?.id!==id||r.action!==b.command.action||r.fingerprint!==nativeCommandFingerprint(b.command)||
          !['ACCEPTED','RUNNING','COMPLETED','REFUSED','UNKNOWN'].includes(r.state)||typeof r.readBackVerified!=='boolean'||typeof r.ownerCallStarted!=='boolean'||
          (r.state==='COMPLETED'? !r.readBackVerified||!r.ownerCallStarted:r.readBackVerified)||
          (['ACCEPTED','REFUSED'].includes(r.state)&&r.ownerCallStarted)|| (r.state==='RUNNING'&&!r.ownerCallStarted))refuse('Native receipt does not match the original model operation');
        if(!r||Object.keys(r).some(k=>!['id','action','fingerprint','state','readBackVerified','ownerCallStarted','reason'].includes(k))||(r.reason!==undefined&&(typeof r.reason!=='string'||!/^[_A-Z]{1,64}$/.test(r.reason))))refuse('Unexpected native receipt fields');
        const receipt={id:r.id,action:r.action,fingerprint:r.fingerprint,state:r.state,readBackVerified:r.readBackVerified,ownerCallStarted:r.ownerCallStarted,...(r.reason!==undefined?{reason:r.reason}:{})};
        const normalized={schemaVersion:envelope.schemaVersion,moduleSha256:envelope.moduleSha256,supervisorSha256:envelope.supervisorSha256,bootId:envelope.bootId,modelId:envelope.modelId,receipt};
        const frozen=JSON.stringify(normalized);
        if(finalNative(row)){if(row.envelope!==null&&JSON.stringify(row.envelope)!==frozen)refuse('Final model receipt cannot be rewritten');return row;}
        if(row.envelope?.receipt.state==='RUNNING'&&r.state==='ACCEPTED')refuse('Native receipt moved backwards');
        if(row.state===r.state&&row.reason===null&&row.envelope&&JSON.stringify(row.envelope)===frozen)return row;
        const at=timestamp();
        db.prepare('UPDATE model_operations SET state=?,envelope=?,reason=NULL,events=?,updatedAt=? WHERE id=?').run(r.state,frozen,JSON.stringify([...row.events,{state:r.state,source:'native_receipt',envelopeHash:hash(normalized),at}]),at,id);
        return get(id);
      });
    },
  });
}
