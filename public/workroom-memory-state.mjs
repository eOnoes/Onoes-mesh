const schema='onoes-workroom-memory-state/v1';
const labels={
  off:null,not_shared:null,
  pending:['Pending','Waiting to record this update in Mind.'],
  uncertain:['Awaiting receipt','Delivery is uncertain. No saved result has been confirmed.'],
  held:['Needs attention','Sharing is held for review. Later updates will wait.'],
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
  element.textContent=state?`Mind · ${state.label}`:'';
  element.title=state?.description||'';
  element.setAttribute('aria-label',state?`${element.textContent}. ${state.description}`:'');
}
