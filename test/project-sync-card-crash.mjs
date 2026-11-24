// Owned disposable-process fixture only. Refuse paths outside its temp namespace.
import {resolve,dirname,basename} from 'node:path';
import {tmpdir} from 'node:os';
import {openTaskStore} from '../lib/task-store.mjs';
import {createWorkroomProjectSyncCandidate} from '../integrations/workroom-project-sync-candidate.mjs';

const [file,cardId,phase,edit]=process.argv.slice(2);
const folder=dirname(resolve(file));
if(dirname(folder)!==resolve(tmpdir())||!basename(folder).startsWith('mesh-sync-process-')||
  !['before_commit','after_commit'].includes(phase))throw Error('Owned fixture path and crash phase required.');
const store=openTaskStore(file,{projectSyncFactory:context=>{
  const controller=createWorkroomProjectSyncCandidate(context,{storeId:'synthetic-store'});
  return {capture:(...args)=>{controller.capture(...args);if(phase==='before_commit')process.exit(71);}};
}});
const card=store.get(cardId);
if(edit==='combined'){
  const t=store.workroom.get(cardId);
  store.workroom.save(cardId,{project:'Print',criteria:'Measure the tray',owner:'nims',team:'local_build',stage:'working',revision:t.workroom.revision},
    {goal:'Use a 95 mm tray',checklist:[],result:'',evidence:'',reviewer:'',decision:'pending',revision:t.progress.revision,taskRevision:t.revision,briefRevision:t.workroom.revision});
}else{
  store.update(cardId,{title:'Committed process update',description:card.description,label:card.label,status:'open',revision:card.revision});
}
process.exit(72);
