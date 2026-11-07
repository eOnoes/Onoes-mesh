// Isolated SQLite/HTTP/browser fixture; no live agent/model connection.
import {mkdir} from 'node:fs/promises';import {randomUUID} from 'node:crypto';import {join} from 'node:path';
import {startApp,ROOT} from '../server.mjs';import {openTaskStore} from '../lib/task-store.mjs';
process.env.MESH_STANDALONE='1';
const dataDir='data/team-policy-browser-'+randomUUID();await mkdir(join(ROOT,dataDir),{recursive:true});
const store=openTaskStore(join(ROOT,dataDir,'tasks.sqlite'));
for(const outside of [false,true]){
 let t=store.create({title:outside?'Other folder - synthetic policy check':'Mesh folder - synthetic policy check',description:'Disposable UI test only; never start workers.',owner:'echo'});
 t=store.workroom.get(t.id);
 t=store.workroom.save(t.id,{project:'Synthetic scope display',criteria:'Inspect policy without dispatch',owner:'echo',team:'local_build',stage:'ready',revision:t.workroom.revision});
 t=store.workroom.saveProgress(t.id,{goal:'Show automatic team limits',checklist:[{id:'inspect',text:'Inspect displayed policy only',status:'pending'}],result:'',evidence:'',reviewer:'',decision:'pending',revision:t.progress.revision,taskRevision:t.revision,briefRevision:t.workroom.revision});
 store.workroom.savePlan(t.id,{lead:'echo',spec:'Read policy only',workspace:outside?ROOT+'-unqualified':ROOT,allowedFiles:'none',checks:'UI inspection only',boundaries:'No workers, models or edits',workerId:'echo',reviewerId:'nims',state:'locked',revision:0,taskRevision:t.revision,briefRevision:t.workroom.revision,progressRevision:t.progress.revision});
}
store.close();const app=await startApp({dataDir,relayEnabled:false});console.log(JSON.stringify({url:app.url+'/#workroom',pid:process.pid,dataDir}));
let stopping=false;async function stop(){if(stopping)return;stopping=true;await app.close();}process.on('SIGINT',()=>void stop());process.on('SIGTERM',()=>void stop());
