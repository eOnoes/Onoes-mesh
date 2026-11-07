// A metadata save must not adopt a newer progress revision on behalf of old inputs.
export async function saveCardBrief(task, body, request) {
  if (!['project','criteria','owner','stage','team'].some(key => body[key] !== task.workroom[key])) return task;
  const saved = (await request('/api/workroom/' + task.id, {method:'PATCH',body:JSON.stringify(body)})).task;
  return {...saved, progress:task.progress};
}
