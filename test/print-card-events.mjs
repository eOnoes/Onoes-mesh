import {openTaskStore} from '../lib/task-store.mjs';
import {mkdirSync} from 'node:fs';
import {createWorkroomProjectSyncCandidate} from '../integrations/workroom-project-sync-candidate.mjs';

// Standalone producer for the Python cross-repository qualification.
let controller;
let database;
const filename = process.argv[2] === '--keep-fixture' ? 'print-board/tasks.sqlite' : ':memory:';
if (filename !== ':memory:') mkdirSync('print-board');
const store = openTaskStore(filename, {
  projectSyncFactory(context) {
    database = context.db;
    controller = createWorkroomProjectSyncCandidate(context, {storeId:'synthetic-store', initialize:true});
    return controller;
  }
});

try {
  const card = store.create({title:'Desk tray', description:'PRIVATE fixture description', owner:'nims'});
  if (filename !== ':memory:') {
    store.workroom.save(card.id, {project:'Print fixture', criteria:'Check the revised tray tolerance',
      owner:'echo', team:'local_build', stage:'ready', revision:store.workroom.get(card.id).workroom.revision});
  }
  function saveSpec(width, revision) {
    const task = store.workroom.get(card.id);
    store.workroom.saveProgress(card.id, {
      goal:`Tray width ${width} mm${revision === 2 && process.argv.includes('--missing-tolerance') ? '' : ' ±0.2 mm'}. CAD tray-v${revision}.step`,
      checklist:[{id:'fit', text:'Calculate the tray width range', status:'pending'}],
      result:'', evidence:'PRIVATE free-form notes', reviewer:'', decision:'pending',
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
