import {TaskError} from './task-store.mjs';
const SCHEMA='onoes-mind-recall/v1';
const exact=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===[...keys].sort().join(',');
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
export function createMindRecallClient({baseUrl,token,fetchImpl=fetch,timeoutMs=4000}){
 const url=new URL(baseUrl);
 if(url.protocol!=='http:'||url.hostname!=='127.0.0.1'||!url.port||url.pathname!=='/'||url.search||url.hash||url.username||url.password||!string(token,4096)||!token||/[\r\n]/.test(token))throw Error('A fixed loopback Mind reader and server-side credential are required.');
 return {async recall(input){
  recallInput(input);const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeoutMs);let reader;
  try{
   const response=await fetchImpl(new URL('/v1/recall',url),{method:'POST',redirect:'error',cache:'no-store',signal:controller.signal,headers:{'Content-Type':'application/json',Authorization:'Bearer '+token},body:JSON.stringify({schema:SCHEMA,...input})});
   if(response.status!==200||!response.headers.get('content-type')?.includes('application/json'))throw Error('Unavailable');
   reader=response.body.getReader();let bytes=0;const chunks=[];
   while(true){const item=await reader.read();if(item.done)break;bytes+=item.value.byteLength;if(bytes>65536)throw Error('Bound exceeded');chunks.push(Buffer.from(item.value));}
   return validateRecall(JSON.parse(Buffer.concat(chunks).toString('utf8')),input.limit);
  }catch{throw new TaskError(503,'Onoes-Mind recall unavailable or its response could not be verified. No memory was written.');}
  finally{clearTimeout(timer);controller.abort();try{await reader?.cancel();}catch{}}
 }};
}
