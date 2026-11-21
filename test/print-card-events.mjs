import {openTaskStore} from '../lib/task-store.mjs';
import {createWorkroomProjectSyncCandidate} from '../integrations/workroom-project-sync-candidate.mjs';

// Standalone producer for the Python cross-repository qualification.
let controller;
let database;
const store = openTaskStore(':memory:', {
  projectSyncFactory(context) {
    database = context.db;
    controller = createWorkroomProjectSyncCandidate(context, {storeId:'synthetic-store', initialize:true});
    return controller;
  }
});

try {
  const card = store.create({title:'Desk tray', description:'PRIVATE fixture description', owner:'nims'});
  function saveSpec(width, revision) {
    const task = store.workroom.get(card.id);
    store.workroom.saveProgress(card.id, {
      goal:`Tray width ${width} mm ±0.2 mm. CAD tray-v${revision}.step`,
      checklist:[], result:'', evidence:'PRIVATE free-form notes', reviewer:'', decision:'pending',
      revision:task.progress.revision, taskRevision:task.revision, briefRevision:task.workroom.revision
    });
  }
  saveSpec(90, 1);
  controller.link({cardId:card.id, projectId:'project-A', approvalRef:'fixture:owner-reviewed',
                   fields:['title','stage','goal']});
  saveSpec(95, 2);
  const rows = database.prepare('SELECT payload FROM mind_project_outbox WHERE cardId=? ORDER BY sequence').all(card.id);
  process.stdout.write(JSON.stringify(rows.map(row => JSON.parse(row.payload))));
} finally {
  store.close();
}
