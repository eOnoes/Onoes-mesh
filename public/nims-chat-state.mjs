const uuid=value=>typeof value==='string'&&/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value);
export function createNimsChatState({request,onChange=()=>{}}){
  let available=false,epoch=0,busy=false,configured=false,project=null,conversations=[],listCursor=null,selected=null,groups=[],turnCursor=null;
  let note='Connect to browse Nims project chats.';
  const state=()=>({available,busy,configured,project,conversations:[...conversations],selected:selected&&{...selected},
    messages:groups.flatMap(group=>group.messages),hasOlder:Boolean(turnCursor||groups.some(g=>g.olderItemCursor)),
    moreConversations:Boolean(listCursor),note,readOnly:true});
  const publish=()=>onChange(state());
  const active=token=>available&&token===epoch;
  function clear(){++epoch;busy=false;configured=false;project=null;conversations=[];listCursor=null;selected=null;groups=[];turnCursor=null;note='Connect to browse Nims project chats.';publish();}
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
    note=`${selected.title} · ${selected.status}. Browsing the actual Codex chat. Sending and new chats are not enabled in this preview.`;
  }
  async function read(input,mode){
    if(!available||busy||!selected)return;
    const token=epoch;busy=true;publish();
    try{const result=await request('/api/relay/codex/history',{method:'POST',body:JSON.stringify(input)});if(!active(token))return;merge(result,mode);}
    catch(error){if(active(token))note=`History unavailable; the displayed record may be stale. ${error.message}`;}
    finally{if(active(token)){busy=false;publish();}}
  }
  return {
    state,
    setAvailable(value){if(available===value)return;available=value;if(!value)clear();else{note='Open Nims project chats to check the desktop connection.';publish();}},
    clear(){available=false;clear();},
    async catalog(more=false){
      if(!available||busy)return;
      const token=epoch;busy=true;publish();
      try{
        const status=await request('/api/relay/codex/status');if(!active(token))return;
        configured=status.configured===true;
        if(!configured){note='Nims project chats are not connected yet.';return;}
        const result=await request('/api/relay/codex/catalog',{method:'POST',body:JSON.stringify(more&&listCursor?{cursor:listCursor}:{})});
        if(!active(token))return;
        if(!Array.isArray(result.conversations)||!result.project)throw Error('Native conversation catalog unavailable.');
        if(project&&project.id!==result.project.id)throw Error('Native project identity changed.');
        project=result.project;listCursor=result.nextCursor;
        const combined=more?[...conversations,...result.conversations]:result.conversations;
        conversations=[...new Map(combined.map(c=>[c.id,c])).values()];
        note=selected?note:'Choose a native Nims conversation. Nothing is sent when you open it.';
      }catch(error){if(active(token))note=`Nims desktop connection unavailable. ${error.message}`;}
      finally{if(active(token)){busy=false;publish();}}
    },
    async select(id){
      if(!available||!uuid(id)||!conversations.some(c=>c.id===id))return;
      ++epoch;busy=false;selected=conversations.find(c=>c.id===id);groups=[];turnCursor=null;note='Reading the selected native conversation…';publish();
      await read({threadId:id},'latest');
    },
    refresh(){return selected?read({threadId:selected.id},'latest'):Promise.resolve();},
    older(){
      if(!selected)return Promise.resolve();
      const group=[...groups].reverse().find(g=>g.olderItemCursor);
      if(group)return read({threadId:selected.id,itemCursor:group.olderItemCursor},'olderItems');
      return turnCursor?read({threadId:selected.id,cursor:turnCursor},'olderTurns'):Promise.resolve();
    }
  };
}
