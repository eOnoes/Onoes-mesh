import { access } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import { Worker } from 'node:worker_threads';
export const SERVICE_MAP = Object.freeze([
  Object.freeze({ id:'relay', label:'Relay', adapter:'held' }),
  Object.freeze({ id:'inference', label:'Inference', adapter:'fixed_local_module' }),
  Object.freeze({ id:'agent', label:'Agent', adapter:'absent' }),
  Object.freeze({ id:'mind', label:'Mind', adapter:'absent' })
]);
const VERSION = 'mesh-inference-observation/v1';
const STATUSES = new Set(['not_configured','disabled','fresh','partial','stale','unavailable','unauthorized','unsupported','invalid']);
const plain = v => v !== null && typeof v === 'object' && !Array.isArray(v) && Object.getPrototypeOf(v) === Object.prototype;
const text = (v,max=128) => typeof v === 'string' && v.length > 0 && v.length <= max && !/[\u0000-\u001f\u007f]/u.test(v);
const iso = v => text(v,24) && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/.test(v) && Number.isFinite(Date.parse(v)) && new Date(v).toISOString() === v;
const exact = (v,keys) => plain(v) && Object.keys(v).length === keys.length && keys.every(k=>Object.hasOwn(v,k));
const id = v => typeof v === 'string' && /^[a-z][a-z0-9_-]{0,47}$/.test(v);
const label = v => typeof v === 'string' && /^[A-Za-z0-9][A-Za-z0-9 ()_-]{0,63}$/.test(v);
const integer = (v,min,max) => Number.isSafeInteger(v) && v >= min && v <= max;
const number = (v,max) => typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= max;
const nullable = (v,check) => v === null || check(v);
export const INFERENCE_LIMITS = Object.freeze({nodes:32,modelsPerNode:128,errors:32,elements:73728,outputBytes:2097152,deadlineMs:5000,containmentGraceMs:250});
const NODE_STATES = new Set(['disabled','fresh','stale','unknown','unavailable','unauthorized','unsupported']);
const GLOBAL_ERRORS = new Set(['clock_invalid','config_invalid','duplicate_node_id','path_rejected','destination_rejected']);
const NODE_ERRORS = Object.freeze({
  observation_stale:'stale', timestamp_missing:'unknown', timestamp_invalid:'unknown',
  response_shape:'unknown', malformed_json:'unknown', node_unreachable:'unavailable',
  redirect_rejected:'unavailable', upstream_unavailable:'unavailable', response_too_large:'unavailable',
  deadline_exceeded:'unavailable', unauthorized:'unauthorized', route_unsupported:'unsupported', source_gate_held:'unsupported'
});
export const emptyInference = (status='not_configured',nowIso=new Date().toISOString()) => ({schemaVersion:VERSION,observedAt:nowIso,status,nodes:[],errors:[]});
const invalid = () => { throw new Error('invalid'); };
export function normalizeInference(value,nowIso=new Date().toISOString()) {
  try {
    if (!iso(nowIso)) invalid();
    if (!exact(value,['schemaVersion','observedAt','status','nodes','errors']) || value.schemaVersion !== VERSION || !iso(value.observedAt) || Date.parse(value.observedAt) > Date.parse(nowIso) || !STATUSES.has(value.status) || !Array.isArray(value.nodes) || value.nodes.length > INFERENCE_LIMITS.nodes || !Array.isArray(value.errors) || value.errors.length > INFERENCE_LIMITS.errors) invalid();
    let elements=8; const ids=new Set();
    const nodes=value.nodes.map(n=> {
      if (!exact(n,['id','label','status','observedAt','source','capabilities','models','hardware']) || !id(n.id) || ids.has(n.id) || !label(n.label) || !NODE_STATES.has(n.status) || !nullable(n.observedAt,iso) || (n.observedAt !== null && Date.parse(n.observedAt) > Date.parse(value.observedAt)) || !['disabled','disposable_fixture','source_bound_live'].includes(n.source) || !exact(n.capabilities,['observation','load','unload']) || typeof n.capabilities.observation !== 'boolean' || n.capabilities.load !== false || n.capabilities.unload !== false || !Array.isArray(n.models) || n.models.length > INFERENCE_LIMITS.modelsPerNode || !exact(n.hardware,['expected','observed'])) invalid();
      ids.add(n.id); elements+=24;
      const expected=n.hardware.expected, observed=n.hardware.observed;
      if (!exact(expected,['gpuCount','vramTotalMiB']) || !nullable(expected.gpuCount,v=>integer(v,0,64)) || !nullable(expected.vramTotalMiB,v=>number(v,1e12))) invalid();
      if (observed !== null && (!exact(observed,['gpuCount','vramTotalMiB','vramUsedMiB','utilizationPercent']) || !nullable(observed.gpuCount,v=>integer(v,0,64)) || !nullable(observed.vramTotalMiB,v=>number(v,1e12)) || !nullable(observed.vramUsedMiB,v=>number(v,1e12)) || !nullable(observed.utilizationPercent,v=>number(v,100)) || (observed.vramTotalMiB !== null && observed.vramUsedMiB !== null && observed.vramUsedMiB > observed.vramTotalMiB) || (observed.gpuCount === 0 && [observed.vramTotalMiB,observed.vramUsedMiB,observed.utilizationPercent].some(v=>v !== null && v > 0)))) invalid();
      const seenModels=new Set();
      const models=n.models.map(m=> {
        elements+=16;
        if (!exact(m,['id','label','runtime','resident','contextWindow','sizeGB','vramGB']) || !id(m.id) || seenModels.has(m.id) || !label(m.label) || ![null,'lmstudio','ollama','mock'].includes(m.runtime) || !nullable(m.resident,v=>typeof v === 'boolean') || !nullable(m.contextWindow,v=>integer(v,1,16777216)) || !nullable(m.sizeGB,v=>number(v,100000)) || !nullable(m.vramGB,v=>number(v,100000)) || (m.runtime === null && (m.resident !== null || m.contextWindow !== null)) || (m.resident === false && m.vramGB !== null)) invalid();
        if (n.status !== 'fresh' && [m.resident,m.contextWindow,m.sizeGB,m.vramGB].some(v=>v !== null)) invalid();
        seenModels.add(m.id);
        return {id:m.id,label:m.label,runtime:m.runtime,resident:m.resident,contextWindow:m.contextWindow,sizeGB:m.sizeGB,vramGB:m.vramGB};
      });
      if (n.status === 'fresh' || n.status === 'stale') {
        if (!n.capabilities.observation || n.observedAt === null || n.source !== 'disposable_fixture') invalid();
      } else if (n.observedAt !== null) invalid();
      if (n.status !== 'fresh' && observed !== null) invalid();
      if (!n.capabilities.observation && (models.length || observed !== null)) invalid();
      if (n.status === 'disabled' ? n.source !== 'disabled' || n.capabilities.observation : n.source === 'disabled') invalid();
      if (n.source === 'source_bound_live' && (n.status !== 'unsupported' || n.capabilities.observation)) invalid();
      if (!['fresh','stale','unknown'].includes(n.status) && n.capabilities.observation) invalid();
      return {id:n.id,label:n.label,status:n.status,observedAt:n.observedAt,source:n.source,capabilities:{observation:n.capabilities.observation,load:false,unload:false},models,hardware:{expected:{gpuCount:expected.gpuCount,vramTotalMiB:expected.vramTotalMiB},observed:observed === null ? null : {gpuCount:observed.gpuCount,vramTotalMiB:observed.vramTotalMiB,vramUsedMiB:observed.vramUsedMiB,utilizationPercent:observed.utilizationPercent}}};
    });
    const errorNodes=new Set();
    const errors=value.errors.map(e=> {
      elements+=3;
      if (!exact(e,['code','nodeId']) || !(e.nodeId === null ? GLOBAL_ERRORS.has(e.code) && value.status === 'invalid' && nodes.length === 0 : id(e.nodeId) && ids.has(e.nodeId) && Object.hasOwn(NODE_ERRORS,e.code)) || errorNodes.has(e.nodeId)) invalid();
      errorNodes.add(e.nodeId);
      if (e.nodeId !== null) {
        const n=nodes.find(n=>n.id === e.nodeId);
        if (NODE_ERRORS[e.code] !== n.status || (['timestamp_missing','timestamp_invalid'].includes(e.code) ? !n.capabilities.observation : ['response_shape','malformed_json'].includes(e.code) && n.capabilities.observation) || (e.code === 'source_gate_held') !== (n.source === 'source_bound_live')) invalid();
      }
      return {code:e.code,nodeId:e.nodeId};
    });
    for (const n of nodes) if (['fresh','disabled'].includes(n.status) ? errorNodes.has(n.id) : !errorNodes.has(n.id)) invalid();
    if (nodes.length) {
      const states=new Set(nodes.map(n=>n.status));
      const aggregate=states.size === 1 && nodes[0].status !== 'unknown' ? nodes[0].status : 'partial';
      if (value.status !== aggregate) invalid();
    } else if (!['not_configured','disabled','invalid','unavailable','unsupported'].includes(value.status) || (value.status !== 'invalid' && errors.length)) invalid();
    if (elements > INFERENCE_LIMITS.elements) invalid();
    const result={schemaVersion:VERSION,observedAt:value.observedAt,status:value.status,nodes,errors};
    if (Buffer.byteLength(JSON.stringify(result),'utf8') > INFERENCE_LIMITS.outputBytes) invalid();
    return result;
  } catch { return emptyInference('invalid',iso(nowIso) ? nowIso : new Date().toISOString()); }
}
// Run even module import in a disposable thread. On success, failure or deadline,
// await termination: no module timers, sockets or late output survive the return.
const WORKER_SOURCE = String.raw`
const { parentPort, workerData } = require('node:worker_threads');
const pending = new Map(); let nextId=0;
parentPort.on('message',m=> { const p=pending.get(m.id); if(p) { pending.delete(m.id); m.error ? p.reject(Error('test transport unavailable')) : p.resolve({status:m.status,redirected:m.redirected,headers:{get:k=>m.headers[k.toLowerCase()]??null},body:(async function*(){yield new Uint8Array(m.body);})(),cancel(){}}); } });
const injectedFetch = (url,options) => new Promise((resolve,reject)=> {
 const id=++nextId; pending.set(id,{resolve,reject});
 options.signal.addEventListener('abort',()=>parentPort.postMessage({type:'abort',id}),{once:true});
 parentPort.postMessage({type:'fetch',id,url,options:{...options,signal:undefined}});
});
(async()=> {
 try {
  const {normalizeInference,emptyInference}=await import(workerData.wrapperUrl);
  const mod=await import(workerData.moduleUrl);
  const args={config:workerData.config,nowIso:workerData.nowIso};
  if(workerData.inject) args.fetchImpl=injectedFetch;
  const result=typeof mod.readInferenceSnapshot === 'function' ? normalizeInference(await mod.readInferenceSnapshot(args),workerData.nowIso) : emptyInference('unsupported',workerData.nowIso);
  parentPort.postMessage({type:'result',result});
 } catch {parentPort.postMessage({type:'failed'});}
})();
`;
export async function readFixedInference({modulePath,confine,config,fetchImpl,nowIso=new Date().toISOString()}) {
  try { await access(modulePath); }
  catch(e) { return emptyInference(e.code === 'ENOENT' ? 'not_configured' : 'unavailable',nowIso); }
  let worker,timer; const transports=new Map(), operations=new Set();
  const dispose = async entry => {
    entry.controller.abort();
    try { entry.response?.body?.destroy?.(); await entry.reader?.cancel(); await entry.response?.cancel?.(); } catch { /* code-only failure */ }
  };
  try {
    await confine(modulePath);
    if (fetchImpl !== undefined && typeof fetchImpl !== 'function') return emptyInference('invalid',nowIso);
    // The candidate runs all nodes concurrently under one 20..5000 ms budget.
    // A fixed 250 ms allowance covers import/normalization; it never cuts off 5000 ms.
    const requestMs=integer(config?.deadlineMs,20,5000) ? config.deadlineMs : 1000;
    worker=new Worker(WORKER_SOURCE,{eval:true,stdout:true,stderr:true,resourceLimits:{maxOldGenerationSizeMb:256,stackSizeMb:4},workerData:{moduleUrl:pathToFileURL(modulePath).href,wrapperUrl:import.meta.url,config,nowIso,inject:fetchImpl !== undefined}});
    // Module diagnostics are never forwarded into app output.
    worker.stdout.resume();worker.stderr.resume();
    const result=await new Promise(resolve=> {
      timer=setTimeout(()=>resolve(emptyInference('unavailable',nowIso)),requestMs+INFERENCE_LIMITS.containmentGraceMs);
      worker.once('error',()=>resolve(emptyInference('unavailable',nowIso)));
      worker.once('exit',()=>resolve(emptyInference('unavailable',nowIso)));
      worker.on('message',m=> {
        if (m.type === 'result') {resolve(normalizeInference(m.result,nowIso));return;}
        if (m.type === 'failed') {resolve(emptyInference('unavailable',nowIso));return;}
        if (m.type === 'abort') { const entry=transports.get(m.id); if(entry) void dispose(entry); return; }
        if (m.type !== 'fetch' || !fetchImpl) return;
        // Explicit test injection only. The injector must honor AbortSignal and
        // settle cancellation. It is never installed in the production app.
        const entry={controller:new AbortController()}; transports.set(m.id,entry);
        const operation=(async()=> {
          try {
            entry.response=await fetchImpl(m.url,{...m.options,signal:entry.controller.signal});
            if(entry.controller.signal.aborted) throw Error('cancelled');
            const chunks=[];let size=0;const cap=m.options.maxResponseBytes;
            if(!integer(cap,256,1048576)) throw Error('cap');
            const take=chunk=> {size+=chunk.byteLength;if(size>cap) throw Error('cap');chunks.push(Buffer.from(chunk));};
            if(entry.response.body?.getReader) {
              entry.reader=entry.response.body.getReader();
              for(;;){const r=await entry.reader.read();if(r.done)break;take(r.value);}
            } else for await(const chunk of entry.response.body) take(chunk);
            const headers=Object.fromEntries(['content-type','content-length'].map(k=>[k,entry.response.headers.get(k)]));
            worker.postMessage({id:m.id,status:entry.response.status,redirected:entry.response.redirected,headers,body:Buffer.concat(chunks)});
          } catch {try {worker.postMessage({id:m.id,error:true});} catch { /* terminated */ }}
          finally {await dispose(entry);transports.delete(m.id);}
        })();
        operations.add(operation);void operation.finally(()=>operations.delete(operation));
      });
    });
    return result;
  } catch { return emptyInference('unavailable',nowIso); }
  finally {
    clearTimeout(timer);
    await Promise.all([...transports.values()].map(dispose));
    if(worker) await worker.terminate();
    await Promise.allSettled([...operations]);
  }
}
// Only an explicitly labelled owned disposable fixture. No supplied URL/route/auth.
export async function readDisposableHealth({port,timeoutMs=300,fetchImpl=fetch}={}) {
  const started=performance.now();
  const result=(status,error=null)=>({status,error,elapsedMs:Math.round(performance.now()-started)});
  if (!Number.isInteger(port) || port < 1 || port > 65535 || [8787,5173].includes(port) || !Number.isInteger(timeoutMs) || timeoutMs < 20 || timeoutMs > 1500) return result('invalid','invalid_config');
  const controller=new AbortController(); let timer,reader;
  const operation=async()=> {
    const response=await fetchImpl(`http://127.0.0.1:${port}/api/health`,{method:'GET',redirect:'manual',signal:controller.signal,credentials:'omit',headers:{Accept:'application/json'}});
    if (response.status >= 300 && response.status < 400 || response.redirected) return result('invalid','redirect_refused');
    if ([401,403].includes(response.status)) return result('unauthorized','unauthorized');
    if (!response.ok) return result('unavailable','upstream_unavailable');
    if (!/^application\/json(?:\s*;|$)/i.test(response.headers.get('content-type') ?? '')) return result('invalid','malformed');
    const size=response.headers.get('content-length');
    if (size !== null && (!/^\d+$/.test(size) || Number(size)>16384)) return result('invalid','oversized');
    if (!response.body) return result('invalid','malformed');
    reader=response.body.getReader(); const chunks=[]; let bytes=0;
    for (;;) {
      const {done,value}=await reader.read(); if (done) break;
      bytes+=value.byteLength;
      if (bytes>16384) return result('invalid','oversized');
      chunks.push(value);
    }
    let body;
    try {body=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(chunks)));}
    catch {return result('invalid','malformed');}
    if (!plain(body) || typeof body.ok !== 'boolean') return result('invalid','malformed');
    // Source-derived health boolean only; never private/degraded bodies.
    return result(body.ok ? 'fresh' : 'partial');
  };
  try {
    return await Promise.race([operation(),new Promise(resolve=> {timer=setTimeout(()=>{controller.abort();resolve(result('unavailable','timeout'));},timeoutMs);})]);
  } catch {return result('unavailable',controller.signal.aborted ? 'timeout' : 'unreachable');}
  finally {clearTimeout(timer);controller.abort();if(reader) await reader.cancel().catch(()=>{});}
}
export function createConnectionReader({config={},inferenceReader,relayReader,fetchImpl=fetch}={}) {
  // Copy only fixed server-owned config fields; unknown fields never become URLs.
  const settings=Object.fromEntries(SERVICE_MAP.map(s=> {
    const c=config[s.id];
    return [s.id,c===undefined ? undefined : {enabled:c?.enabled===true,source:c?.source,fixturePort:c?.fixturePort,timeoutMs:c?.timeoutMs}];
  }));
  return async()=> {
    const observedAt=new Date().toISOString();
    const services=await Promise.all(SERVICE_MAP.map(async service=> {
      const c=settings[service.id];
      const base={id:service.id,label:service.label,status:'not_configured',source:'none',observedAt,elapsedMs:0,errors:[]};
      if(service.id==='relay' && relayReader) {
        const started=performance.now();
        try {
          const relay=await relayReader();
          return {...base,status:relay.status,source:'isolated_relay',elapsedMs:Math.round(performance.now()-started),errors:relay.status==='fresh' ? [] : [{code:'relay_unavailable'}]};
        } catch {return {...base,status:'unavailable',source:'isolated_relay',errors:[{code:'relay_unavailable'}]};}
      }
      if(service.id==='inference') {
        const started=performance.now();
        try {
          const snapshot=await inferenceReader();
          return {...base,status:snapshot.status,source:snapshot.status === 'not_configured' ? 'none' : 'fixed_local_module',observedAt:snapshot.observedAt,elapsedMs:Math.round(performance.now()-started),errors:snapshot.errors.map(e=>({code:e.code}))};
        } catch {return {...base,status:'unavailable',errors:[{code:'observation_unavailable'}]};}
      }
      if(c===undefined) return base;
      if(!c.enabled) return {...base,status:'disabled'};
      if(service.id==='relay' && c.source==='disposable_fixture') {
        const r=await readDisposableHealth({port:c.fixturePort,timeoutMs:c.timeoutMs,fetchImpl});
        return {...base,status:r.status,source:'disposable_fixture',elapsedMs:r.elapsedMs,errors:r.error ? [{code:r.error}] : []};
      }
      return {...base,status:'unsupported',errors:[{code:service.id==='relay' ? 'source_route_held' : 'adapter_absent'}]};
    }));
    return {schemaVersion:'mesh-service-connections/v1',observedAt,services};
  };
}
