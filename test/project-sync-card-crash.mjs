// Owned disposable-process fixture only. Refuse paths outside its temp namespace.
import {resolve,dirname,basename} from 'node:path';
import {tmpdir} from 'node:os';
import {openTaskStore} from '../lib/task-store.mjs';
import {createWorkroomProjectSyncCandidate} from '../integrations/workroom-project-sync-candidate.mjs';

const [file,cardId,phase]=process.argv.slice(2);
const folder=dirname(resolve(file));
if(dirname(folder)!==resolve(tmpdir())||!basename(folder).startsWith('mesh-sync-process-')||
  !['before_commit','after_commit'].includes(phase))throw Error('Owned fixture path and crash phase required.');
const store=openTaskStore(file,{projectSyncFactory:context=>{
  const controller=createWorkroomProjectSyncCandidate(context,{storeId:'synthetic-store'});
  return {capture:(...args)=>{controller.capture(...args);if(phase==='before_commit')process.exit(71);}};
}});
const card=store.get(cardId);
store.update(cardId,{title:'Committed process update',description:card.description,label:card.label,status:'open',revision:card.revision});
process.exit(72);
