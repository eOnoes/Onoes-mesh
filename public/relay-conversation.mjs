export const RECEIPT_KEY = 'mesh.relay.receipt.v2';
const LEGACY_KEY = 'mesh.relay.pending.v1';
const identity = value => typeof value === 'string' && value.length > 0 && value.length <= 256;
const same = (a,b) => a && b && a.agentId === b.agentId && a.sessionId === b.sessionId;
const key = value => JSON.stringify([value.agentId,value.sessionId]);
const validReceipt = p => p && Object.keys(p).sort().join(',') === 'agentId,hash,id,sessionId,version' &&
  p.version === 2 && identity(p.agentId) && identity(p.sessionId) && /^[0-9a-f-]{36}$/.test(p.id) && /^[0-9a-f]{64}$/.test(p.hash);
const hashText = async text => Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(text))),n=>n.toString(16).padStart(2,'0')).join('');

// One ordinary conversation; Relay owns durable history/outbox. Browser retains no message body.
export function createRelayConversation({request,storage,onChange=()=>{},uuid=()=>crypto.randomUUID(),digest=hashText}) {
  let available=false,blocked=false,initializing=false,sending=false,live=false,epoch=0,reads=0;
  let agents=[],destination=null,messages=[],observedAt=null,pending=null,note='Connect to choose a Relay agent.';
  const drafts=new Map();
  function state() {
    return {available,initializing,sending,live,agents:[...agents],destination:destination && {...destination},
      messages:[...messages],observedAt,pending:pending && {...pending},note,
      draft:destination ? drafts.get(key(destination)) || '' : '',
      canSend:available&&!initializing&&!sending&&!blocked&&Boolean(destination)&&agents.some(peer=>peer.id===destination.agentId)&&(!pending||Boolean(same(pending,destination)))&&(live||Boolean(same(pending,destination)))};
  }
  const publish=()=>onChange(state());
  const current=turn=>available&&turn===epoch;
  function persist(receipt) {
    const value=JSON.stringify(receipt);storage.setItem(RECEIPT_KEY,value);
    if(storage.getItem(RECEIPT_KEY)!==value)throw Error('Retry receipt could not be saved. Nothing was sent.');
  }
  async function restore(turn) {
    const raw=storage.getItem(RECEIPT_KEY);
    if(raw){pending=JSON.parse(raw);if(!validReceipt(pending))throw Error('Saved retry receipt is invalid. Inspect it before sending another message.');}
    const old=storage.getItem(LEGACY_KEY);
    if(old){
      const legacy=JSON.parse(old);
      if(!identity(legacy.id)||!identity(legacy.agentId)||!identity(legacy.sessionId)||typeof legacy.text!=='string'||!legacy.text||legacy.text.length>4000)throw Error('Earlier send needs manual recovery. Its saved receipt was preserved.');
      const migrated={version:2,id:legacy.id,agentId:legacy.agentId,sessionId:legacy.sessionId,hash:await digest(legacy.text)};
      if(!current(turn))return;
      if(!validReceipt(migrated)||(pending&&(!same(pending,migrated)||pending.id!==migrated.id||pending.hash!==migrated.hash)))throw Error('Conflicting retry receipts preserved. Inspect them before sending.');
      persist(migrated);pending=migrated;drafts.set(key(migrated),legacy.text);
      storage.removeItem(LEGACY_KEY);
      if(storage.getItem(LEGACY_KEY)!==null)throw Error('Earlier receipt migration could not complete. Sending is paused.');
    }
    if(current(turn)&&pending){destination={agentId:pending.agentId,sessionId:pending.sessionId,name:pending.agentId};note='Uncertain send restored. Re-enter its exact original text to retry the same receipt; no automatic send.';}
  }
  async function refresh() {
    if(!available||initializing)return;
    const turn=epoch,read=++reads;
    try {
      const list=await request('/relay/api/agents');
      if(!current(turn)||read!==reads)return;
      if(!Array.isArray(list))throw Error('Agent list unavailable.');
      agents=list.filter(a=>identity(a.id)).map(a=>({id:a.id,name:typeof a.name==='string'?a.name:a.id,sessionId:identity(a.conversation_id)?a.conversation_id:null,status:a.status||'unknown'}));
      if(!destination){live=false;note='Choose an agent to read its current conversation.';publish();return;}
      const peer=agents.find(a=>a.id===destination.agentId);
      if(!peer)throw Error('Selected agent is unavailable. No other agent was selected.');
      destination.name=peer.name;
      const result=await request(`/relay/api/agents/${encodeURIComponent(destination.agentId)}/sessions/${encodeURIComponent(destination.sessionId)}/messages`);
      if(!current(turn)||read!==reads)return;
      if(!Array.isArray(result?.messages))throw Error('Conversation history unavailable.');
      messages=result.messages.map(m=>({id:String(m.id??''),k:m.k==='you'?'you':'ag',t:String(m.t??''),at:String(m.created_at??''),
        files:(Array.isArray(m.attachments)?m.attachments:[]).filter(f=>typeof f.name==='string').map(f=>({name:f.name,size:Number(f.size)||0}))}));
      live=peer.sessionId===destination.sessionId;observedAt=new Date().toISOString();
      note=live ? (pending?'Uncertain send: retry requires its exact original text and destination.':'Conversation checked. Sending requires an explicit Send.') : 'Native conversation changed. This is the selected historical session. Use current conversation explicitly; an uncertain retry stays bound to its original session.';
      publish();
    }catch(error){if(current(turn)&&read===reads){live=false;note=`History unavailable; last displayed record is stale. ${error.message}`;publish();}}
  }
  async function select(agentId) {
    if(!available||initializing||sending)return;
    const peer=agents.find(a=>a.id===agentId);
    if(!peer?.sessionId){note='Choose an available agent with a current conversation.';publish();return;}
    epoch++;reads++;destination={agentId:peer.id,sessionId:peer.sessionId,name:peer.name};messages=[];observedAt=null;live=false;
    note='Reading the explicitly selected conversation…';publish();await refresh();
  }
  async function send() {
    if(!state().canSend)return;
    const text=state().draft.trim();if(!text)return;
    const turn=epoch,target={...destination};sending=true;publish();
    try {
      const hash=await digest(text);if(!current(turn))return;
      if(pending&&(!same(pending,target)||pending.hash!==hash))throw Error('An earlier send is uncertain. Retry its exact original text and destination; a new send is paused.');
      const capabilities=await request('/relay/api/mesh-capabilities');if(!current(turn))return;
      if(capabilities?.taskSessionBinding!==1)throw Error('Relay session binding is unavailable. Nothing was sent.');
      const list=await request('/relay/api/agents');if(!current(turn))return;
      const peer=Array.isArray(list)&&list.find(a=>a.id===target.agentId);
      if(!peer||(!pending&&peer.conversation_id!==target.sessionId)){live=false;throw Error('Selected destination changed. Nothing was sent; explicitly select the current conversation.');}
      if(!pending){const receipt={version:2,id:uuid(),agentId:target.agentId,sessionId:target.sessionId,hash};persist(receipt);pending=receipt;}
      const receipt={...pending};
      const result=await request(`/relay/api/agents/${encodeURIComponent(receipt.agentId)}/message`,{method:'POST',body:JSON.stringify({id:receipt.id,text,expectedConversationId:receipt.sessionId})});
      if(!current(turn))return;
      if(result?.ok!==true)throw Error('Send outcome was not acknowledged. Retry only the same receipt.');
      storage.removeItem(RECEIPT_KEY);
      if(storage.getItem(RECEIPT_KEY)!==null)throw Error('Accepted, but the retry receipt could not be cleared. Inspect before continuing.');
      pending=null;drafts.delete(key(target));note='Relay accepted the message. Acceptance is separate from an agent reply.';
    }catch(error){if(current(turn))note=`${error.message}${pending?' Receipt retained; no automatic retry.':''}`;}
    finally{if(current(turn)){sending=false;publish();}}
  }
  return {
    state,refresh,select,send,
    setDraft(text){if(available&&destination&&!sending){drafts.set(key(destination),String(text).slice(0,4000));publish();}},
    async setAvailable(value){
      value=Boolean(value);if(value===available)return;
      epoch++;reads++;available=value;live=false;
      if(!value){agents=[];destination=null;messages=[];observedAt=null;drafts.clear();pending=null;blocked=false;initializing=false;sending=false;note='Private chat cleared. Reconnect to choose an agent.';publish();return;}
      initializing=true;const turn=epoch;publish();
      try{await restore(turn);}catch(error){if(current(turn)){blocked=true;note=error.message;}}
      if(current(turn)){initializing=false;publish();if(!blocked)await refresh();}
    }
  };
}
