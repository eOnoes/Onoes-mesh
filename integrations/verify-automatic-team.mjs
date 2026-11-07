import {mkdirSync,writeFileSync} from 'node:fs';
import {randomUUID} from 'node:crypto';
import {resolve,join} from 'node:path';
import {openTaskStore} from '../lib/task-store.mjs';
import {createRelayHttpLink} from '../lib/relay-http.mjs';
import {withNims} from '../lib/nims-link.mjs';
import {createTeamRunner} from '../lib/workroom-automation.mjs';
const id=randomUUID(),directory='data/automatic-team-live-'+id,artifact='data/automatic-team-artifact-'+id;mkdirSync(directory);mkdirSync(artifact);
const store=openTaskStore(join(directory,'tasks.sqlite'));
const base=await createRelayHttpLink({baseUrl:'http://127.0.0.1:8787',tokenFile:'D:/Dev/Onoes-Relay/.private/relay.key'});
const relay=withNims(base,{root:process.cwd(),workroom:store.workroom});const runner=createTeamRunner({workroom:store.workroom,relay,root:process.cwd()});
let task;const receipt={at:new Date().toISOString(),scope:'isolated real Echo build → read-only Nims independent review; no owner data or app source edits',artifact:resolve(artifact)};
try{
 const agents=await relay.agents();const echo=agents.find(a=>a.id==='echo');if(!echo||!['idle','done','stopped'].includes(echo.status))throw Error('Echo is busy/unavailable; no job sent.');if(!agents.some(a=>a.id==='nims'&&a.conversation_id))throw Error('Nims unavailable; no job sent.');
 const allowed=[resolve(artifact,'labels.mjs'),resolve(artifact,'labels.test.mjs')];
 const brief='Qualification fixture only. You may create/edit ONLY '+allowed.join(' and ')+'. No app source, other user data, network, purchases, model operations, git, service changes or other agents. Implement exported function summarizeLabels(items): accepts an array of strings, trims values, drops empty strings, returns distinct strings sorted with ordinary JS .sort(); case-sensitive. Throw TypeError for non-array input or any non-string item. Add meaningful Node tests for normal/dedup/trim/empty/invalid cases. Run node --test on the named test file. Preserve checklist IDs/goal when reporting. Independent reviewer: read both exact files, run their tests plus independent checks, read-only only; report actual verdict, do not approve based on worker claims. Do not edit or dispatch anything.';
 task=store.create({title:'Automatic team qualification — scoped labels helper',description:brief,owner:'echo'});task=store.workroom.get(task.id);
 task=store.workroom.save(task.id,{project:'Mesh automatic team acceptance',criteria:'Correct exact function contract; meaningful tests and independent read-only review; only two scoped fixture files changed.',owner:'echo',team:'local_build',stage:'ready',revision:task.workroom.revision});
 task=store.workroom.saveProgress(task.id,{goal:'Build and independently verify one scoped labels helper',checklist:[{id:'implement',text:'Implement the exact helper contract',status:'pending'},{id:'verify',text:'Add and run meaningful local tests',status:'pending'},{id:'report',text:'Report exact scoped artifacts and actual evidence',status:'pending'}],result:'',evidence:'',reviewer:'',decision:'pending',revision:0,taskRevision:task.revision,briefRevision:task.workroom.revision});
 task=store.workroom.savePlan(task.id,{lead:'echo',spec:'Implement the exact labels helper contract in the task brief',workspace:process.cwd(),allowedFiles:allowed.join('\n'),checks:'node --test '+JSON.stringify(allowed[1]),boundaries:'Only the two named fixture files. No real app edits, network, money, models, git, service changes or worker spawning.',workerId:'echo',reviewerId:'nims',state:'locked',revision:0,taskRevision:task.revision,briefRevision:task.workroom.revision,progressRevision:task.progress.revision}).task;
 runner.action(task.id,{action:'start',revision:0,planRevision:task.plan.revision,taskRevision:task.revision,briefRevision:task.workroom.revision,progressRevision:task.progress.revision},agents);
 receipt.taskId=task.id;receipt.status='running';writeFileSync('../mesh-automatic-team-qualification.json',JSON.stringify(receipt,null,2));
 let last='';const deadline=Date.now()+12*60*1000;
 while(Date.now()<deadline){task=store.workroom.get(task.id);const current=task.automation.state+'/'+task.automation.phase;if(current!==last){console.log(JSON.stringify({at:new Date().toISOString(),state:current,reason:task.automation.reason}));last=current;}if(task.automation.state!=='active')break;await new Promise(r=>setTimeout(r,1000));}
 task=store.workroom.get(task.id);receipt.automation=task.automation;receipt.status=task.automation.state==='needs_review'?'REVIEW_RECEIVED':task.automation.state;receipt.decision=task.progress.decision;receipt.review=task.agentReviews.at(-1)?.review;receipt.reviewApplied=task.agentReviews.at(-1)?.applied??false;receipt.native=task.messages.find(m=>m.agentId==='nims')?.nims;receipt.sends=task.messages.map(m=>({id:m.id,agentId:m.agentId,phase:m.phase,state:m.state}));
 writeFileSync('../mesh-automatic-team-qualification.json',JSON.stringify(receipt,null,2));writeFileSync(join(directory,'final-task.json'),JSON.stringify(task,null,2));console.log(JSON.stringify(receipt,null,2));
 if(task.automation.state!=='needs_review')throw Error('Real team stopped before independent review: '+task.automation.reason);
}finally{await runner.close();await relay.close();store.close();}
