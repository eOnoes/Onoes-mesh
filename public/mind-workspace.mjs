// Deliberate retrieval from the existing admitted Workroom store. No second memory store.
export function taskContext(task) {
  if (!task || typeof task.id !== 'string' || typeof task.title !== 'string' ||
      !Number.isSafeInteger(task.revision) || !task.progress || !task.workroom ||
      !Number.isSafeInteger(task.progress.revision) || !Number.isSafeInteger(task.workroom.revision)) {
    throw Error('Saved task context is unavailable. Open the task in Workroom to inspect it.');
  }
  const p = task.progress;
  return {
    id: task.id, title: task.title, description: task.description || '',
    taskRevision: task.revision, briefRevision: task.workroom.revision, progressRevision: p.revision,
    updatedAt: task.updatedAt || 'Not recorded', project: task.workroom.project || 'Not assigned',
    stage: task.workroom.stage || 'Not recorded', goal: p.goal || '',
    checklist: (Array.isArray(p.checklist) ? p.checklist : []).map(item => ({text:item.text, status:item.status})),
    result: p.result || '', evidence: p.evidence || '', reviewer: p.reviewer || 'Not recorded',
    decision: ['pending','approved','changes_requested'].includes(p.decision) ? p.decision : 'Not recorded'
  };
}

export function createMindWorkspace({root, request, openTask, doc = globalThis.document}) {
  if (!root) return {setTasks() {}, setAvailable() {}, clear() {}};
  let epoch = 0, available = false, tasks, reading = false;
  const node = (tag, text = '') => { const n = doc.createElement(tag); n.textContent = text; return n; };
  const label = node('label', 'Saved Workroom task'); label.htmlFor = 'mind-task';
  const select = node('select'); select.id = 'mind-task';
  const read = node('button', 'Read selected task'); read.type = 'button';
  const forget = node('button', 'Clear this view'); forget.type = 'button';
  const state = node('p'); state.setAttribute('role', 'status');
  const content = node('article'); content.className = 'box section-gap'; content.hidden = true;
  root.replaceChildren(label, select, read, forget, state, content);
  const recall=createMindRecallView({root,request,doc});
  function controls() {
    select.disabled = !available || !tasks?.length || reading;
    read.disabled = !available || !select.value || reading;
    forget.disabled = content.hidden && !reading;
  }
  function reset(message) {
    epoch++; reading = false; content.replaceChildren(); content.hidden = true;
    state.textContent = message; controls();
  }
  select.addEventListener('change', () => reset('Selection changed. Choose Read selected task to retrieve its current record.'));
  forget.addEventListener('click', () => { select.value = ''; reset('View cleared. The saved task remains in Workroom.'); });
  read.addEventListener('click', async () => {
    if (!available || reading) return;
    if (!tasks?.some(task => task.id === select.value)) { reset('Choose a task from the current saved task list.'); return; }
    reset('Reading the selected task…'); reading = true; controls();
    const id = select.value, turn = epoch;
    try {
      const response = await request('/api/workroom/' + encodeURIComponent(id));
      if (turn !== epoch || !available) return;
      if (response?.task?.id !== id) throw Error('The returned record does not match the selected task. Refresh Workroom and try again.');
      const context = taskContext(response.task);
      const add = (tag, text) => { const n = node(tag, text); content.append(n); return n; };
      add('h2', context.title);
      add('p', `Source: Mesh Workroom · task ${context.id} · project ${context.project}`);
      add('p', `Revisions: task ${context.taskRevision}, brief ${context.briefRevision}, progress ${context.progressRevision}. Task updated: ${context.updatedAt}. Read: ${new Date().toISOString()}.`);
      add('p', `Saved stage: ${context.stage}. Recorded decision: ${context.decision}. Reviewer label: ${context.reviewer}.`);
      add('p', 'These are saved task records, not independently verified facts. A pending result still needs review. Open Workroom for the full report and review provenance.');
      for (const [title, value] of [['Description',context.description],['Goal',context.goal],['Result',context.result],['Evidence / source references',context.evidence]]) {
        add('h3',title); const text = add('p',value || 'Not recorded'); text.style.whiteSpace = 'pre-wrap'; text.style.overflowWrap = 'anywhere';
      }
      add('h3','Saved checklist');
      if (!context.checklist.length) add('p','No checklist recorded.');
      for (const item of context.checklist) add('p', `${item.status}: ${item.text}`);
      const open = add('button','Open source task in Workroom'); open.type = 'button';
      open.addEventListener('click', () => { if (available && turn === epoch) openTask(id); });
      content.hidden = false; state.textContent = 'Selected task retrieved. This snapshot does not update automatically.';
    } catch (error) {
      if (turn === epoch) reset(error.message || 'Task context unavailable. Reconnect and try again.');
    } finally { if (turn === epoch) { reading = false; controls(); } }
  });
  return {
    setTasks(value) {
      tasks = Array.isArray(value) ? value.filter(t => typeof t.id === 'string' && typeof t.title === 'string').map(t => ({id:t.id,title:t.title})) : undefined;
      select.replaceChildren(node('option','Choose a task…')); select.firstChild.value = '';
      for (const task of tasks || []) { const option = node('option',task.title); option.value = task.id; select.append(option); }
      select.value = ''; reset(tasks ? (tasks.length ? 'Select a task. Only that record will be retrieved.' : 'No saved Workroom tasks.') : 'Saved task list unavailable. Reconnect and refresh app status.');
    },
    setAvailable(value) { recall.setAvailable(value); available = Boolean(value); if (!available) reset('Connect to read a selected saved task.'); else controls(); },
    clear() { recall.setAvailable(false); available = false; tasks = undefined; select.replaceChildren(); select.value = ''; reset('Private task context cleared. Reconnect to choose a saved task.'); }
  };
}


