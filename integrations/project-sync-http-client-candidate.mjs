// Server-only, explicitly constructed transport. No discovery, browser config or startup.
import {validateProjectEvent} from './project-sync-outbox-candidate.mjs';
import {request as httpRequest} from 'node:http';

const exact=(value,keys)=>value?.constructor===Object&&Object.keys(value).sort().join(',')===[...keys].sort().join(',');
const id=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,100}$/.test(value);

export class ProjectSyncTransportError extends Error {
  constructor(held=false){super(held?'Project sync response refused or unverified.':'Project sync transport unavailable; delivery may be uncertain.');this.name='ProjectSyncTransportError';this.projectSyncHeld=held;}
}

function flatJson(text){
  const body=JSON.parse(text);
  if(body?.constructor!==Object||Object.values(body).some(v=>v!==null&&typeof v==='object'))throw Error('Flat response required.');
  const keys=new Set();
  for(const match of text.matchAll(/"(?:\\.|[^"\\])*"/g)){
    if(text.slice(match.index+match[0].length).trimStart().startsWith(':')){
      const key=JSON.parse(match[0]);if(keys.has(key))throw Error('Duplicate response key.');keys.add(key);
    }
  }
  return body;
}

export function createProjectSyncHttpClient({baseUrl,token,storeId,timeoutMs=4000}){
  const url=new URL(baseUrl);
  if(url.protocol!=='http:'||url.hostname!=='127.0.0.1'||!url.port||Number(url.port)<1||url.pathname!=='/'||
    url.search||url.hash||url.username||url.password||!id(storeId)||
    typeof token!=='string'||! /^[A-Za-z0-9_-]{20,256}$/.test(token)||
    !Number.isSafeInteger(timeoutMs)||timeoutMs<10||timeoutMs>10000)throw Error('Fixed loopback service, identity and bounded timeout required.');
  function request(path,payload){
    return new Promise((resolve,reject)=>{
      let settled=false;
      const bytes=Buffer.from(JSON.stringify(payload));
      const req=httpRequest(new URL(path,url),{method:'POST',agent:false,
        headers:{'Content-Type':'application/json','Content-Length':bytes.length,Authorization:'Bearer '+token}},response=>{
        const values=name=>{const rows=[];for(let i=0;i<response.rawHeaders.length;i+=2)if(response.rawHeaders[i].toLowerCase()===name)rows.push(response.rawHeaders[i+1]);return rows;};
        const lengths=values('content-length');
        if(values('content-type').join(',')!=='application/json'||lengths.length!==1||
          !/^[0-9]{1,6}$/.test(lengths[0])||Number(lengths[0])>4096||values('transfer-encoding').length){finish(new ProjectSyncTransportError(true));return;}
        const chunks=[];let size=0;
        response.on('data',chunk=>{size+=chunk.length;if(size>4096)finish(new ProjectSyncTransportError(true));else chunks.push(chunk);});
        response.once('aborted',()=>finish(new ProjectSyncTransportError()));
        response.once('error',()=>finish(new ProjectSyncTransportError()));
        response.once('end',()=>{
          if(settled)return;
          if(size!==Number(lengths[0]))return finish(new ProjectSyncTransportError());
          let body;
          try{body=flatJson(new TextDecoder('utf-8',{fatal:true}).decode(Buffer.concat(chunks)));}
          catch{return finish(new ProjectSyncTransportError(true));}
          if(response.statusCode!==200){
            const unavailable=response.statusCode===503&&exact(body,['schema','code'])&&body.schema==='onoes-mind-project-error/v1'&&body.code==='unavailable';
            return finish(new ProjectSyncTransportError(!unavailable));
          }
          finish(null,body);
        });
      });
      const timer=setTimeout(()=>finish(new ProjectSyncTransportError()),timeoutMs);
      function finish(error,value){if(settled)return;settled=true;clearTimeout(timer);req.destroy();if(error)reject(error);else resolve(value);}
      req.once('error',()=>finish(new ProjectSyncTransportError()));
      req.end(bytes);
    });
  }
  function identity(body,query){return body.storeId===storeId&&body.scope==='project/onoes-mind/shared'&&
    body.principal==='mesh-project-sync'&&body.projectId===query.projectId&&body.eventId===query.eventId;}
  function receipt(body,query){return exact(body,['schema','storeId','scope','principal','projectId','eventId','cardId',
    'sequence','payloadHash','receiptId','durable','recordState'])&&body.schema==='onoes-mind-project-receipt/v1'&&
    identity(body,query)&&id(body.cardId)&&Number.isSafeInteger(body.sequence)&&body.sequence>0&&
    /^[a-f0-9]{64}$/.test(body.payloadHash)&&id(body.receiptId)&&body.durable===true&&
    ['active','superseded','purged','project_deleted'].includes(body.recordState);}
  return {
    async lookup(query){
      if(!exact(query,['projectId','eventId'])||!id(query.projectId)||!id(query.eventId))throw new ProjectSyncTransportError(true);
      const body=await request('/v1/project-events/lookup',{schema:'onoes-mind-project-lookup/v1',...query});
      if(receipt(body,query))return body;
      if(exact(body,['schema','storeId','scope','principal','projectId','eventId','found'])&&
        body.schema==='onoes-mind-project-absence/v1'&&identity(body,query)&&body.found===false)return body;
      throw new ProjectSyncTransportError(true);
    },
    async submit(event){
      const {hash}=validateProjectEvent(event);
      const body=await request('/v1/project-events/submit',event);
      if(!receipt(body,event)||body.cardId!==event.cardId||body.sequence!==event.sequence||body.payloadHash!==hash)throw new ProjectSyncTransportError(true);
      return body;
    },
  };
}
