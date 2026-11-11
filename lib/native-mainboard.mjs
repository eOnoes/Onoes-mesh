import {createHash} from 'node:crypto';
import {readFileSync,lstatSync,realpathSync} from 'node:fs';
import {isAbsolute,relative,sep} from 'node:path';
import {nativeGatewayWorkerOptions} from './native-gateway-transport.mjs';

const keys=(value,expected)=>value&&typeof value==='object'&&!Array.isArray(value)
  &&Object.keys(value).sort().join(',')===expected.slice().sort().join(',');
const inside=(directory,file)=>{
  const path=relative(directory,file);
  return !path||!isAbsolute(path)&&path!=='..'&&!path.startsWith('..'+sep);
};
const fail=reason=>{throw Error(reason);};

// Trusted launcher configuration only. No browser-supplied profile or credentials.
export function mainboardNativeConnection({root,env=process.env,makeOptions=nativeGatewayWorkerOptions}) {
  const file=env.MESH_NATIVE_WORKER_RECORD,approval=env.MESH_NATIVE_WORKER_RECORD_SHA256;
  if(!file&&!approval)return {state:'disabled',options:undefined};
  // A standalone/Relay-disabled app has no real handoff transport to fall back to.
  if(env.MESH_STANDALONE==='1'||env.MESH_RELAY!=='1'||env.MESH_RELAY_MODE!=='http')
    return {state:'held',reason:'live_relay_required',options:undefined};
  const held=reason=>({state:'held',reason,options:{
    profile:{profileRef:'native-enrollment-held',identityRef:'native-enrollment-held',
      provider:'openai-codex',model:'gpt-6-luna',workspace:root},
    authorized:()=>false,rpc:async()=>{throw Error('Native worker enrollment is held');},
  }});
  try {
    if(typeof file!=='string'||!isAbsolute(file)||typeof approval!=='string'||!(/^[a-f0-9]{64}$/).test(approval))fail('explicit_record_approval_required');
    const read=()=>{
      if(env.MESH_NATIVE_WORKER_RECORD!==file||env.MESH_NATIVE_WORKER_RECORD_SHA256!==approval
          ||env.MESH_SIMPLE_FLOW==='1'||env.MESH_STANDALONE==='1'||env.MESH_RELAY!=='1'||env.MESH_RELAY_MODE!=='http')fail('enrollment_revoked');
      const stat=lstatSync(file);
      if(!stat.isFile()||stat.isSymbolicLink()||stat.size>16384)fail('invalid_record_file');
      const bytes=readFileSync(file);
      if(createHash('sha256').update(bytes).digest('hex')!==approval)fail('record_approval_mismatch');
      const record=JSON.parse(bytes.toString('utf8'));
      if(!keys(record,['schema','profile','runtime'])||record.schema!=='mesh-native-worker-enrollment/v1'
          ||!keys(record.profile,['profileRef','identityRef','provider','model','workspace'])
          ||record.profile.provider!=='openai-codex'||record.profile.model!=='gpt-6-luna'
          ||!['profileRef','identityRef'].every(k=>typeof record.profile[k]==='string'&&/^[A-Za-z0-9_-]{1,100}$/.test(record.profile[k]))
          ||typeof record.profile.workspace!=='string'||!isAbsolute(record.profile.workspace)
          ||!keys(record.runtime,['home','nativeRoot','pythonExecutable'])
          ||!Object.values(record.runtime).every(v=>typeof v==='string'&&isAbsolute(v)))fail('invalid_closed_profile');
      const workspace=realpathSync(record.profile.workspace);
      if(!lstatSync(workspace).isDirectory()||inside(workspace,realpathSync(file)))fail('record_must_be_outside_worker_workspace');
      if(Object.values(record.runtime).some(path=>inside(workspace,realpathSync(path))))fail('runtime_must_be_outside_worker_workspace');
      return record;
    };
    const record=read();
    const authorized=()=>{try{read();return true;}catch{return false;}};
    const options=makeOptions({...record.runtime,profile:record.profile,authorized});
    return {state:'configured',options};
  } catch(error) {
    return held(/^[a-z_]+$/.test(error.message)?error.message:'enrollment_unavailable');
  }
}
