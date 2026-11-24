// A metadata save must not adopt a newer progress revision on behalf of old inputs.
export async function saveCardBrief(task, body, request, progress) {
  const briefChanged=['project','criteria','owner','stage','team'].some(key => body[key] !== task.workroom[key]);
  if(progress){
    const route='/api/workroom/'+task.id+(briefChanged?'':'/progress');
    const edit=briefChanged?{brief:body,progress}:progress;
    return (await request(route,{method:'PATCH',body:JSON.stringify(edit)})).task;
  }
  if (!briefChanged) return task;
  const saved = (await request('/api/workroom/' + task.id, {method:'PATCH',body:JSON.stringify(body)})).task;
  return {...saved, progress:task.progress};
}
