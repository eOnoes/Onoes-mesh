import {createNimsChatState,nimsStatusLabel} from './nims-chat-state.mjs';

export function createNimsChatReader({root,request}){
  if(!root)return {setAvailable(){},clear(){}};
  const document=root.ownerDocument;
  const project=root.querySelector('[data-nims-project]'),select=root.querySelector('[data-nims-conversation]');
  const status=root.querySelector('[data-nims-status]'),history=root.querySelector('[data-nims-history]');
  const refresh=root.querySelector('[data-nims-refresh]'),older=root.querySelector('[data-nims-older]'),more=root.querySelector('[data-nims-more]');
  const mode=root.querySelector('[data-nims-mode]'),newButton=root.querySelector('[data-nims-new]'),newForm=root.querySelector('[data-nims-new-form]');
  const titleInput=root.querySelector('[data-nims-title]'),newText=root.querySelector('[data-nims-new-text]'),createButton=root.querySelector('[data-nims-create]');
  const compose=root.querySelector('[data-nims-compose]'),textInput=root.querySelector('[data-nims-text]'),sendButton=root.querySelector('[data-nims-send]');
  const sendNote=root.querySelector('[data-nims-send-note]');
  let signature='',catalogSignature='',core;
  function draw(state){
    project.textContent=state.project?.label??'Nims project';status.textContent=state.note;
    mode.textContent=state.readOnly?'Read-only preview · messages stay in Codex.':'Your existing Codex conversations · messages stay in Codex.';
    newButton.hidden=state.readOnly;newButton.disabled=!state.available||state.busy||state.writing||!state.project;
    newForm.hidden=!state.newChat;compose.hidden=state.readOnly||state.newChat||!state.selected;
    if(textInput.value!==state.draft)textInput.value=state.draft;
    textInput.disabled=!state.available||state.readOnly||state.writing;
    sendButton.disabled=!state.canSend;createButton.disabled=!state.canCreate;
    if(titleInput.value!==state.title)titleInput.value=state.title;
    if(newText.value!==state.newText)newText.value=state.newText;
    titleInput.disabled=newText.disabled=state.writing;
    sendNote.textContent=state.sendNote;

    select.disabled=!state.available||state.busy||state.writing||!state.configured;
    const next=JSON.stringify(state.conversations);
    if(next!==catalogSignature){
      catalogSignature=next;select.replaceChildren();
      const empty=document.createElement('option');empty.value='';empty.textContent='Choose a conversation…';select.append(empty);
      for(const conversation of state.conversations){const option=document.createElement('option');option.value=conversation.id;option.textContent=`${conversation.title} · ${nimsStatusLabel(conversation.status)}`;select.append(option);}
    }
    select.value=state.selected?.id??'';
    refresh.disabled=!state.available||state.busy||state.writing;older.disabled=refresh.disabled;older.hidden=!state.hasOlder;
    more.disabled=refresh.disabled;more.hidden=!state.moreConversations;
    const changed=JSON.stringify([state.selected?.id,state.messages]);
    if(changed!==signature){
      const switched=signature&&!signature.startsWith(JSON.stringify([state.selected?.id]).slice(0,-1)+',');
      const atBottom=history.scrollHeight-history.scrollTop-history.clientHeight<40;
      const top=history.scrollTop,height=history.scrollHeight;
      const previousFirst=history.firstElementChild?.dataset.messageId;
      signature=changed;history.replaceChildren();
      for(const message of state.messages){
        const article=document.createElement('article');article.className='box';article.dataset.messageId=message.id;
        const who=document.createElement('strong');who.textContent=message.role==='user'?(message.queued?'YOU · queued in Codex':message.viaRelay?'YOU · via Relay':'YOU'):'NIMS';
        const body=document.createElement('pre');body.textContent=message.text;
        article.append(who,body);
        if(message.truncated){const note=document.createElement('p');note.className='fine';note.textContent='The desktop API shortened this message.';article.append(note);}
        history.append(article);
      }
      if(!state.messages.length){const empty=document.createElement('p');empty.textContent=state.selected?'No chat messages on this page. Earlier history may contain messages.':'Choose a conversation to read its saved messages.';history.append(empty);}
      const prepended=previousFirst&&state.messages[0]?.id!==previousFirst&&state.messages.some(m=>m.id===previousFirst);
      if(switched||atBottom&&!prepended)history.scrollTop=history.scrollHeight;
      else if(prepended)history.scrollTop=top+history.scrollHeight-height;
      else history.scrollTop=top;
    }
  }
  let storage;try{storage=document.defaultView.sessionStorage;}catch{storage={getItem(){throw Error('Storage unavailable');},setItem(){throw Error('Storage unavailable');}};}
  core=createNimsChatState({request,storage,onChange:draw});
  textInput.addEventListener('input',()=>core.setDraft(textInput.value));
  compose.addEventListener('submit',event=>{event.preventDefault();core.send();});
  newButton.addEventListener('click',()=>core.startNew());
  root.querySelector('[data-nims-cancel-new]').addEventListener('click',()=>core.cancelNew());
  titleInput.addEventListener('input',()=>core.setNewTitle(titleInput.value));
  newText.addEventListener('input',()=>core.setNewText(newText.value));
  newForm.addEventListener('submit',event=>{event.preventDefault();core.create();});
  select.addEventListener('change',()=>core.select(select.value));
  refresh.addEventListener('click',async()=>{await core.catalog();await core.refresh();});
  older.addEventListener('click',()=>core.older());more.addEventListener('click',()=>core.catalog(true));
  root.addEventListener('toggle',()=>{if(root.open&&core.state().available&&!core.state().project)core.catalog();});
  const timer=setInterval(()=>{if(root.open&&!document.hidden&&core.state().available)core.refresh();},10000);
  timer.unref?.();draw(core.state());
  return {setAvailable(value){core.setAvailable(value);},clear(){core.clear();}};
}
