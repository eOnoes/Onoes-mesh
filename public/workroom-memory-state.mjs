const schema='onoes-workroom-memory-state/v1';
const labels={
  off:null,
  not_shared:['Not linked','This Workroom card has no link to a Mind project.'],
  offline:['Mind disconnected','Your card is saved on this PC. Shared updates are waiting for Mind.'],
  pending:['Pending','Waiting to record this update in Mind.'],
  uncertain:['Awaiting receipt','Mesh is waiting for confirmation that Mind saved this update.'],
  held:['Needs attention','Later updates will wait until the sharing issue is reviewed.'],
  saved:['Last update recorded','The last update was recorded in Mind. This does not approve the work.'],
  withdrawn:['Sharing paused','New updates are not shared. Previously recorded facts may remain.'],
  unavailable:['Unavailable','Memory sync status could not be verified.'],
};

export function memoryStatePresentation(value){
  if(value===undefined)return null; // Older backend; never invent a saved result.
  if(value?.constructor!==Object||Object.keys(value).sort().join(',')!=='schema,state'||
    value.schema!==schema||!Object.hasOwn(labels,value.state))return {state:'unavailable',label:labels.unavailable[0],description:labels.unavailable[1]};
  const text=labels[value.state];
  return text?{state:value.state,label:text[0],description:text[1]}:null;
}

export function paintMemoryState(element,value){
  const state=memoryStatePresentation(value);
  element.hidden=!state;
  const label=state?`Mind · ${state.label}`:'';
  const explain=state && ['offline','held','uncertain','withdrawn','unavailable'].includes(state.state);
  element.textContent=explain?`${label}. ${state.description}`:label;
  element.title=explain?'':state?.description||'';
  element.setAttribute('aria-label',state?`${label}. ${state.description}`:'');
}
