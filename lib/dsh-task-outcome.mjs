import {createHash} from 'node:crypto';
import {TaskError} from './task-store.mjs';
const terminal=new Set(['TASK_STATE_COMPLETED','TASK_STATE_CANCELED','TASK_STATE_FAILED','TASK_STATE_REJECTED']);
const hash=value=>createHash('sha256').update(value).digest('hex');
export function verifyDshTaskOutcome(task,source){
  if(!task || task.id!==source.peerTaskId || task.contextId!==source.conversationId || !Array.isArray(task.history))throw new TaskError(409,'Native task identity or conversation does not match this handoff.');
  const matches=task.history.filter(message=>['ROLE_USER','user',1].includes(message.role) && (message.parts||[]).map(part=>typeof part.text==='string'?part.text:part.content?.$case==='text'?part.content.value:'').join('')===source.payload);
  if(matches.length!==1)throw new TaskError(409,'Native task history does not uniquely match the exact saved handoff.');
  if(!terminal.has(task.status?.state))throw new TaskError(409,'Native task is not confirmed terminal. No outcome recorded.');
  const proof={schema:'mesh-dsh-task-proof/v1',taskId:task.id,contextId:task.contextId,state:task.status.state,payloadHash:hash(source.payload),nativeTimestamp:task.status.timestamp||null,artifactsHash:hash(JSON.stringify(task.artifacts||[]))};
  return {peerTaskId:task.id,state:task.status.state,proofHash:hash(JSON.stringify(proof)),verifiedAt:new Date().toISOString()};
}
