// Fixed, read-only supervisor routes. Never call generation or admin endpoints.
const LANES = Object.freeze([
  {id:'qwen3.8-flash-next-iq3-s',label:'Qwen3.8 Flash-Next IQ3_S',port:18090,runtime:'UnbiasedStrata'},
  {id:'qwen3.6-35b-a3b-ud-q6_k_xl',label:'Qwen3.6 35B A3B Q6',port:18091,runtime:'UnbiasedStrata'},
  {id:'qwen3.8-27b',label:'Qwen3.8 27B',port:8098,runtime:'llama.cpp'},
  {id:'nemotron-3.5-bolt-74b-a9b',label:'Nemotron 3.5 Bolt 74B A9B',port:8099,runtime:'llama.cpp'},
]);
const SCHEMA='mesh-supervisor-observation/v1';
const LIMIT=16384;
async function readJson(fetchImpl,url,signal) {
  const response=await fetchImpl(url,{method:'GET',redirect:'manual',credentials:'omit',cache:'no-store',signal});
  if(response.status!==200 || response.redirected || !/^application\/json(?:;|$)/i.test(response.headers.get('content-type')||''))throw Error('unavailable');
  const reader=response.body.getReader();let size=0;const chunks=[];
  try {
    for(;;){const part=await reader.read();if(part.done)break;size+=part.value.byteLength;if(size>LIMIT)throw Error('oversize');chunks.push(part.value);}
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } finally {await reader.cancel().catch(()=>{});}
}
function unavailableReason(detail) {
  if(typeof detail!=='string')return 'preflight_failed';
  if(detail.startsWith('ENGINE_NOT_BUILT'))return 'engine_not_built';
  if(detail.startsWith('missing '))return 'model_files_missing';
  return 'preflight_failed';
}
export function createSupervisorObservation({enabled=false,fetchImpl=globalThis.fetch,now=Date.now,timeoutMs=2000}={}) {
  let inFlight;
  async function observe(lane) {
    const base={id:lane.id,label:lane.label,runtime:lane.runtime};
    try {
      const signal=AbortSignal.timeout(timeoutMs),origin='http://127.0.0.1:'+lane.port;
      const [health,list]=await Promise.all(['/health','/v1/models'].map(path=>readJson(fetchImpl,origin+path,signal)));
      const entry=Array.isArray(list?.data)&&list.data.length===1 ? list.data[0] : null;
      if(health?.port!==lane.port || health.model!==lane.id || entry?.id!==lane.id ||
         entry.owned_by!=='dsh-local-supervisor' || typeof health.loaded!=='boolean' ||
         typeof health.loading!=='boolean' || typeof health.servable!=='boolean' ||
         typeof entry.loaded!=='boolean' || entry.loaded!==health.loaded)throw Error('identity');
      // The supervisor sets its target before startup completes; loading is global.
      // Neither this response nor a process name proves child custody or GPU mapping.
      const state=health.loading ? 'loading_unconfirmed' : health.loaded ? 'reported_loaded' : health.servable ? 'ready' : 'unavailable';
      return {...base,state,available:health.servable,loaded:health.loading?null:health.loaded,
        reason:health.servable?null:unavailableReason(health.detail)};
    } catch {return {...base,state:'unknown',available:null,loaded:null,reason:'observation_unavailable'};}
  }
  return async function read() {
    if(!enabled)return {schemaVersion:SCHEMA,state:'not_configured',source:'none',models:[]};
    if(inFlight)return inFlight;
    inFlight=(async()=>{
      const models=await Promise.all(LANES.map(observe)),at=now();
      const known=models.filter(row=>row.state!=='unknown').length;
      return {schemaVersion:SCHEMA,state:known===LANES.length?'fresh':known?'partial':'unavailable',
        source:'local_supervisor',observedAt:new Date(at).toISOString(),expiresAt:at+5000,
        custody:'unverified',gpuMapping:'unverified',controls:false,models};
    })();
    try{return await inFlight;}finally{inFlight=undefined;}
  };
}
