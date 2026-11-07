import {NEMOTRON_MODEL} from './model-operation-store.mjs';
import {randomUUID} from 'node:crypto';
const uuid=value=>typeof value==='string'&&/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value);
const sha=value=>typeof value==='string'&&/^[0-9a-f]{64}$/.test(value);
export class NemotronProtocolError extends Error{
  constructor(code){super(code);this.code=code;this.status=503;}
}
export function createNemotronClient({moduleSha256,supervisorSha256,fetchImpl=globalThis.fetch,timeoutMs=3000}={}){
  if(!sha(moduleSha256)||!sha(supervisorSha256))throw Error('Explicit qualified native source hashes are required');
  const fail=code=>{throw new NemotronProtocolError(code);};
  function metadata(value,binding){
    if(value?.schemaVersion!=='mesh-supervisor-control/v1'||value.moduleSha256!==moduleSha256||value.supervisorSha256!==supervisorSha256||value.modelId!==NEMOTRON_MODEL||!uuid(value.bootId))fail('BRIDGE_IDENTITY_MISMATCH');
    if(binding&&value.bootId!==binding.bootId)fail('NATIVE_BOOT_CHANGED');
  }
  async function request(path,{command,binding,signal,chat=false}={}){
    let response;
    try{response=await fetchImpl('http://127.0.0.1:8099'+path,{method:command?'POST':'GET',redirect:'manual',credentials:'omit',cache:'no-store',signal:AbortSignal.any([AbortSignal.timeout(chat?50000:timeoutMs),...(signal?[signal]:[])]),
      ...(command?{headers:{'Content-Type':'application/json'},body:JSON.stringify(command)}:{})});}
    catch{fail('BRIDGE_UNAVAILABLE');}
    if(response.redirected||response.status>=300&&response.status<400)fail('BRIDGE_REDIRECT_REFUSED');
    if(!/^application\/json(?:;|$)/i.test(response.headers.get('content-type')||''))fail('BRIDGE_REPLY_INVALID');
    let value;
    try{
      const reader=response.body.getReader(),chunks=[];let bytes=0;
      try{for(;;){const part=await reader.read();if(part.done)break;bytes+=part.value.byteLength;if(bytes>(chat?32768:16384))throw Error();chunks.push(part.value);}value=JSON.parse(Buffer.concat(chunks).toString('utf8'));}
      finally{await reader.cancel().catch(()=>{});}
    }catch{fail('BRIDGE_REPLY_INVALID');}
    metadata(value,binding);
    if(response.status<200||response.status>=300){
      const code=typeof value.error==='string'&&/^[A-Z_]{1,64}$/.test(value.error)?value.error:'BRIDGE_REQUEST_REFUSED';
      const error=new NemotronProtocolError(code);error.status=response.status;error.nativeIdentityVerified=true;error.envelope={schemaVersion:value.schemaVersion,moduleSha256:value.moduleSha256,supervisorSha256:value.supervisorSha256,bootId:value.bootId,modelId:value.modelId,error:code};throw error;
    }
    return value;
  }
  function bindingValid(binding){
    if(binding?.modelId!==NEMOTRON_MODEL||binding.moduleSha256!==moduleSha256||binding.supervisorSha256!==supervisorSha256||!uuid(binding.bootId)||
      !uuid(binding.command?.id)||!['load','unload'].includes(binding.command.action)||!sha(binding.command.expected)||Object.keys(binding.command).sort().join(',')!=='action,expected,id')fail('COMMAND_BINDING_INVALID');
  }
  return Object.freeze({
    async chat(prompt,native,{signal,admitted=()=>true}={}){
      metadata(native);if(!sha(native.expected)||typeof prompt!=='string'||!prompt.trim()||Buffer.byteLength(prompt)>3000)fail('CHAT_BINDING_INVALID');
      const current=await this.status();metadata(current,native);
      if(current.expected!==native.expected||current.active!==null||!current.unload)fail('OWNER_CHANGED');
      if(!admitted()||signal?.aborted)fail('ADMISSION_EXPIRED');
      const id=randomUUID();const value=await request('/mesh/v1/chat',{command:{id,expected:native.expected,prompt},binding:native,signal,chat:true});
      const reply=value.chat;
      if(!reply||Object.keys(reply).sort().join(',')!=='expected,id,response'||reply.id!==id||!sha(reply.expected)||reply.expected===native.expected||typeof reply.response!=='string'||!reply.response.trim()||Buffer.byteLength(reply.response)>16384)fail('BRIDGE_REPLY_INVALID');
      return {response:reply.response,expected:reply.expected};
    },
    async status(){
      const value=await request('/mesh/v1/status');
      if(!sha(value.expected)||!['empty','resident','uncertain'].includes(value.owner?.state)||typeof value.load!=='boolean'||typeof value.unload!=='boolean'||
        !(value.active===null||uuid(value.active)))fail('BRIDGE_REPLY_INVALID');
      return value;
    },
    async command(binding,{admitted=()=>true}={}){
      bindingValid(binding);
      try{const current=await this.status();metadata(current,binding);
        if(current.expected!==binding.command.expected)fail('OWNER_CHANGED');
        if(current.active!==null||current[binding.command.action]!==true)fail('ACTION_UNAVAILABLE');
        if(!admitted())fail('ADMISSION_EXPIRED');
      }catch(error){error.notSent=true;throw error;}
      // Exactly one POST. A network timeout is not authority to send another.
      return request('/mesh/v1/commands',{command:binding.command,binding});
    },
    async receipt(binding){bindingValid(binding);return request('/mesh/v1/receipts/'+binding.command.id,{binding});},
    async recover(binding,{bootId,expected,admitted=()=>true}={}){
      bindingValid(binding);if(!uuid(bootId)||!sha(expected))fail('COMMAND_BINDING_INVALID');
      const current=await this.status();metadata(current,{bootId});
      if(current.expected!==expected)fail('OWNER_CHANGED');
      if(current.active!==null||!(current.load||current.unload))fail('ACTION_UNAVAILABLE');
      if(!admitted())fail('ADMISSION_EXPIRED');
      // Fencing is an explicit confirmation, never an original command retry.
      return request('/mesh/v1/recover',{binding:{bootId},command:{command:binding.command,originalBootId:binding.bootId,currentExpected:expected}});
    },
  });
}
