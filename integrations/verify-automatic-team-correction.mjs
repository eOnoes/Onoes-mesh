import {readFileSync,writeFileSync} from 'node:fs';
import {join,relative} from 'node:path';
import {openTaskStore} from '../lib/task-store.mjs';
import {createRelayHttpLink} from '../lib/relay-http.mjs';
import {withNims} from '../lib/nims-link.mjs';
import {createTeamRunner} from '../lib/workroom-automation.mjs';
const prior=JSON.parse(readFileSync('../mesh-automatic-team-qualification.json','utf8'));
const id=prior.artifact.split('automatic-team-artifact-')[1],directory='data/automatic-team-live-'+id;
const store=openTaskStore(join(directory,'tasks.sqlite'));
const base=await createRelayHttpLink({baseUrl:'http://127.0.0.1:8787',tokenFile:'D:/Dev/Onoes-Relay/.private/relay.key'}),relay=withNims(base,{root:process.cwd(),workroom:store.workroom}),runner=createTeamRunner({workroom:store.workroom,relay,root:process.cwd()});
const action=(t,kind)=>({action:kind,revision:t.automation.revision,planRevision:t.plan.revision,taskRevision:t.revision,briefRevision:t.workroom.revision,progressRevision:t.progress.revision});
try{
 const agents=await relay.agents();if(!['idle','done','stopped'].includes(agents.find(a=>a.id==='echo')?.status))throw Error('Echo busy; no correction sent.');
 let t=store.workroom.get(prior.taskId);if(t.automation.state!=='paused')throw Error('Expected paused original attempt.');
 writeFileSync('../mesh-automatic-team-first-attempt.json',JSON.stringify(prior,null,2));const report=t.agentUpdates.at(-1);
 t=store.workroom.applyAgentUpdate(t.id,{sendId:report.sendId,messageId:report.messageId,hash:report.hash,revision:t.progress.revision,taskRevision:t.revision,briefRevision:t.workroom.revision}).task;
 t=store.workroom.automation.action(t.id,action(t,'close'),[],process.cwd()).task;
 const description=t.description+'\nControlled correction: Nims independently reran your 7 tests and all passed. Your prior report marked the worker test step blocked despite reporting 7 PASS. Inspect and rerun those same two existing files; do not modify them unless you find an actual defect. Return the same goal and exact checklist IDs/wording with truthful statuses. The verify step is YOUR local test run; independent reviewer work happens later and must not block that step. If the tests pass, the worker steps are done while overall review remains pending. No other paths or agents.';
 store.update(t.id,{title:t.title,description,label:t.label,status:'open',revision:t.revision});t=store.workroom.get(t.id);
 t=store.workroom.saveProgress(t.id,{goal:t.progress.goal,checklist:t.progress.checklist.map(s=>({...s,status:'pending'})),result:'',evidence:'',reviewer:'',decision:'pending',revision:t.progress.revision,taskRevision:t.revision,briefRevision:t.workroom.revision});
 const {spec,workspace,allowedFiles,checks,boundaries,workerId,reviewerId,lead}=t.plan;
 t=store.workroom.savePlan(t.id,{spec,workspace,allowedFiles,checks,boundaries,workerId,reviewerId,lead,state:'locked',revision:t.plan.revision,taskRevision:t.revision,briefRevision:t.workroom.revision,progressRevision:t.progress.revision}).task;
 runner.action(t.id,action(t,'start'),agents);let last='';const deadline=Date.now()+12*60*1000;
 while(Date.now()<deadline){t=store.workroom.get(t.id);const status=t.automation.state+'/'+t.automation.phase;if(status!==last){console.log(JSON.stringify({at:new Date().toISOString(),status,reason:t.automation.reason}));last=status;}if(t.automation.state!=='active')break;await new Promise(r=>setTimeout(r,1000));}
 t=store.workroom.get(t.id);const receipt={at:new Date().toISOString(),taskId:t.id,artifact:prior.artifact,status:t.automation.state,automation:t.automation,review:t.agentReviews.at(-1)?.review,reviewApplied:t.agentReviews.at(-1)?.applied??false,decision:t.progress.decision,native:t.messages.findLast(m=>m.agentId==='nims')?.nims,sends:t.messages.map(m=>({id:m.id,agentId:m.agentId,phase:m.phase,state:m.state})),firstAttempt:'Preserved as blocked worker report; independently reran7 PASS; explicitly closed before bounded correction.'};writeFileSync('../mesh-automatic-team-qualification.json',JSON.stringify(receipt,null,2));writeFileSync(join(directory,'final-task.json'),JSON.stringify(t,null,2));console.log(JSON.stringify(receipt,null,2));if(t.automation.state!=='needs_review')throw Error('Qualification paused: '+t.automation.reason);
}finally{await runner.close();await relay.close();store.close();}
