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
  const saved = node('details');
  saved.append(node('summary','Saved task context (optional)'), label, select, read, forget, state, content);
  root.replaceChildren();
  const recall=createMindRecallView({root,request,doc});
  root.append(saved);
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
      recall.setTasks(tasks);
      select.replaceChildren(node('option','Choose a task…')); select.firstChild.value = '';
      for (const task of tasks || []) { const option = node('option',task.title); option.value = task.id; select.append(option); }
      select.value = ''; reset(tasks ? (tasks.length ? 'Select a task. Only that record will be retrieved.' : 'No saved Workroom tasks.') : 'Saved task list unavailable. Reconnect and refresh app status.');
    },
    setAvailable(value) { recall.setAvailable(value); available = Boolean(value); if (!available) reset('Connect to read a selected saved task.'); else controls(); },
    clear() { recall.setAvailable(false); available = false; tasks = undefined; select.replaceChildren(); select.value = ''; reset('Private task context cleared. Reconnect to choose a saved task.'); }
  };
}


export function recallConnection(status){
 if(status?.configured===true&&status.source==='canonical_ledger')return {configured:true,source:'canonical_ledger',message:'Shared Onoes-Mind reader configured. Search deliberately shared project facts; agent-private memory is excluded.'};
 if(status?.configured===true&&status.source==='disposable_fixture')return {configured:true,source:'disposable_fixture',message:'Synthetic test reader configured. No live memory access. Choose a query to read.'};
 return {configured:false,source:'not_configured',message:status?.configured===true?'Memory reader source could not be verified. No records were read.':'Onoes-Mind reader is not connected. Saved Workroom context remains available.'};
}

function workroomFact(record) {
 if (record.kind !== 'project_fact' || record.source_class !== 'workroom' || typeof record.claim !== 'string') return null;
 try {
  const fact = JSON.parse(record.claim);
  if (fact?.source !== 'workroom' || typeof fact.cardId !== 'string' || !fact.cardId.trim() ||
      typeof fact.title !== 'string' || !fact.title.trim()) return null;
  return fact;
 } catch {
  return null;
 }
}

// Read-only presentation of an already shared agent-handoff claim. No ingestion, authority or dispatch.
function agentHandoff(record) {
 if (record.kind !== 'project_fact' || record.source_class !== 'agent_handoff' || typeof record.claim !== 'string') return null;
 let handoff;
 try {
  handoff = JSON.parse(record.claim);
 } catch {
  return null;
 }
 if (!handoff || typeof handoff !== 'object' || Array.isArray(handoff)) return null;
 if (handoff.schema !== 'onoes-handoff/v1') return null;
 if (typeof record.project_id !== 'string' || !record.project_id.trim() || record.project_id.length > 96) return null;
 if (handoff.project_id !== record.project_id) return null;
 if (typeof handoff.handoff_id !== 'string' || !handoff.handoff_id.trim() || handoff.handoff_id.length > 128) return null;
 if (typeof handoff.author !== 'string' || !/^[a-z][a-z0-9_-]*$/.test(handoff.author) || handoff.author.length > 48) return null;
 if (!Number.isSafeInteger(handoff.revision) || handoff.revision <= 0) return null;
 if (typeof handoff.next_action !== 'string' || !handoff.next_action.trim() || handoff.next_action.length > 4096) return null;
 for (const [key, max] of [['objective',4096], ['recipient',96]]) {
  if (handoff[key] !== undefined && (typeof handoff[key] !== 'string' || handoff[key].length > max)) return null;
 }
 for (const key of ['completed', 'remaining']) {
  if (handoff[key] === undefined) continue;
  if (!Array.isArray(handoff[key]) || handoff[key].length > 32) return null;
  for (const item of handoff[key]) if (typeof item !== 'string' || item.length > 4096) return null;
 }
 return handoff;
}

