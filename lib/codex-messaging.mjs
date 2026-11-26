import {createHash} from 'node:crypto';
import {CodexRequestError} from './codex-request-store.mjs';

const uuid=v=>typeof v==='string'&&/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(v);
const hash=v=>createHash('sha256').update(JSON.stringify(v)).digest('hex');
const exact=(value,keys)=>value&&typeof value==='object'&&!Array.isArray(value)&&Object.keys(value).sort().join(',')===[...keys].sort().join(',');

export function createCodexMessaging({transport,store,scopeKey,verifyCaller,inspect,project}){
  if(!transport?.dispatch||!store||typeof scopeKey!=='string'||![verifyCaller,inspect,project].every(v=>typeof v==='function'))throw Error('Invalid native messaging binding.');
  async function execute(kind,input,admitted){
    const keys=kind==='send'?['requestId','threadId','text']:['requestId','projectId','text','title'];
    if(!exact(input,keys)||!uuid(input.requestId)||!uuid(kind==='send'?input.threadId:input.projectId)||
      typeof input.text!=='string'||!input.text.trim()||input.text.length>4000||input.text.includes('\0')||
      kind==='new'&&(typeof input.title!=='string'||input.title.length>120||/[\r\n\0]/.test(input.title)))throw new CodexRequestError(400,'Choose a destination and enter a message of at most 4000 characters.');
    if(typeof admitted!=='function'||!admitted())throw new CodexRequestError(403,'Reconnect before sending. Nothing was sent.');
    const request={requestId:input.requestId,kind,targetId:kind==='send'?input.threadId:input.projectId,
      hash:hash(kind==='send'?[kind,input.threadId,input.text]:[kind,input.projectId,input.title.trim(),input.text])};
    const previous=store.existing(scopeKey,request);if(previous)return previous;
    await verifyCaller();
    let args;
    if(kind==='send'){
      await inspect(input.threadId);
      args={threadId:input.threadId,hostId:'local',prompt:input.text};
    }else{
      const selected=await project();
      if(selected.projectId!==input.projectId)throw new CodexRequestError(403,'Choose the approved native project.');
      args={prompt:input.text,target:{type:'project',projectId:input.projectId,environment:{type:'local'}}};
      if(input.title.trim())args.title=input.title.trim();
    }
    if(!admitted())throw new CodexRequestError(403,'Access ended before sending. Nothing was sent.');
    const claimed=store.claim(scopeKey,request);if(!claimed.fresh)return claimed.receipt;
    let acknowledgement;
    try{
      acknowledgement=await transport.dispatch(kind==='send'?'send_message_to_thread':'create_thread',args,{requestId:input.requestId,admitted});
    }catch(error){
      return store.finish(scopeKey,input.requestId,error?.nativeNotSent===true?'not_sent':'unconfirmed');
    }
    // A success acknowledgement is acceptance by Codex, not a finished reply.
    if(acknowledgement?.acknowledged!==true)return store.finish(scopeKey,input.requestId,'unconfirmed');
    const data=acknowledgement?.data;
    if(data?.hostId&&data.hostId!=='local')return store.finish(scopeKey,input.requestId,'unconfirmed');
    if(kind==='send'){
      const returned=data?.threadId??data?.thread?.id;
      if(returned&&returned!==input.threadId||data?.hostId&&data.hostId!=='local')return store.finish(scopeKey,input.requestId,'unconfirmed');
      return store.finish(scopeKey,input.requestId,'accepted',{nativeThreadId:input.threadId});
    }
    const id=data?.threadId??data?.thread?.id;
    if(uuid(id)){
      try{await inspect(id);}catch{return store.finish(scopeKey,input.requestId,'unconfirmed');}
      return store.finish(scopeKey,input.requestId,'accepted',{nativeThreadId:id});
    }
    if(uuid(data?.clientThreadId))return store.finish(scopeKey,input.requestId,'accepted',{clientThreadId:data.clientThreadId});
    return store.finish(scopeKey,input.requestId,'unconfirmed');
  }
  const active=new Set();
  function tracked(kind,input,admitted){const work=execute(kind,input,admitted);active.add(work);work.finally(()=>active.delete(work)).catch(()=>{});return work;}
  return {
    send:(input,admitted)=>tracked('send',input,admitted),
    create:(input,admitted)=>tracked('new',input,admitted),
    receipt(input){if(!exact(input,['requestId'])||!uuid(input.requestId))throw new CodexRequestError(400,'Choose a valid send receipt.');return store.get(scopeKey,input.requestId);},
    close:()=>Promise.allSettled([...active])
  };
}
