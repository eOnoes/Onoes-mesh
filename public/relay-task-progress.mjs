// Read-only saved Workroom progress. No chat binding, dispatch or browser storage.
export function relayProgressSummary(task){
  if(!task||typeof task.id!=='string'||typeof task.title!=='string'||!task.progress||!Array.isArray(task.progress.checklist)||typeof task.progress.goal!=='string')throw Error('Saved task progress is unavailable.');
  const steps=task.progress.checklist.map(step=>{
    if(typeof step.text!=='string'||!['pending','working','done','blocked'].includes(step.status))throw Error('Saved task checklist is invalid.');
    return {text:step.text,status:step.status};
  });
  return {id:task.id,title:task.title,goal:task.progress.goal,steps,done:steps.filter(step=>step.status==='done').length,
    total:steps.length,review:String(task.progress.decision||'pending')};
}
export function createRelayTaskProgress({root,button,request,document,timeoutMs=8000}){
  if(!root||!button)return {setAvailable(){},clear(){},refresh:async()=>{}};
  let available=false,paused=false,reading=false,epoch=0,selected='',model=null,abort=null;
  const el=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
  const title=el('h2','Task progress');
  const explanation=el('p','View a saved Workroom task. Chat messages do not change its checklist.');
  const label=el('label','Saved task');const picker=el('select');picker.setAttribute('aria-label','Saved task');label.append(picker);
  const refresh=el('button','Refresh tasks');refresh.type='button';
  const note=el('p');note.setAttribute('role','status');
  const body=el('section');const close=el('button','Done');close.type='button';
  const toolbar=el('div');toolbar.className='workroom-sheet-toolbar';toolbar.append(close);
  root.replaceChildren(toolbar,title,explanation,label,refresh,note,body);
  function controls(){button.disabled=!available||paused;picker.disabled=!available||paused||reading;refresh.disabled=picker.disabled;}
  function empty(){const option=el('option','Choose a task…');option.value='';picker.replaceChildren(option);picker.value='';}
  function paint(){
    body.replaceChildren();button.textContent=model?(model.total?`Task · ${model.done}/${model.total}`:'Task · no steps'):'Task progress';
    if(!model)return;
    body.append(el('h3',model.title),el('h4','Goal'),el('p',model.goal||'No goal saved yet.'),el('p',`${model.done} of ${model.total} saved steps done · Review: ${model.review}`));
    const list=el('ul');
    for(const step of model.steps){const symbol={pending:'○',working:'→',done:'✓',blocked:'!'}[step.status];list.append(el('li',`${symbol} ${step.status}: ${step.text}`));}
    body.append(list);if(!model.total)body.append(el('p','No checklist saved yet. Add steps in Workroom.'));
  }
  async function read(route){
    const controller=new AbortController();abort=controller;let timer;
    try{return await Promise.race([request(route,{signal:controller.signal}),new Promise((_,reject)=>{
      timer=setTimeout(()=>{controller.abort();reject(Error('Task progress timed out. Refresh to try again.'));},timeoutMs);
      controller.signal.addEventListener('abort',()=>reject(Error('Task progress read stopped.')),{once:true});
    })]);}finally{clearTimeout(timer);if(abort===controller)abort=null;}
  }
  async function refreshSaved(withList=false){
    if(!available||paused||reading||(!withList&&!selected))return;
    reading=true;const turn=epoch;controls();
    try{
      if(withList){
        const result=await read('/api/workroom');if(turn!==epoch||!available)return;
        if(!Array.isArray(result?.tasks))throw Error('Saved task list is unavailable.');
        const previous=selected;empty();
        for(const task of result.tasks){if(typeof task.id!=='string'||typeof task.title!=='string')continue;const option=el('option',task.title);option.value=task.id;picker.append(option);}
        if(previous&&result.tasks.some(task=>task.id===previous)){selected=previous;picker.value=previous;}
        else{selected='';model=null;paint();}
      }
      if(selected){
        const result=await read('/api/workroom/'+encodeURIComponent(selected));if(turn!==epoch||!available)return;
        const next=relayProgressSummary(result?.task);if(next.id!==selected)throw Error('Saved task identity changed.');
        const changed=JSON.stringify(next)!==JSON.stringify(model);model=next;if(changed)paint();
        note.textContent='Saved Workroom progress checked '+new Date().toLocaleTimeString()+'.';
      }else note.textContent='Choose the task whose saved progress you want to view.';
    }catch(error){if(turn===epoch&&available)note.textContent='Could not refresh saved task progress. Last shown values may be stale. Refresh to try again.';}
    finally{if(turn===epoch){reading=false;controls();}}
  }
  button.addEventListener('click',()=>{if(!available||paused)return;root.showModal();refreshSaved(true);});
  close.addEventListener('click',()=>root.close());root.addEventListener('close',()=>{if(available)button.focus();});
  picker.addEventListener('change',()=>{if(!available||paused||reading)return;selected=picker.value;model=null;paint();note.textContent='Reading saved progress…';refreshSaved();});
  refresh.addEventListener('click',()=>refreshSaved(true));
  function clear(){epoch++;abort?.abort();abort=null;available=false;reading=false;selected='';model=null;empty();paint();note.textContent='Connect to view saved task progress.';if(root.open)root.close();controls();}
  empty();paint();controls();
  return {refresh:()=>refreshSaved(),clear,setAvailable(value,isPaused=false){paused=Boolean(isPaused);if(!value){clear();return;}available=true;controls();}};
}