function renderRecallRecord(record, node, sourceLinks) {
 const card = node('article');
 card.className = 'box section-gap';
 const fact = workroomFact(record);
 const handoff = fact ? null : agentHandoff(record);
 if (fact) {
  const title = node('h3', fact.title);
  title.style.overflowWrap = 'anywhere';
  card.append(title);
  for (const [key, label] of [['stage','Stage'], ['owner','Owner'], ['goal','Goal'], ['blocker','Blocker'], ['result','Result']]) {
   if (typeof fact[key] !== 'string' || !fact[key].trim()) continue;
   const body = node('p', fact[key]);
   body.style.whiteSpace = 'pre-wrap';
   card.append(node('strong', label), body);
  }
  const refs = (record.provenance || []).filter(item => item?.type === 'workroom');
  const cardReference = /^card:([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})@\d+\/\d+\/\d+$/;
  if (refs.length && refs.every(item => cardReference.exec(item.ref)?.[1] === fact.cardId)) {
   const link = node('a', 'Open current Workroom card');
   link.className = 'mind-card-link';
   sourceLinks.set(link, fact.cardId);
   card.append(link);
  }
 } else if (handoff) {
  const heading = node('h3', 'Project handoff');
  heading.style.overflowWrap = 'anywhere';
  card.append(heading);
  const meta = node('p', `Project ${handoff.project_id} · recorded author ${handoff.author}${typeof handoff.recipient === 'string' ? ` · recorded recipient ${handoff.recipient}` : ''} · Document revision ${handoff.revision} · handoff ID ${handoff.handoff_id}`);
  meta.style.whiteSpace = 'pre-wrap';
  card.append(meta);
  if (typeof handoff.objective === 'string') {
   const body = node('p', handoff.objective);
   body.style.whiteSpace = 'pre-wrap';
   card.append(node('strong', 'Objective'), body);
  }
  const action = node('p', handoff.next_action);
  action.style.whiteSpace = 'pre-wrap';
  card.append(node('strong', 'Next action'), action);
  for (const [key, listLabel] of [['completed','Completed (reported)'], ['remaining','Remaining work']]) {
   if (!Array.isArray(handoff[key])) continue;
   card.append(node('strong', listLabel));
   if (!handoff[key].length) card.append(node('p','None recorded.'));
   for (const item of handoff[key]) { const body = node('p', item); body.style.whiteSpace = 'pre-wrap'; card.append(body); }
  }
 } else {
  card.append(node('p', record.claim));
 }
 const source = node('details');
 source.append(node('summary','Source details'), node('p',`Record ${record.record_id} · project ${record.project_id} · scope ${record.scope_id}`),
  node('p',`Source class ${record.source_class} · observed ${record.observed_at || 'not recorded'} · hash ${record.payload_hash}`));
 for (const item of record.provenance || []) source.append(node('p', `${item.type}: ${item.ref} · ${item.content_hash}`));
 if (fact || handoff) source.append(node('p', record.claim));
 card.append(source);
 return card;
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
 const results=node('div');let available=false,configured=false,busy=false,epoch=0,readerSource='not_configured';
 const sourceLinks = new Map();
 let taskIds = new Set();
 function syncSourceLinks() {
  for (const [link, id] of sourceLinks) {
   link.hidden = !available || !taskIds.has(id);
   if (link.hidden) link.removeAttribute('href');
   else link.setAttribute('href', '#task=' + id);
  }
 }
 section.append(node('h2','Onoes-Mind memory'),check,label,query,read,clear,state,results);root.append(section);
 const controls=()=>{check.disabled=!available||busy;query.disabled=!available||!configured||busy;read.disabled=query.disabled||!query.value.trim();clear.disabled=!available;};
 function reset(message){epoch++;busy=false;sourceLinks.clear();results.replaceChildren();state.textContent=message;controls();}
 query.addEventListener('input',()=>reset('Query changed. Choose Read matching memories to retrieve a fresh snapshot.'));
 clear.addEventListener('click',()=>{query.value='';reset('Memory view cleared. Source records were not changed.');});
 check.addEventListener('click',async()=>{
  if(!available||busy)return;reset('Checking the configured reader…');busy=true;controls();const turn=epoch;
  try{const status=await request('/api/mind/status');if(turn!==epoch||!available)return;const connection=recallConnection(status);configured=connection.configured;readerSource=connection.source;state.textContent=connection.message;}
  catch{if(turn===epoch){configured=false;state.textContent='Memory connection unavailable. No records were read.';}}
  finally{if(turn===epoch){busy=false;controls();}}
 });
 read.addEventListener('click',async()=>{
  if(!available||!configured||busy||!query.value.trim())return;
  reset('Reading matching memories…');busy=true;controls();const turn=epoch;
  try{
   const snapshot=await request('/api/mind/recall',{method:'POST',body:JSON.stringify({query:query.value.trim(),limit:8})});if(turn!==epoch||!available)return;
   if(snapshot?.schema!=='onoes-mind-recall/v1'||snapshot.source!=='canonical_ledger'||!Array.isArray(snapshot.records))throw Error('Invalid memory response');
   const sourceNote=readerSource==='disposable_fixture'?'Synthetic fixture only; source claims are not independent verification.':'Read-only shared project facts; source claims are not independent verification.';
   results.append(node('p',`Source: Onoes-Mind canonical ledger · read ${snapshot.observedAt} · request ${snapshot.requestId}. ${sourceNote}`));
   for (const record of snapshot.records) results.append(renderRecallRecord(record, node, sourceLinks));
   syncSourceLinks();
   if(!snapshot.records.length)results.append(node('p','No matching records in the reader’s permitted scopes.'));
   state.textContent='Memory snapshot retrieved. Read again for corrections or deletion updates.';
  }catch{if(turn===epoch)reset('Memory read unavailable or invalid. Previous results cleared.');}
  finally{if(turn===epoch){busy=false;controls();}}
 });
 controls();return {
  setTasks(tasks){taskIds = new Set((tasks || []).map(task => task.id));syncSourceLinks();},
  setAvailable(value){
   available=Boolean(value);
   if(!available){
    taskIds.clear(); configured=false; readerSource='not_configured'; query.value='';
    reset('Private memory view cleared. Reconnect and check the reader again.');
   } else { syncSourceLinks(); controls(); }
  }
 };
}
