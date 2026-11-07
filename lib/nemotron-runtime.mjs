import {execFile} from 'node:child_process';
import {NEMOTRON_MODEL} from './model-operation-store.mjs';
export function createNemotronRuntime({client,fetchImpl=globalThis.fetch,execFileImpl=execFile}={}){
  async function child(path,{prompt,signal}={}){
    const response=await fetchImpl('http://127.0.0.1:8199'+path,{method:prompt===undefined?'GET':'POST',redirect:'manual',credentials:'omit',cache:'no-store',
      signal:AbortSignal.any([AbortSignal.timeout(prompt===undefined?2500:45000),...(signal?[signal]:[])]),
      ...(prompt===undefined?{}:{headers:{'Content-Type':'application/json'},body:JSON.stringify({model:NEMOTRON_MODEL,messages:[{role:'user',content:prompt}],max_tokens:512,stream:false})})});
    if(response.status!==200||response.redirected||!/^application\/json(?:;|$)/i.test(response.headers.get('content-type')||''))throw Error('Model response unavailable');
    const reader=response.body.getReader();let bytes=0;const chunks=[];
    try{for(;;){const part=await reader.read();if(part.done)break;bytes+=part.value.byteLength;if(bytes>16384)throw Error('Model response exceeded bound');chunks.push(part.value);}return JSON.parse(Buffer.concat(chunks).toString('utf8'));}
    finally{await reader.cancel().catch(()=>{});}
  }
  async function devices(pid){
    const stdout=await new Promise((resolve,reject)=>execFileImpl('C:/Windows/System32/nvidia-smi.exe',['--query-compute-apps=pid,gpu_uuid','--format=csv,noheader,nounits'],
      {windowsHide:true,timeout:2500,maxBuffer:16384,encoding:'utf8'},(error,out)=>error?reject(Error('GPU mapping unavailable')):resolve(out)));
    return [...new Set(String(stdout).split(/\r?\n/).flatMap(line=>{const parts=line.split(',').map(x=>x.trim());return parts[0]===String(pid)&&/^GPU-[a-f0-9-]{36}$/i.test(parts[1]||'')?[parts[1]]:[];}))];
  }
  return {
    async verifyResident(before){
      const [health,models,gpuUuids]=await Promise.all([child('/health'),child('/v1/models'),devices(before.owner.identity.pid)]);
      const after=await client.status();
      const same=after.bootId===before.bootId&&after.expected===before.expected&&after.moduleSha256===before.moduleSha256&&after.supervisorSha256===before.supervisorSha256;
      return {ownerChanged:!same,healthy:same&&health?.status==='ok'&&Array.isArray(models?.data)&&models.data.some(m=>m.id===NEMOTRON_MODEL),
        gpuMapping:same&&gpuUuids.length?'VERIFIED':'UNKNOWN',gpuUuids:same?gpuUuids:[]};
    },
    async chatImpl(prompt,{signal}){
      const value=await child('/v1/chat/completions',{prompt,signal});const content=value?.choices?.[0]?.message?.content;
      if(typeof content!=='string'||!content.trim())throw Error('Model returned no final answer');return content;
    },
  };
}
