// Exercise the installed request-admission prefix with disposable collaborators only.
// No plugin import, HTTP listener, credentials, native agent or real task is used.
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { createHash } from 'node:crypto';

const sourcePath=resolve(homedir(),'.dsh/profiles/a2a/node_modules/dsh-a2a-server/lib/index.js');
const bytes=readFileSync(sourcePath),source=bytes.toString('utf8');
const start=source.indexOf('const handleHttp = async (req, res) => {');
const end=source.indexOf('const result = await jsonRpc.handle(requestBody, context);',start);
assert.ok(start>=0 && end>start,'Installed admission prefix changed; review before qualifying.');
const prefix=source.slice(start,end+'const result = await jsonRpc.handle(requestBody, context);'.length);
const enabled=source.slice(source.lastIndexOf('async function apply(',start),start).match(/let enabled = (true|false);/);
assert.ok(enabled,'Installed initial admission state not found.');
const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
const factory=new AsyncFunction('deps',`const {records,readBody,jsonRpc,approvalHttp,sendJson,config,metrics,ServerCallContext}=deps;
const path='/a2a',adminPath='/a2a/admin',agentCardPath='/.well-known/agent.json',authToken='fixture-only',meshApprovalReceipts=new Map();
let enabled=${enabled[1]};
${prefix}
return result;
}
}; return handleHttp;`);
const checks={};
async function fixture(readBody=async()=>'{"fixture":true}') {
  const records=new Map([['existing-fixture-task',{state:'running'}]]),calls={dispatch:0,approval:0,body:0};
  const handle=await factory({records,readBody:async(...args)=>{calls.body++;return readBody(...args);},
    jsonRpc:{handle:async()=>{calls.dispatch++;return {fixtureOnly:true};}},
    approvalHttp:async(_req,res)=>{calls.approval++;res.end('{}');},sendJson:(res,value)=>{res.end(JSON.stringify(value));},
    config:{},metrics:{requests:0},ServerCallContext:class {}});
  const request=async(url,method='POST',authorized=true)=>{
    const response={status:200,body:'',writeHead(code){this.status=code;},end(body){this.body=body;}};
    await handle({url,method,headers:authorized?{authorization:'Bearer fixture-only'}:{}},response);
    return response;
  };
  return {request,records,calls};
}
const f=await fixture();
assert.equal((await f.request('/a2a/admin/disable','POST',false)).status,401);
assert.equal(JSON.parse((await f.request('/a2a/admin/status','GET')).body).enabled,true);
checks.unauthorizedDisableRefused=true;
assert.equal(JSON.parse((await f.request('/a2a/admin/disable')).body).enabled,false);
assert.equal((await f.request('/a2a')).status,503);
assert.equal(f.calls.body,0);assert.equal(f.calls.dispatch,0);
checks.disabledNewA2ARefusedBeforeBody=true;
const state=JSON.parse((await f.request('/a2a/admin/status','GET')).body);
assert.equal(state.enabled,false);assert.equal(state.activeTasks,1);assert.equal(f.records.size,1);
checks.statusReadableExistingTaskNotRetired=true;
await f.request('/a2a/admin/approval');assert.equal(f.calls.approval,1);
checks.approvalRouteDelegatesOutsideDisableGate=true;
let finishBody,arrive;
const arrived=new Promise(resolve=>{arrive=resolve;});
const racing=await fixture(()=>{arrive();return new Promise(resolve=>{finishBody=resolve;});});
const original=racing.request('/a2a');await arrived;
await racing.request('/a2a/admin/disable');assert.equal(racing.calls.dispatch,0);
finishBody('{"fixture":true}');await original;assert.equal(racing.calls.dispatch,1);
checks.requestAdmittedBeforeDisableCanDispatchAfterDisable=true;
const restarted=await fixture();
assert.equal(JSON.parse((await restarted.request('/a2a/admin/status','GET')).body).enabled,true);
checks.newHandlerStartsEnabledWithoutPersistedPause=true;
assert.equal(createHash('sha256').update(readFileSync(sourcePath)).digest('hex'),createHash('sha256').update(bytes).digest('hex'));
checks.installedSourceUnchanged=true;
const result={observedAt:new Date().toISOString(),sourcePath,sourceSha256:createHash('sha256').update(bytes).digest('hex'),checks,
 boundary:'Actual installed handleHttp admission prefix only; all collaborators and records synthetic. No full-plugin/native/runtime acceptance. Approval delegation is proven, not the downstream approval authorization or execution.',
 conclusion:'Admin disable refuses future A2A requests, but is not a durable, drained, whole-native maintenance fence. Existing work, already-admitted body reads, approval delegation and direct UI need separate exclusion.'};
const output=resolve(process.argv[2]||`data/dsh-admission-control-${Date.now()}.json`);
writeFileSync(output,JSON.stringify(result,null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify({output,...result}));
