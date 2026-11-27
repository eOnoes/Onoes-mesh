const uuid=value=>typeof value==='string'&&/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value);
import {createNimsSendState} from './nims-send-state.mjs';
const STATUS_LABELS=Object.create(null,{notLoaded:{value:'Saved chat',enumerable:true},idle:{value:'Idle',enumerable:true},active:{value:'Working',enumerable:true},running:{value:'Working',enumerable:true},inProgress:{value:'Working',enumerable:true},systemError:{value:'Needs attention',enumerable:true},interrupted:{value:'Paused',enumerable:true}});
export function nimsStatusLabel(status){return typeof status==='string'&&Object.hasOwn(STATUS_LABELS,status)?STATUS_LABELS[status]:'Status unknown';}
export function createNimsChatState({request,onChange=()=>{},storage,makeId,hash}){
  let available=false,epoch=0,busy=false,configured=false,project=null,conversations=[],listCursor=null,selected=null,groups=[],turnCursor=null;
  let note='Connect to browse Nims project chats.',readOnly=true,sender;
  const state=()=>({available,busy,configured,project,conversations:[...conversations],selected:selected&&{...selected},
    ...sender?.state(),messages:[...groups.flatMap(group=>group.messages),...sender?.queuedMessages()??[]],hasOlder:Boolean(turnCursor||groups.some(g=>g.olderItemCursor)),
    moreConversations:Boolean(listCursor),note,readOnly});
  const publish=()=>onChange(state());
  const active=token=>available&&token===epoch;
  function clear(){++epoch;busy=false;configured=false;project=null;conversations=[];listCursor=null;selected=null;groups=[];turnCursor=null;note='Connect to browse Nims project chats.';readOnly=true;sender?.setAvailable(false);publish();}
  function merge(result,mode){
    const incoming=result.groups;
    if(!Array.isArray(incoming)||result.conversation?.id!==selected?.id)throw Error('Native conversation identity changed.');
    const unseen=[];
    for(const group of incoming){
      const index=groups.findIndex(g=>g.id===group.id);
      if(index<0){unseen.push(group);continue;}
      const old=groups[index],items=mode==='olderItems'?[...group.messages,...old.messages]:[...old.messages,...group.messages];
      const merged=new Map(items.map(m=>[m.id,m]));
      groups[index]={...group,messages:[...merged.values()],olderItemCursor:mode==='latest'?old.olderItemCursor:group.olderItemCursor};
    }
    groups=mode==='olderTurns'?[...unseen,...groups]:[...groups,...unseen];
    if(mode!=='olderItems')turnCursor=result.olderTurnCursor;
    selected=result.conversation;
    sender?.synchronize(groups.flatMap(group=>group.messages));
    note=`${selected.title} · ${nimsStatusLabel(selected.status)}${readOnly?' · read-only preview':''}.`;
  }
  async function read(input,mode){
    if(!available||busy||!selected||sender?.state().writing)return{loaded:false};
    const token=epoch,thread=selected.id;busy=true;publish();
    let loaded=false;
    try{const result=await request('/api/relay/codex/history',{method:'POST',body:JSON.stringify(input)});if(!active(token))return{loaded:false};merge(result,mode);loaded=true;}
    catch(error){if(active(token))note=`History unavailable; the displayed record may be stale. ${error.message}`;}
    finally{if(active(token)){busy=false;publish();}}
    return{loaded,token,thread};
  }
  async function prefetchOlderItems(token,thread){
    let attempts=0;
    while(attempts<2){
      if(!active(token)||busy||selected?.id!==thread||sender?.state().writing)return;
      if(groups.some(g=>g.messages.some(m=>m.role==='user')))return;
      const group=[...groups].reverse().find(g=>g.olderItemCursor);
      if(!group)return;
      const target=group.id,cursor=group.olderItemCursor;
      const outcome=await read({threadId:selected.id,itemCursor:cursor},'olderItems');
      if(!outcome.loaded||outcome.token!==token||outcome.thread!==thread)return;
      ++attempts;
      if(outcome.token!==epoch){return;}
      const updated=groups.find(g=>g.id===target);
      if(updated&&updated.olderItemCursor===cursor)return;
    }
  }
  sender=createNimsSendState({request,storage,makeId,hash,
    getContext:()=>({available,readOnly,selected,project,busy,nativeMessages:groups.flatMap(group=>group.messages)}),onChange:publish,
    async onAccepted(kind,receipt){
      if(kind==='new'){await api.catalog();if(receipt.nativeThreadId&&conversations.some(c=>c.id===receipt.nativeThreadId))await api.select(receipt.nativeThreadId);}
      else if(selected?.id===receipt.targetId)await api.refresh();
    }});
  const api={
    state,send:sender.send,create:sender.create,startNew:sender.startNew,cancelNew:sender.cancelNew,
    setDraft:sender.setDraft,setNewTitle:sender.setNewTitle,setNewText:sender.setNewText,recover:sender.recover,
    setAvailable(value){if(available===value)return;available=value;if(!value)clear();else{note='Open Nims project chats to check the desktop connection.';sender.setAvailable(true);publish();}},
    clear(){available=false;clear();},
    async catalog(more=false){
      if(!available||busy)return;
      const token=epoch;busy=true;publish();
      try{
        const status=await request('/api/relay/codex/status');if(!active(token))return;
        configured=status.configured===true;readOnly=status.readOnly!==false;
        if(!configured){note='Nims project chats are not connected yet.';return;}
        const result=await request('/api/relay/codex/catalog',{method:'POST',body:JSON.stringify(more&&listCursor?{cursor:listCursor}:{})});
        if(!active(token))return;
        if(!Array.isArray(result.conversations)||!result.project)throw Error('Native conversation catalog unavailable.');
        if(project&&project.id!==result.project.id)throw Error('Native project identity changed.');
        project=result.project;listCursor=result.nextCursor;
        const combined=more?[...conversations,...result.conversations]:result.conversations;
        conversations=[...new Map(combined.map(c=>[c.id,c])).values()];
        note=selected?note:'Choose a Nims conversation. Opening it does not send anything.';
        await sender.recover();
      }catch(error){if(active(token))note=`Nims desktop connection unavailable. ${error.message}`;}
      finally{if(active(token)){busy=false;publish();}}
    },
    async select(id){
      if(!available||sender.state().writing||!uuid(id)||!conversations.some(c=>c.id===id))return;
      ++epoch;busy=false;selected=conversations.find(c=>c.id===id);groups=[];turnCursor=null;note='Reading the selected native conversation…';publish();
      const token=epoch,thread=id;
      const outcome=await read({threadId:id},'latest');
      if(outcome.loaded&&active(token)&&selected?.id===thread)await prefetchOlderItems(token,thread);
    },
    refresh(){return selected?read({threadId:selected.id},'latest'):Promise.resolve();},
    older(){
      if(!selected)return Promise.resolve();
      const group=[...groups].reverse().find(g=>g.olderItemCursor);
      if(group)return read({threadId:selected.id,itemCursor:group.olderItemCursor},'olderItems');
      return turnCursor?read({threadId:selected.id,cursor:turnCursor},'olderTurns'):Promise.resolve();
    }
  };
  return api;
}
