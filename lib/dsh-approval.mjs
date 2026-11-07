import {readFile} from 'node:fs/promises';
import {TaskError} from './task-store.mjs';
import {randomUUID} from 'node:crypto';
import {verifyDshTaskOutcome} from './dsh-task-outcome.mjs';
const unconfirmedDecision=()=>Object.assign(new TaskError(503,'Approval outcome unavailable. Refresh before retrying the same decision.'),{code:'DSH_DECISION_UNCONFIRMED'});

export function createDshApprovalClient({origin='http://127.0.0.1:4123',tokenFile='D:/Dev/Onoes-Relay/.private/dsh.key',fetchImpl=fetch,token}={}){
  const base=new URL(origin);
  if(base.protocol!=='http:' || !['127.0.0.1','localhost','[::1]'].includes(base.hostname) || base.username || base.password || base.pathname!=='/' || base.search || base.hash)throw new Error('DSH approvals require a fixed loopback HTTP origin.');
  async function request(suffix,body,authorize,protocol='approval'){
    let key;try{key=token||String(await readFile(tokenFile,'utf8')).trim();}catch{throw new TaskError(503,'DeepSeek approval credentials are unavailable on this PC.');}
    if(!key || key.length>4096)throw new TaskError(503,'DeepSeek approval credentials are unavailable on this PC.');
    authorize?.();
    let response;
    try{response=await fetchImpl(base.origin+(protocol==='native_task'?'/a2a':'/a2a/admin/approval'+suffix),{method:body?'POST':'GET',redirect:'manual',headers:{Authorization:'Bearer '+key,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(body?12000:3000)});}catch{if(protocol==='approval' && body)throw unconfirmedDecision();throw new TaskError(503,protocol==='native_task'?'DeepSeek task record is unavailable. No recovery state changed.':'DeepSeek approval service is unavailable.');}
    if(response.status===404 && !body)return {supported:false,pending:null,task:null,reason:'The DeepSeek bridge needs the approval update. No action was approved.'};
    if(response.status>=300 && response.status<400)throw new TaskError(503,'DeepSeek approval redirect refused.');
    if(!response.ok)throw new TaskError(response.status===409?409:503,response.status===409?'Approval changed or could not be confirmed. Refresh the exact request.':'DeepSeek refused the approval request.');
    const reader=response.body.getReader();const chunks=[];let size=0;
    try{for(;;){const chunk=await reader.read();if(chunk.done)break;size+=chunk.value.length;if(size>131072)throw new TaskError(503,'DeepSeek approval response exceeded its bound.');chunks.push(chunk.value);}}finally{await reader.cancel().catch(()=>{});}
    let data;try{data=JSON.parse(Buffer.concat(chunks).toString('utf8'));}catch{throw new TaskError(503,'DeepSeek returned an invalid approval response.');}
    if(protocol==='approval' && data.schema!=='mesh-dsh-approval/v1')throw new TaskError(503,'DeepSeek approval protocol mismatch.');
    return data;
  }
  function scoped(data,scope){
    const p=data.pending;
    const binding=data.binding;
    if((p || data.task) && (!binding || binding.sendId!==scope.id || binding.workroomTaskId!==scope.taskId || binding.contextId!==scope.conversationId || p && p.taskId!==binding.taskId || data.task && data.task.id!==binding.taskId))throw new TaskError(409,'DeepSeek approval binding does not match this task.');
    if(p && (p.sendId!==scope.id || p.workroomTaskId!==scope.taskId || p.contextId!==scope.conversationId || typeof p.requestId!=='string' || p.requestId.length>100 || typeof p.taskId!=='string' || p.taskId.length>100 || typeof p.toolName!=='string' || p.toolName.length>200 || typeof p.reason!=='string' || p.reason.length>2000 || !(p.arguments===null || typeof p.arguments==='string' && p.arguments.length<=16384) || p.canApprove!==false && p.canApprove!==true || p.canApprove && p.arguments===null))throw new TaskError(409,'DeepSeek approval does not match this task handoff.');
    if(data.task && data.task.contextId!==scope.conversationId)throw new TaskError(409,'DeepSeek result belongs to another conversation.');
    return data;
  }
  return {
    async readTaskOutcome(source,peerTaskId){
      if(typeof peerTaskId!=='string' || !/^[A-Za-z0-9_-]{1,100}$/.test(peerTaskId))throw new TaskError(400,'Choose a valid native task identity.');
      const id=randomUUID();const data=await request('',{jsonrpc:'2.0',id,method:'GetTask',params:{id:peerTaskId}},undefined,'native_task');
      if(data.jsonrpc!=='2.0' || data.id!==id || data.error)throw new TaskError(409,'Native task lookup was not confirmed. No outcome recorded.');
      return verifyDshTaskOutcome(data.result,{...source,peerTaskId});
    },
    async inspect(scope){return scoped(await request('?'+new URLSearchParams({sendId:scope.id,workroomTaskId:scope.taskId,contextId:scope.conversationId})),scope);},
    async decide(scope,body,authorize){
      const current=scoped(await this.inspect(scope),scope);const p=current.pending;
      if(!p || p.requestId!==body.requestId)throw new TaskError(409,'Approval is no longer pending. Refresh the request.');
      const result=await request('',{taskId:p.taskId,requestId:p.requestId,decision:body.decision},authorize);
      if(result.taskId!==p.taskId || result.requestId!==p.requestId || result.decision!==body.decision)throw new TaskError(409,'DeepSeek returned a mismatched decision receipt.');
      if(result.result?.task && (result.result.task.id!==p.taskId || result.result.task.contextId!==scope.conversationId))throw new TaskError(409,'DeepSeek returned a result for another task.');
      return result;
    }
  };
}

export function captureDshResult(workroom,taskId,send,task){
  if(!task || task.contextId!==send.conversationId || typeof task.id!=='string')return;
  const text=(task.artifacts||[]).flatMap(a=>a.parts||[]).map(p=>typeof p.text==='string'?p.text:p.content?.$case==='text'?p.content.value:'').filter(Boolean).join('\n');
  if(text && text.length<=64000)workroom.captureReplies(taskId,send.id,[{id:send.id,k:'you',t:''},{id:'dsh-'+task.id,k:'ag',t:text,created_at:task.status?.timestamp||send.at}]);
}
