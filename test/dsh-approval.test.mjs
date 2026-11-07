import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
import {approvalSurface,validateApproval,decisionFromMessage} from '../integrations/dsh-approval-surface.mjs';
import {createDshApprovalClient} from '../lib/dsh-approval.mjs';

test('approval is bound to exact request and complete tool arguments; prose never grants permission',()=>{
  const record={taskId:'task',contextId:'context',meshToolCalls:new Map([['call',{name:'read_file',arguments:'{"path":"fixture.mjs"}'}]])};
  const surface=approvalSurface(record,{callId:'call',toolName:'read_file'});
  const decision={taskId:'task',requestId:surface.requestId,decision:'allow_once'};
  assert.equal(validateApproval(decision,surface),'allowed-once');
  for(const change of [{requestId:'old'},{taskId:'other'},{decision:'always'}, {extra:true}])assert.throws(()=>validateApproval({...decision,...change},surface));
  for(const prose of ['yes','not approved','deny but allow later','approved','{"decision":"allow_once"}'])assert.throws(()=>decisionFromMessage({parts:[{content:{$case:'text',value:prose}}]},surface));
  const missing=approvalSurface({...record,meshToolCalls:new Map()},{callId:'call',toolName:'read_file'});
  assert.equal(missing.canApprove,false);assert.throws(()=>validateApproval({...decision,requestId:missing.requestId},missing));
  assert.equal(validateApproval({...decision,requestId:missing.requestId,decision:'reject'},missing),'rejected');
  const oversized=approvalSurface({...record,meshToolCalls:new Map([['call',{name:'read_file',arguments:'x'.repeat(16385)}]])},{callId:'call',toolName:'read_file'});
  assert.equal(oversized.canApprove,false);assert.equal(oversized.arguments,null);
});

test('candidate plugin HTTP lifecycle exposes exact approval and applies a once-only decision through real A2A SDK',async()=>{
  const {apply}=await import(pathToFileURL(resolve('data/dsh-approval-candidate/lib/index.js')));
  const routes=new Map();const events=new Map();let granted=0;let finalDecision;
  const ctx={logger:{error:()=>{}},get:name=>name==='webServer'?{register:route=>{routes.set(route.path,route.handler);return ()=>routes.delete(route.path);}}:undefined,
    effect:()=>{},on:(name,fn)=>events.set(name,fn),agents:{create:async({sessionId})=>{
      const session={id:sessionId,header:{id:sessionId}};let idleResolve;const idle=new Promise(resolve=>idleResolve=resolve);
      const agent={session,whenIdle:()=>idle,cancel:()=>idleResolve(),followup:()=>queueMicrotask(()=>{
        events.get('session/event')(session,{type:'tool/call',data:{callId:'call-one',name:'read_file',arguments:'{"path":"fixture.mjs"}'}});
        events.get('approval/request')({agent,callId:'call-one',toolName:'read_file',reason:'Read the review fixture'},async()=>{throw Error('Unexpected fallback');}).then(decision=>{
          finalDecision=decision;if(decision==='allowed-once')granted++;
          events.get('session/event')(session,{type:'assistant/message',data:{message:{content:[{type:'text',text:'Independent fixture review completed.'}]}}});
          events.get('session/event')(session,{type:'turn/end',data:{reason:{kind:'stop'}}});idleResolve();
        });
      })};return {agent,dispose:()=>{}};
    }}};
  await apply(ctx,{host:'127.0.0.1',port:0,cwd:process.cwd(),auth:{token:'fixture-token'}});
  const server=http.createServer((req,res)=>{const handler=routes.get(new URL(req.url,'http://local').pathname);if(!handler){res.writeHead(404);res.end();return;}Promise.resolve(handler(req,res)).catch(error=>{res.writeHead(500);res.end(JSON.stringify({error:error.message}));});});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const base='http://127.0.0.1:'+server.address().port;
  async function call(route,method='GET',body,authorized=true){const r=await fetch(base+route,{method,headers:{'Content-Type':'application/json',...(authorized?{Authorization:'Bearer fixture-token'}:{})},...(body?{body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(4000)});const text=await r.text();return {status:r.status,body:text?JSON.parse(text):null};}
  try{
    const first=await call('/a2a','POST',{jsonrpc:'2.0',id:'first',method:'SendMessage',params:{message:{messageId:'user-one',role:'ROLE_USER',contextId:'review-context',parts:[{text:'Workroom message work-send\nPhase: review\nWorkroom task work-task: Read the fixture'}]}}});
    assert.equal(first.status,200);assert.ok(!first.body.error,JSON.stringify(first.body));const task=first.body.result.task;
    assert.equal(task.status.state,'TASK_STATE_INPUT_REQUIRED');
    assert.equal((await call('/a2a/admin/approval?taskId='+task.id,'GET',undefined,false)).status,401);
    const inspection=await call('/a2a/admin/approval?taskId='+task.id);assert.equal(inspection.status,200,JSON.stringify(inspection.body));const pending=inspection.body.pending;
    assert.equal(pending.toolName,'read_file');assert.equal(pending.arguments,'{"path":"fixture.mjs"}');assert.equal(pending.canApprove,true);assert.equal(granted,0);
    const client=createDshApprovalClient({origin:base,token:'fixture-token'});const scope={id:'work-send',taskId:'work-task',conversationId:'review-context'};
    assert.equal((await client.inspect(scope)).pending.requestId,pending.requestId);
    assert.equal((await client.inspect({...scope,id:'other-send'})).pending,null);
    assert.equal((await call('/a2a/admin/approval','POST',{taskId:task.id,requestId:'stale',decision:'allow_once'})).status,409);assert.equal(granted,0);
    const body={taskId:task.id,requestId:pending.requestId,decision:'allow_once'};
    const pair=await Promise.all([call('/a2a/admin/approval','POST',body),call('/a2a/admin/approval','POST',body)]);
    const decision=pair.find(r=>r.status===200);assert.ok(decision,JSON.stringify(pair));assert.ok(pair.every(r=>[200,409].includes(r.status)));assert.equal(finalDecision,'allowed-once');assert.equal(granted,1);
    assert.equal((await call('/a2a/admin/approval','POST',body)).body.duplicate,true);assert.equal(granted,1);
    assert.equal((await call('/a2a/admin/approval','POST',{...body,decision:'reject'})).status,409);
    assert.equal((await call('/a2a/admin/approval?taskId='+task.id)).body.pending,null);
    assert.equal(decision.body.result.task.status.state,'TASK_STATE_COMPLETED');
  }finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
});
