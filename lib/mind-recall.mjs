import {TaskError} from './task-store.mjs';
const SCHEMA='onoes-mind-recall/v1';
function exact(value, keys) {
 if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
 return Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
}
const string=(value,max=32768)=>typeof value==='string'&&value.length<=max;
export function recallInput(body){
 if(!exact(body,['query','limit'])||!string(body.query,512)||!body.query.trim()||!Number.isInteger(body.limit)||body.limit<1||body.limit>20)throw new TaskError(400,'Enter a memory query of 1–512 characters and a result limit of 1–20.');
 return body;
}
export function validateRecall(body,limit){
 if(!exact(body,['schema','requestId','source','observedAt','records'])||body.schema!==SCHEMA||body.source!=='canonical_ledger'||!string(body.requestId,100)||!body.requestId||!string(body.observedAt,100)||!Number.isFinite(Date.parse(body.observedAt))||!Array.isArray(body.records)||body.records.length>limit)throw Error('Invalid recall response');
 for(const r of body.records){
  if(!exact(r,['record_id','scope_id','kind','project_id','payload_hash','claim','source_class','observed_at','provenance'])||!['record_id','scope_id','kind','project_id','payload_hash','claim','source_class'].every(k=>string(r[k]))||(r.observed_at!==null&&!string(r.observed_at,100))||!Array.isArray(r.provenance)||r.provenance.length>100)throw Error('Invalid recall record');
  if(!r.provenance.every(p=>exact(p,['type','ref','content_hash'])&&['type','ref','content_hash'].every(k=>string(p[k]))))throw Error('Invalid recall provenance');
 }
 return body;
}
export function createMindRecallClient({baseUrl,token,fetchImpl=fetch,timeoutMs=4000,expectedScope}){
 const url=new URL(baseUrl);
 if(url.protocol!=='http:'||url.hostname!=='127.0.0.1'||!url.port||url.pathname!=='/'||url.search||url.hash||url.username||url.password||!string(token,4096)||!token||/[\r\n]/.test(token))throw Error('A fixed loopback Mind reader and server-side credential are required.');
 if(expectedScope!==undefined&&!(typeof expectedScope==='string'&&/^project\/[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\/shared$/.test(expectedScope)))throw Error('One shared project scope is required.');
 return {async recall(input){
  recallInput(input);const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeoutMs);let reader;
  try{
   const response=await fetchImpl(new URL('/v1/recall',url),{method:'POST',redirect:'error',cache:'no-store',signal:controller.signal,headers:{'Content-Type':'application/json',Authorization:'Bearer '+token},body:JSON.stringify({schema:SCHEMA,...input})});
   if(response.status!==200||!response.headers.get('content-type')?.includes('application/json'))throw Error('Unavailable');
   reader=response.body.getReader();let bytes=0;const chunks=[];
   while(true){const item=await reader.read();if(item.done)break;bytes+=item.value.byteLength;if(bytes>65536)throw Error('Bound exceeded');chunks.push(Buffer.from(item.value));}
   const decoded = new TextDecoder('utf-8', {fatal:true}).decode(Buffer.concat(chunks));
   const result=validateRecall(JSON.parse(decoded),input.limit);
   if(expectedScope!==undefined&&result.records.some(record=>record.scope_id!==expectedScope))throw Error('Reader scope mismatch');
   return result;
  }catch{throw new TaskError(503,'Onoes-Mind recall unavailable or its response could not be verified. No memory was written.');}
  finally{clearTimeout(timer);controller.abort();try{await reader?.cancel();}catch{}}
 }};
}

// Trusted native-host configuration only. No HTTP, CLI or ambient environment
// accepts this object. The host must separately establish private credential
// custody, the exact BoundRecallLedger process/binding and owner authorization.
// reviewRef records that review; it is not itself proof or a consent mechanism.
export function configureMindRecall({standalone,fixtureOptions,approvedOptions}){
 if(fixtureOptions!==undefined){
  if(!standalone||approvedOptions!==undefined||!exact(fixtureOptions,['baseUrl','source','token'])||fixtureOptions.source!=='disposable_fixture')throw Error('Mind recall seam is synthetic standalone testing only.');
  return {client:createMindRecallClient(fixtureOptions),source:'disposable_fixture'};
 }
 if(approvedOptions===undefined)return {client:null,source:'not_configured'};
 if(standalone||!exact(approvedOptions,['baseUrl','token','binding'])||!exact(approvedOptions.binding,['servicePrincipal','storeId','environment','scopeId','reviewRef']))throw Error('Reviewed native Mind configuration required.');
 const binding=approvedOptions.binding;
 if(binding.servicePrincipal!=='mesh-recall'||binding.scopeId!=='project/onoes-mind/shared'||typeof binding.storeId!=='string'||
    !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(binding.storeId)||
    typeof binding.environment!=='string'||!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(binding.environment)||
    !string(binding.reviewRef,256)||!binding.reviewRef.trim()||/[\x00-\x1f\x7f]/.test(binding.reviewRef))throw Error('Reviewed native Mind configuration required.');
 return {client:createMindRecallClient({baseUrl:approvedOptions.baseUrl,token:approvedOptions.token,expectedScope:binding.scopeId}),source:'canonical_ledger'};
}
