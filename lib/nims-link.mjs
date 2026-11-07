import {createCodexClient} from './codex-client.mjs';
import {TaskError} from './task-store.mjs';
export function withNims(base,{root,workroom,client=createCodexClient({root})}){
 let available=false,error='Not connected',closing=false;const jobs=new Set();
 async function nimsAgents(){try{await client.connect();available=true;error='';}catch{available=false;error='Nims local Codex connection unavailable. Existing requests are not replayed.';}
  const active=workroom.nims.list().some(r=>['prepared','running'].includes(r.state));
  return [{id:'nims',name:'Nims (Codex)',backend:'codex',device:'this PC',status:available?(active?'thinking':'idle'):'stopped',conversation_id:available?'mesh-nims':null,approval:null,capabilities:{plan:true,review:true,work:false,mode:'read-only'}}];
 }
 async function agents(){const results=await Promise.allSettled([base.agents(),nimsAgents()]);return results.flatMap(r=>r.status==='fulfilled'?r.value:[]);}
 return {...base,agents,
 async snapshot(){const snapshot=await base.snapshot();return {...snapshot,agents:await agents(),nims:{connected:available,mode:'read-only',error}};},
 async nativeRead(route){if(route==='/api/nims/capabilities'){await nimsAgents();if(!available)throw new TaskError(503,error);return {taskSessionBinding:1};}
  if(route==='/api/agents/nims/sessions/mesh-nims/messages')return {messages:workroom.nims.list().flatMap(r=>[{id:r.sendId,k:'you',t:r.payload,ts:r.at},...(['completed','failed','blocked','interrupted'].includes(r.state)?[{id:r.sendId+'-result',k:'ag',t:r.state==='completed'?r.text:'Nims request '+r.state+'. '+r.text,ts:r.finishedAt||r.at}]:[])])};
  return base.nativeRead(route);
 },
 async taskMessage(body,admitted){if(body.agentId!=='nims')return base.taskMessage(body,admitted);if(closing||!admitted())throw new TaskError(403,'Nims request admission expired.');if(body.conversationId!=='mesh-nims')throw new TaskError(409,'Nims conversation changed.');await nimsAgents();if(!available)throw new TaskError(503,error);if(!admitted())throw new TaskError(403,'Admission expired.');const {run,fresh}=workroom.nims.reserve(body);if(!fresh){if(['failed','blocked','interrupted'].includes(run.state))throw new TaskError(409,'Inspect this ended Nims attempt before a fresh request.');return {ok:true};}
  const operation=new Promise(resolve=>setImmediate(resolve)).then(async()=>{try{const result=await client.run({threadId:workroom.nims.thread(run.taskId),text:run.payload,onBinding:binding=>workroom.nims.bind(run.sendId,binding)});workroom.nims.finish(run.sendId,result.permissionBlocked?'blocked':result.status==='completed'?'completed':'failed',result.permissionBlocked?'Additional permission was declined in the read-only connector; no report can approve work.':result.text||'No final result returned.');}catch{if(!closing)workroom.nims.finish(run.sendId,'failed','Nims could not confirm completion. Inspect the saved native identity; no automatic retry.');}});
  jobs.add(operation);operation.finally(()=>jobs.delete(operation));return {ok:true};
 },
 async close(){closing=true;for(const r of workroom.nims.list())if(['prepared','running'].includes(r.state))workroom.nims.finish(r.sendId,'interrupted','Mesh stopped this connection. Request was not replayed.');await client.close();await Promise.allSettled([...jobs]);await base.close();}
 };
}