export function createMindRecallView({root,request,doc=globalThis.document}){
 const node=(tag,text='')=>{const n=doc.createElement(tag);n.textContent=text;if(tag==='p')n.style.overflowWrap='anywhere';return n;};
 const section=node('section');section.className='box section-gap';
 const check=node('button','Check memory connection');check.type='button';
 const label=node('label','Search Onoes-Mind');label.htmlFor='mind-query';
 const query=node('input');query.id='mind-query';query.maxLength=512;
 const read=node('button','Read matching memories');read.type='button';
 const clear=node('button','Clear memory view');clear.type='button';
 const state=node('p','Memory connection not checked. Saved Workroom context above is a separate source.');state.setAttribute('role','status');
 const results=node('div');let available=false,configured=false,busy=false,epoch=0;
 section.append(node('h2','Onoes-Mind memory'),check,label,query,read,clear,state,results);root.append(section);
 const controls=()=>{check.disabled=!available||busy;query.disabled=!available||!configured||busy;read.disabled=query.disabled||!query.value.trim();clear.disabled=!available;};
 function reset(message){epoch++;busy=false;results.replaceChildren();state.textContent=message;controls();}
 query.addEventListener('input',()=>reset('Query changed. Choose Read matching memories to retrieve a fresh snapshot.'));
 clear.addEventListener('click',()=>{query.value='';reset('Memory view cleared. Source records were not changed.');});
 check.addEventListener('click',async()=>{
  if(!available||busy)return;reset('Checking the configured reader…');busy=true;controls();const turn=epoch;
  try{const status=await request('/api/mind/status');if(turn!==epoch||!available)return;configured=status?.configured===true;state.textContent=configured?'Synthetic test reader configured. No live memory access. Choose a query to read.':'Onoes-Mind reader is not connected. Saved Workroom context remains available.';}
  catch{if(turn===epoch){configured=false;state.textContent='Memory connection unavailable. No records were read.';}}
  finally{if(turn===epoch){busy=false;controls();}}
 });
 read.addEventListener('click',async()=>{
  if(!available||!configured||busy||!query.value.trim())return;
  reset('Reading matching memories…');busy=true;controls();const turn=epoch;
  try{
   const snapshot=await request('/api/mind/recall',{method:'POST',body:JSON.stringify({query:query.value.trim(),limit:8})});if(turn!==epoch||!available)return;
   if(snapshot?.schema!=='onoes-mind-recall/v1'||snapshot.source!=='canonical_ledger'||!Array.isArray(snapshot.records))throw Error('Invalid memory response');
   results.append(node('p',`Source: Onoes-Mind canonical ledger · read ${snapshot.observedAt} · request ${snapshot.requestId}. Synthetic fixture only; source claims are not independent verification.`));
   for(const record of snapshot.records){const card=node('article');card.className='box section-gap';card.append(node('p',`Record ${record.record_id} · project ${record.project_id} · scope ${record.scope_id}`),node('p',record.claim),node('p',`Source class ${record.source_class} · observed ${record.observed_at||'not recorded'} · hash ${record.payload_hash}`));for(const p of record.provenance||[])card.append(node('p',`${p.type}: ${p.ref} · ${p.content_hash}`));results.append(card);}
   if(!snapshot.records.length)results.append(node('p','No matching records in the reader’s permitted scopes.'));
   state.textContent='Memory snapshot retrieved. Read again for corrections or deletion updates.';
  }catch{if(turn===epoch)reset('Memory read unavailable or invalid. Previous results cleared.');}
  finally{if(turn===epoch){busy=false;controls();}}
 });
 controls();return {setAvailable(value){available=Boolean(value);if(!available){configured=false;query.value='';reset('Private memory view cleared. Reconnect and check the reader again.');}else controls();}};
}
