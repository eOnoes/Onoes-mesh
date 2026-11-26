export const NIMS_RECEIPTS='mesh.nims.receipts.v1';
const uuid=value=>typeof value==='string'&&/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value);
const digest=async value=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(value)))),n=>n.toString(16).padStart(2,'0')).join('');

export function createNimsSendState({request,getContext,onChange=()=>{},onAccepted=async()=>{},storage,makeId=()=>crypto.randomUUID(),hash=digest}){
  if(!storage){const memory=new Map();storage={getItem:k=>memory.get(k)??null,setItem:(k,v)=>memory.set(k,v),removeItem:k=>memory.delete(k)};}
  let epoch=0,enabled=false,writing=false,blocked=false,newChat=false,title='',newText='',note='';
  const drafts=new Map(),pending=new Map(),queued=new Map();
  function save(){const raw=JSON.stringify([...pending.values()]);storage.setItem(NIMS_RECEIPTS,raw);if(storage.getItem(NIMS_RECEIPTS)!==raw)throw Error('Browser send receipt could not be saved.');}
  function restore(){
    try{
      const raw=storage.getItem(NIMS_RECEIPTS);if(!raw)return;
      const items=JSON.parse(raw);
      if(!Array.isArray(items)||items.length>32||items.some(p=>!p||Object.keys(p).sort().join(',')!=='hash,kind,requestId,targetId,version'||p.version!==1||!uuid(p.requestId)||!uuid(p.targetId)||!['send','new'].includes(p.kind)||!(/^[a-f0-9]{64}$/).test(p.hash)))throw Error();
      for(const p of items)pending.set(p.requestId,p);
      if(items.length)note='A saved request needs confirmation. Nothing is resent automatically.';
    }catch{blocked=true;note='Saved send receipts are unavailable. You can still read conversations.';}
  }
  const active=token=>enabled&&token===epoch&&getContext().available;
  function state(){
    const c=getContext(),draft=drafts.get(c.selected?.id)||'';
    return {writing,newChat,title,newText,draft,sendNote:note,canSend:enabled&&!c.readOnly&&!c.busy&&!writing&&!blocked&&!newChat&&Boolean(c.selected)&&Boolean(draft.trim()),
      canCreate:enabled&&!c.readOnly&&!c.busy&&!writing&&!blocked&&newChat&&Boolean(c.project)&&Boolean(newText.trim())};
  }
  function finish(receipt,meta){
    if(!receipt||receipt.requestId!==meta.requestId||receipt.kind!==meta.kind||receipt.targetId!==meta.targetId||receipt.payloadHash!==meta.hash)throw Error('Send receipt did not match the selected request.');
    if(receipt.state==='accepted'||receipt.state==='not_sent'){
      pending.delete(meta.requestId);
      try{save();}catch{blocked=true;note='The request was checked, but browser receipt cleanup failed. Reconnect before sending again.';}
    }
    return receipt.state;
  }
  async function submit(kind){
    const c=getContext(),s=state();if(kind==='send'?!s.canSend:!s.canCreate)return;
    const text=kind==='send'?s.draft:newText,targetId=kind==='send'?c.selected.id:c.project.id,chatTitle=title.trim();
    const token=epoch;writing=true;note='Preparing the selected request…';onChange();
    let meta,invoked=false;
    try{
      const fingerprint=await hash(kind==='send'?[kind,targetId,text]:[kind,targetId,chatTitle,text]);if(!active(token))return;
      meta=[...pending.values()].find(p=>p.kind===kind&&p.targetId===targetId&&p.hash===fingerprint);
      if(!meta){
        if(pending.size>=32)throw Error('Earlier send receipts need review before another request.');
        meta={version:1,requestId:makeId(),kind,targetId,hash:fingerprint};pending.set(meta.requestId,meta);
      }
      try{save();}catch{blocked=true;throw Error('Browser send receipt could not be saved. Nothing was sent.');}
      const baseline=new Set(c.nativeMessages.map(m=>m.id));
      const body=kind==='send'?{requestId:meta.requestId,threadId:targetId,text}:{requestId:meta.requestId,projectId:targetId,title:chatTitle,text};
      invoked=true;
      const result=await request('/api/relay/codex/'+(kind==='send'?'send':'new'),{method:'POST',body:JSON.stringify(body)});
      if(!active(token))return;
      const outcome=finish(result.receipt,meta);
      if(outcome==='accepted'){
        if(kind==='send'){drafts.delete(targetId);queued.set(meta.requestId,{targetId,baseline,id:'queued-'+meta.requestId,role:'user',text,queued:true});}
        else{newChat=false;title='';newText='';}
        note=kind==='send'?'Accepted by Codex. Its reply may still be pending.':result.receipt.nativeThreadId?'New chat accepted by Codex.':'Codex is setting up the chat. Refresh conversations shortly.';
      }else note=outcome==='not_sent'?'Nothing was sent. Reconnect, then choose Send when ready.':'Delivery is not confirmed. Your draft is kept; checking again never resends this request.';
      writing=false;onChange();
      if(outcome==='accepted')await onAccepted(kind,result.receipt);
    }catch(error){if(active(token))note=invoked?'Could not confirm this request. Your draft and receipt are kept; no automatic resend.':error.message;}
    finally{if(active(token)){writing=false;onChange();}}
  }
  return {
    state,
    queuedMessages(){const id=getContext().selected?.id;return [...queued.values()].filter(q=>q.targetId===id).map(({baseline,targetId,...message})=>message);},
    synchronize(messages){for(const [id,q] of queued)if(q.targetId===getContext().selected?.id&&messages.some(m=>m.role==='user'&&m.text===q.text&&!q.baseline.has(m.id)))queued.delete(id);},
    setAvailable(value){if(enabled===value)return;enabled=value;++epoch;writing=false;if(value)restore();else{drafts.clear();queued.clear();pending.clear();newChat=false;title='';newText='';note='';blocked=false;}onChange();},
    setDraft(value){const c=getContext();if(enabled&&!c.readOnly&&!writing&&c.selected&&typeof value==='string'&&value.length<=4000){drafts.set(c.selected.id,value);onChange();}},
    startNew(){const c=getContext();if(enabled&&!c.readOnly&&!writing&&c.project){newChat=true;title='';newText='';onChange();}},
    cancelNew(){if(!writing){newChat=false;title='';newText='';onChange();}},
    setNewTitle(value){if(newChat&&!writing&&typeof value==='string'&&value.length<=120){title=value;onChange();}},
    setNewText(value){if(newChat&&!writing&&typeof value==='string'&&value.length<=4000){newText=value;onChange();}},
    send:()=>submit('send'),create:()=>submit('new'),
    async recover(){
      const c=getContext();if(!enabled||c.readOnly||writing||blocked)return;
      const token=epoch;
      for(const meta of [...pending.values()]){
        try{
          const reply=await request('/api/relay/codex/receipt',{method:'POST',body:JSON.stringify({requestId:meta.requestId})});if(!active(token))return;
          if(!reply.receipt){note='An earlier request has no receipt yet. Nothing is resent automatically.';continue;}
          const outcome=finish(reply.receipt,meta);
          note=outcome==='accepted'?'Codex accepted the earlier request. Refresh its conversation.':outcome==='not_sent'?'The earlier request was not sent.':'An earlier request is unconfirmed. Check its Codex conversation before trying again.';
        }catch{if(active(token))note='Earlier send receipts could not be checked. Nothing was resent.';}
      }
      if(active(token))onChange();
    }
  };
}
