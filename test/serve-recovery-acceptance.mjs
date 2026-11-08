// Manual browser rehearsal only. Creates disposable data; never connects workers.
// Run from the Mesh checkout; stop with Ctrl+C. Do not use the live preview DB.
import {startApp,ROOT} from '../server.mjs';
import {openTaskStore} from '../lib/task-store.mjs';
import {randomUUID} from 'node:crypto';
import {mkdirSync,writeFileSync,existsSync} from 'node:fs';
import {join} from 'node:path';
process.env.MESH_STANDALONE='1';
const dataDir='data/recovery-browser-'+randomUUID(),directory=join(ROOT,dataDir);
mkdirSync(directory);const store=openTaskStore(join(directory,'tasks.sqlite')),cards=[];
for(const decision of ['approved','pending','stale']){
  let t=store.create({title:decision+' completion test',description:'Disposable recovery rehearsal. No agent work.'});t=store.workroom.get(t.id);
  t=store.workroom.save(t.id,{project:'Recovery rehearsal',criteria:'Synthetic acceptance',owner:'echo',team:'local_build',stage:'working',revision:t.workroom.revision});
  t=store.workroom.saveProgress(t.id,{goal:'Check recovery without real work',checklist:[{id:'verify',text:'Synthetic completed step',status:'done'}],result:'Synthetic result',evidence:'Synthetic evidence',reviewer:decision==='pending'?'':'fixture-reviewer',decision:decision==='pending'?'pending':'approved',revision:t.progress.revision,taskRevision:t.revision,briefRevision:t.workroom.revision});
  if(decision==='stale'){const {project,criteria,owner,team,stage,revision}=t.workroom;t=store.workroom.save(t.id,{project,criteria:criteria+' changed',owner,team,stage,revision});}
  cards.push({id:t.id,decision:t.progress.decision});
}
store.close();const expireFlag=join(directory,'expire-session.flag');
const app=await startApp({dataDir,relayEnabled:false,sessionNow:()=>Date.now()+(existsSync(expireFlag)?600000:0)});
const receipt={url:app.url+'/#workroom',dataDir,directory,cards,expireFlag,pid:process.pid};
writeFileSync(join(directory,'browser-fixture.json'),JSON.stringify(receipt,null,2));console.log(JSON.stringify(receipt,null,2));
process.on('SIGINT',async()=>{await app.close();process.exit(0);});
