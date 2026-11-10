export const WORKER_INSTRUCTION='Preserve the saved goal and checklist IDs, wording and order exactly; update their statuses plus result/evidence only. The worker verification step means your named local tests, not the later independent review. If scope needs revision, report blocked instead of silently changing it. Implement only the saved task in the explicitly named workspace/files. Follow repository instructions. Do not purchase, publish, push, change credentials, delete existing data or start other agents. Run the stated local checks. Return changed paths, actual outcomes and verification evidence in the structured update. If access or scope is missing, report blocked; never invent completion.';
import { createHash } from 'node:crypto';
import {createFlowStore} from './workroom-flow.mjs';
import {createRookStore} from './workroom-rook.mjs';
import {resolve as canonicalPath} from 'node:path';
const canonicalWorkspace=value=>canonicalPath(value).toLowerCase();
import { TaskError } from './task-store.mjs';
import {parseAgentUpdate,agentUpdateInstruction,parseAgentReview,agentReviewInstruction} from './workroom-updates.mjs';
import {leadPlanningInstruction} from '../public/lead-policy.mjs';
import {parseAssignment,assignmentInstruction} from './workroom-assignment.mjs';
import {createAutomationStore} from './workroom-automation-store.mjs';
import {createNimsStore} from './nims-store.mjs';
import {createNativeReceiptStore} from './workroom-native-receipts.mjs';
import {createLocalSessionStore,localSessionProfile} from './workroom-local-sessions.mjs';
import {writerQuiescenceBlockers} from './workroom-claim-policy.mjs';
import {initializePlans,readPlan,savePlan,assertPlanDispatch,planBrief} from './workroom-plan.mjs';

export const STAGES = ['backlog', 'ready', 'working', 'needs_you', 'done'];
const identifier = value => typeof value === 'string' && /^[A-Za-z0-9_-]{1,100}$/.test(value);
const text = (value, max) => typeof value === 'string' && value.length <= max && !value.includes('\0');
export function createWorkroom(db, store) {
  initializePlans(db);
  // Separate additive schema: existing task/proposal records keep their contract.
  db.exec(`BEGIN IMMEDIATE;
    CREATE TABLE IF NOT EXISTS workroom_tasks (
      taskId TEXT PRIMARY KEY REFERENCES tasks(id), project TEXT NOT NULL,
      criteria TEXT NOT NULL, owner TEXT NOT NULL, team TEXT NOT NULL,
      stage TEXT NOT NULL, revision INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS workroom_events (
      seq INTEGER PRIMARY KEY, taskId TEXT NOT NULL REFERENCES tasks(id),
      kind TEXT NOT NULL, detail TEXT NOT NULL, at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS workroom_replies (
      taskId TEXT NOT NULL REFERENCES tasks(id), sendId TEXT NOT NULL,
      messageId TEXT NOT NULL, agentId TEXT NOT NULL, text TEXT NOT NULL,
      at TEXT NOT NULL, PRIMARY KEY(taskId,sendId,messageId));
    CREATE TABLE IF NOT EXISTS workroom_update_applications (
      taskId TEXT NOT NULL REFERENCES tasks(id),sendId TEXT NOT NULL,messageId TEXT NOT NULL,
      hash TEXT NOT NULL,PRIMARY KEY(taskId,sendId,messageId,hash));
    CREATE TABLE IF NOT EXISTS workroom_progress (
      taskId TEXT PRIMARY KEY REFERENCES tasks(id), goal TEXT NOT NULL,
      checklist TEXT NOT NULL, result TEXT NOT NULL, evidence TEXT NOT NULL,
      reviewer TEXT NOT NULL, decision TEXT NOT NULL, revision INTEGER NOT NULL,
      reviewFingerprint TEXT NOT NULL, reviewedAt TEXT);
    CREATE TABLE IF NOT EXISTS workroom_sends (
      id TEXT PRIMARY KEY, taskId TEXT NOT NULL REFERENCES tasks(id),
      agentId TEXT NOT NULL, conversationId TEXT NOT NULL, text TEXT NOT NULL,
      fingerprint TEXT NOT NULL, state TEXT NOT NULL, at TEXT NOT NULL,
      payload TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS workroom_send_outcomes (
      sendId TEXT PRIMARY KEY REFERENCES workroom_sends(id),taskId TEXT NOT NULL REFERENCES tasks(id),
      peerTaskId TEXT NOT NULL,state TEXT NOT NULL,proofHash TEXT NOT NULL,verifiedAt TEXT NOT NULL);
    COMMIT;`);
  // Upgrade only this additive schema, without changing the existing task schema.
  if(!db.prepare('PRAGMA table_info(workroom_sends)').all().some(column=>column.name==='payload')) {
    db.exec("ALTER TABLE workroom_sends ADD COLUMN payload TEXT NOT NULL DEFAULT ''; UPDATE workroom_sends SET payload=text;");
  }
  if(!db.prepare('PRAGMA table_info(workroom_sends)').all().some(column=>column.name==='basis'))db.exec("ALTER TABLE workroom_sends ADD COLUMN basis TEXT NOT NULL DEFAULT '';");
  if(!db.prepare('PRAGMA table_info(workroom_sends)').all().some(column=>column.name==='phase'))db.exec("ALTER TABLE workroom_sends ADD COLUMN phase TEXT NOT NULL DEFAULT 'message';");
  db.prepare("UPDATE workroom_sends SET state='unknown' WHERE state='prepared'").run();
  const nims=createNimsStore(db);
  const localSessions=createLocalSessionStore(db,get,reserve);
  const nativeReceipts=createNativeReceiptStore(db,(taskId,sendId)=>Boolean(localSessions.read(taskId,sendId)));
  const automation=createAutomationStore(db,get);
  const flow=createFlowStore(db,get,()=>store.list().map(task=>get(task.id)),assignClaimLead);
  const rook=createRookStore(db);
  function assignClaimLead(task,lead) {
    if(!db.isTransaction||task.workroom.owner||lead!=='nims')throw new TaskError(409,'Invalid atomic lead assignment.');
    const brief=task.workroom;
    const changed=db.prepare(`INSERT INTO workroom_tasks(taskId,project,criteria,owner,team,stage,revision) VALUES(?,?,?,?,?,?,?)
      ON CONFLICT(taskId) DO UPDATE SET owner=excluded.owner,revision=excluded.revision
      WHERE workroom_tasks.owner='' AND workroom_tasks.revision=?`)
      .run(task.id,brief.project,brief.criteria,lead,brief.team,brief.stage,brief.revision+1,brief.revision);
    if(changed.changes!==1)throw new TaskError(409,'Card changed before lead assignment.');
    event(task.id,'lead_assigned','Nims assigned as intake lead with the saved claim.');
    return get(task.id);
  }
  function event(taskId, kind, detail) {
    db.prepare('INSERT INTO workroom_events(taskId,kind,detail,at) VALUES(?,?,?,?)')
      .run(taskId, kind, detail, new Date().toISOString());
  }
  function get(id) {
    const task = store.get(id);
    if (!task) throw new TaskError(404, 'Task not found.');
    const meta = db.prepare('SELECT * FROM workroom_tasks WHERE taskId=?').get(id);
    const saved = meta ? {...meta,stage:task.status==='done'?'done':meta.stage==='done'?'backlog':meta.stage} : {project:'', criteria:'', owner:'', team:'local_build', stage:task.status === 'done' ? 'done' : 'backlog', revision:0};
    const progress=readProgress(id);
    const plan=readPlan(db,{...task,workroom:saved,progress});
    if(progress.decision==='approved' && progress.reviewFingerprint!==briefFingerprint(task,saved))progress.decision='stale';
    if(saved.stage==='done' && progress.decision!=='approved')saved.stage='needs_you';
    const replies=db.prepare('SELECT sendId,messageId,agentId,text,at FROM workroom_replies WHERE taskId=? ORDER BY at,messageId').all(id);
    const outcomes=new Map(db.prepare('SELECT sendId,peerTaskId,state,proofHash,verifiedAt FROM workroom_send_outcomes WHERE taskId=?').all(id).map(row=>[row.sendId,row]));
    const agentUpdates=replies.flatMap(reply=>{
      // Only the exact durable native result may omit the Markdown wrapper.
      // Ordinary Relay replies retain the explicit fenced-report contract.
      const local=localSessions.read(id,reply.sendId);
      const allowUnfenced=reply.agentId==='echo' && Boolean(local?.resultMessageId) && local.resultMessageId===reply.messageId;
      const parsed=parseAgentUpdate(reply.text,{taskId:id,sendId:reply.sendId,allowUnfenced});
      if(!parsed)return [];
      const applied=Boolean(db.prepare('SELECT hash FROM workroom_update_applications WHERE taskId=? AND sendId=? AND hash=?').get(id,reply.sendId,parsed.hash));
      const phase=db.prepare('SELECT phase FROM workroom_sends WHERE id=?').get(reply.sendId)?.phase;
      return [{sendId:reply.sendId,messageId:reply.messageId,agentId:reply.agentId,at:reply.at,phase,...parsed,applied}];
    });
    const content=value=>JSON.stringify([value.goal,value.checklist,value.result,value.evidence]);
    const worker=agentUpdates.filter(update=>{
      if(outcomes.has(update.sendId) && outcomes.get(update.sendId).state!=='TASK_STATE_COMPLETED')return false;
      if(!update.applied || update.phase!=='work' || content(update.update)!==content(progress))return false;
      let basis;try{basis=JSON.parse(db.prepare('SELECT basis FROM workroom_sends WHERE id=?').get(update.sendId)?.basis);}catch{return false;}
      return (!plan||(plan.state==='locked'&&basis?.planRevision===plan.revision)) && basis?.taskRevision===task.revision && basis?.briefFingerprint===briefFingerprint(task,saved);
    }).at(-1)||null;
    const agentReviews=replies.flatMap(reply=>{
      const send=db.prepare('SELECT phase,basis FROM workroom_sends WHERE id=?').get(reply.sendId);
      if(send?.phase!=='review')return [];
      const parsed=parseAgentReview(reply.text,{taskId:id,sendId:reply.sendId});if(!parsed)return [];
      const applied=Boolean(db.prepare('SELECT hash FROM workroom_update_applications WHERE taskId=? AND sendId=? AND hash=?').get(id,reply.sendId,parsed.hash));
      return [{sendId:reply.sendId,messageId:reply.messageId,agentId:reply.agentId,at:reply.at,...parsed,applied}];
    });
    const assignments=replies.flatMap(reply=>{const send=db.prepare("SELECT phase,state FROM workroom_sends WHERE id=? AND taskId=?").get(reply.sendId,id);if(send?.phase!=='plan'||send.state!=='accepted')return [];const parsed=parseAssignment(reply.text,id,reply.sendId);return parsed?[{sendId:reply.sendId,messageId:reply.messageId,agentId:reply.agentId,...parsed}]:[];});
    const result={...task,...(assignments.length?{assignments}:{}), workroom: saved, progress,agentUpdates,worker,agentReviews,
      history: db.prepare('SELECT seq,kind,detail,at FROM workroom_events WHERE taskId=? ORDER BY seq').all(id),
      messages: db.prepare('SELECT id,agentId,conversationId,text,state,at,phase FROM workroom_sends WHERE taskId=? ORDER BY at,id').all(id).map(message=>{const native=message.agentId==='nims'?nims.get(message.id):null;const receipt=nativeReceipts.read(id,message.id),local=localSessions.read(id,message.id);return {...message,...(local?{nativeLocal:local}:{}),outcome:outcomes.get(message.id)||null,...(receipt?{nativeReceipt:receipt}:{}),...(native?{nims:{state:native.state,threadId:native.threadId,turnId:native.turnId,finishedAt:native.finishedAt}}:{})};}),
      replies};
    const team=automation.read(id),flowState=flow.read(id);return {...result,...(plan?{plan}:{}),...(team?{automation:team}:{}),...(flowState?{flow:{...flowState,ownerDecision:flowState.progressRevision===progress.revision?flowState.ownerDecision:'pending'}}:{})};
  }
  function readProgress(id) {
    const row=db.prepare('SELECT * FROM workroom_progress WHERE taskId=?').get(id);
    return row?{...row,checklist:JSON.parse(row.checklist)}:{goal:'',checklist:[],result:'',evidence:'',reviewer:'',decision:'pending',revision:0,reviewFingerprint:'',reviewedAt:null};
  }
  function briefFingerprint(task,meta) {
    return createHash('sha256').update(JSON.stringify([task.title,task.description,meta.project,meta.criteria,meta.owner,meta.team])).digest('hex');
  }
  function assertCanComplete(id) {
    const task=get(id);
    if(task.plan&&task.plan.state!=='locked')throw new TaskError(409,'Lock the current scope before completing this task.');
    if(task.progress.decision!=='approved')throw new TaskError(409,'Record an approved review of the current task and result before marking it done.');
  }
  const isEnrolled=id=>Boolean(db.prepare('SELECT taskId FROM workroom_tasks WHERE taskId=? UNION SELECT taskId FROM workroom_progress WHERE taskId=?').get(id,id));
  function saveProgress(id,body,source=null,ownerFeedback=null) {
    const task=get(id);
    const keys=['goal','checklist','result','evidence','reviewer','decision','revision','taskRevision','briefRevision'];
    if(!body || Object.keys(body).sort().join(',')!==keys.sort().join(',') ||
       !text(body.goal,2000) || !Array.isArray(body.checklist) || body.checklist.length>30 ||
       !text(body.result,4000) || !text(body.evidence,4000) || !text(body.reviewer,100) ||
       !['pending','approved','changes_requested'].includes(body.decision) ||
       !Number.isSafeInteger(body.revision) || body.revision<0)throw new TaskError(400,'Invalid goal, checklist or review.');
    const ids=new Set();
    for(const step of body.checklist){
      if(!step || Object.keys(step).sort().join(',')!=='id,status,text' || !identifier(step.id) || ids.has(step.id) ||
         !text(step.text,300) || !step.text.trim() || !['pending','working','done','blocked'].includes(step.status))throw new TaskError(400,'Each checklist step needs unique identity, text and a valid status.');
      ids.add(step.id);
    }
    db.exec('BEGIN IMMEDIATE;');
    try{
      const latest=get(id);
      if(ownerFeedback&&((latest.flow?.revision??0)!==ownerFeedback.revision||latest.workroom.stage!=='done'||latest.progress.decision!=='approved'))throw new TaskError(409,'Completed result changed. Reopen it before reviewing.');
      if(latest.progress.revision!==body.revision || latest.revision!==body.taskRevision || latest.workroom.revision!==body.briefRevision)throw new TaskError(409,'Task changed. Reload before recording progress or review.');
      if(body.decision==='approved'&&latest.plan&&latest.plan.state!=='locked')throw new TaskError(409,'Lock the current scope before recording approval.');
      if(body.decision==='approved' && (!body.goal.trim() || !body.checklist.length || body.checklist.some(step=>step.status!=='done') ||
          !body.result.trim() || !body.evidence.trim() || !body.reviewer.trim()))throw new TaskError(400,'Approval needs a goal, completed checklist, result, verification evidence and reviewer.');
      const approved=body.decision==='approved';
      db.prepare(`INSERT INTO workroom_progress VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(taskId) DO UPDATE SET
        goal=excluded.goal,checklist=excluded.checklist,result=excluded.result,evidence=excluded.evidence,reviewer=excluded.reviewer,
        decision=excluded.decision,revision=excluded.revision,reviewFingerprint=excluded.reviewFingerprint,reviewedAt=excluded.reviewedAt`)
        .run(id,body.goal,JSON.stringify(body.checklist),body.result,body.evidence,body.reviewer,body.decision,body.revision+1,
          approved?briefFingerprint(latest,latest.workroom):'',approved?new Date().toISOString():null);
      if(!approved && latest.status==='done')store.update(id,{title:latest.title,description:latest.description,label:latest.label,status:'open',revision:latest.revision});
      if(body.decision==='changes_requested' || (!approved && latest.status==='done')) {
        if(db.prepare('SELECT taskId FROM workroom_tasks WHERE taskId=?').get(id))db.prepare("UPDATE workroom_tasks SET stage='needs_you',revision=revision+1 WHERE taskId=?").run(id);
      }
      event(id,ownerFeedback?'owner_review_saved':approved?'review_approved':body.decision==='changes_requested'?'review_changes_requested':'progress_saved',
        approved?`Review recorded by ${body.reviewer}. Evidence: ${body.evidence}`:`Progress recorded: ${body.checklist.filter(step=>step.status==='done').length}/${body.checklist.length} steps done. Review: ${body.decision}.`);
      if(source){
        db.prepare('INSERT INTO workroom_update_applications VALUES(?,?,?,?)').run(id,source.sendId,source.messageId,source.hash);
        event(id,source.review?'agent_review_recorded':'agent_update_applied',`${source.review?'Review':'Unreviewed update'} from ${source.agentId} recorded; message ${source.sendId}/${source.messageId}.`);
      }
      if(ownerFeedback)flow.feedback(id,ownerFeedback,body.revision+1);
      if(process.env.MESH_SIMPLE_FLOW==='1'&&!source&&flow.read(id)?.state==='clarification')flow.enqueue(id);
      if(ownerFeedback?.decision==='changes_requested'&&process.env.MESH_SIMPLE_FLOW==='1')flow.enqueue(id);
      db.exec('COMMIT;');
    }catch(error){db.exec('ROLLBACK;');throw error;}
    return get(id);
  }
  function ownerReview(id,body){
    if(!body||Object.keys(body).sort().join(',')!=='briefRevision,decision,note,progressRevision,revision,taskRevision'||!['accepted','changes_requested'].includes(body.decision)||!text(body.note,2000)||(body.decision==='changes_requested'&&!body.note.trim())||!Number.isSafeInteger(body.revision)||body.revision<0)throw new TaskError(400,'Choose accept or explain the requested changes.');
    const t=get(id),p=t.progress;
    return {task:saveProgress(id,{goal:p.goal,checklist:p.checklist,result:p.result,evidence:p.evidence,reviewer:p.reviewer,decision:body.decision==='accepted'?'approved':'changes_requested',revision:body.progressRevision,taskRevision:body.taskRevision,briefRevision:body.briefRevision},null,body)};
  }
  function save(id, body) {
    const before=get(id);
    if(process.env.MESH_SIMPLE_FLOW==='1'&&body?.stage==='working'&&!body.owner)body={...body,owner:'nims'};
    if (!body || Object.keys(body).sort().join(',') !== 'criteria,owner,project,revision,stage,team' ||
        !text(body.project,160) || !text(body.criteria,4000) || !text(body.owner,100) ||
        (body.owner && !identifier(body.owner)) || body.team !== 'local_build' || !STAGES.includes(body.stage) ||
        !Number.isSafeInteger(body.revision) || body.revision < 0) throw new TaskError(400,'Invalid Workroom fields.');
    db.exec('BEGIN IMMEDIATE;');
    try {
      const current = get(id).workroom;
      if (current.revision !== body.revision) throw new TaskError(409,'Task changed. Reload before saving.');
      if(process.env.MESH_SIMPLE_FLOW==='1'&&body.stage==='working'&&before.workroom.stage!=='working'){
        if(before.status==='done')throw new TaskError(409,'Request changes on the completed result before reopening it.');
        if(['queued','planning','working'].includes(before.flow?.state)||before.messages.some(m=>['plan','work','review'].includes(m.phase)&&['prepared','unknown','accepted'].includes(m.state)&&!m.outcome&&!before.agentUpdates.some(u=>u.sendId===m.id&&u.applied)&&!before.agentReviews.some(r=>r.sendId===m.id&&r.applied)))throw new TaskError(409,'An existing claim or unresolved dispatch must be reconciled first.');
      }
      if (body.stage === 'working' && !body.owner) throw new TaskError(400,'Choose one owner before marking work in progress.');
      if(body.stage==='done') {
        assertCanComplete(id);
        const task=get(id);
        if(task.progress.reviewFingerprint!==briefFingerprint(task,body))throw new TaskError(409,'Save brief changes and review them before marking the task done.');
      }
      db.prepare(`INSERT INTO workroom_tasks VALUES(?,?,?,?,?,?,?) ON CONFLICT(taskId) DO UPDATE SET
        project=excluded.project,criteria=excluded.criteria,owner=excluded.owner,team=excluded.team,stage=excluded.stage,revision=excluded.revision`)
        .run(id,body.project,body.criteria,body.owner,body.team,body.stage,current.revision+1);
      const base=store.get(id);
      const status=body.stage==='done'?'done':'open';
      if(base.status!==status)store.update(id,{title:base.title,description:base.description,label:base.label,status,revision:base.revision});
      event(id,'updated',`Stage: ${body.stage}; owner: ${body.owner || 'unassigned'}. ${process.env.MESH_SIMPLE_FLOW==='1'?'Managed intake rules apply.':'This edit launches no work.'}`);
      if(process.env.MESH_SIMPLE_FLOW==='1'&&body.stage==='working'&&before.workroom.stage!=='working')flow.enqueue(id);
      if(process.env.MESH_SIMPLE_FLOW==='1'&&flow.read(id)?.state==='clarification'&&(before.workroom.criteria!==body.criteria||before.workroom.project!==body.project))flow.enqueue(id);
      db.exec('COMMIT;');
    } catch(error) { db.exec('ROLLBACK;'); throw error; }
    return get(id);
  }
  function reserve(id, body,phase='message',nativeLocal=null,team=null) {
    if(nativeLocal)nativeLocal=localSessionProfile(nativeLocal);
    get(id);
    if (!body || Object.keys(body).sort().join(',') !== 'agentId,conversationId,id,text' ||
        !identifier(body.id) || !identifier(body.agentId) || !identifier(body.conversationId) ||
        !text(body.text,4000) || !body.text.trim()) throw new TaskError(400,'Choose an agent and conversation and write a message.');
    if(!['message','plan','work','review'].includes(phase))throw new TaskError(400,'Invalid handoff phase.');
    const identity=[id,body.agentId,body.conversationId,body.text];if(phase!=='message')identity.push(phase);if(nativeLocal)identity.push('native-local/v1',nativeLocal);if(team)identity.push('native-team/v1',team.planRevision);
    const fingerprint = createHash('sha256').update(JSON.stringify(identity)).digest('hex');
    db.exec('BEGIN IMMEDIATE;');
    try {
      if(team){if(!nativeLocal)throw new TaskError(409,'Team binding requires native transport.');localSessions.assertTeam(id,body,team);}
      const previous = db.prepare('SELECT * FROM workroom_sends WHERE id=?').get(body.id);
      if(previous) {
        if(previous.fingerprint !== fingerprint) throw new TaskError(409,'This message ID already belongs to a different message.');
        if(!nativeLocal && previous.state!=='accepted' && ['work','review'].includes(phase)){const basis=JSON.parse(previous.basis||'{}'),current=get(id);if(current.plan&&!Number.isSafeInteger(basis.planRevision))throw new TaskError(409,'The frozen request has no matching plan. Inspect it before a new handoff.');assertPlanDispatch(current,body.agentId,phase,basis.planRevision);}
        const local=nativeLocal?localSessions.read(id,body.id):null;
        if(nativeLocal&&!local)throw new TaskError(409,'Native dispatch binding is missing; do not change transports.');
        db.exec('COMMIT;'); return {...previous,...(local?{nativeLocal:local}:{}),replayed:true};
      }
      const task=get(id);
      assertPlanDispatch(task,body.agentId,phase);
      if(nativeLocal){
        if(phase!=='work'||body.agentId!=='echo'||task.plan?.state!=='locked'||task.plan.workerId!=='echo'||task.plan.reviewerId!=='nims'
          ||canonicalWorkspace(task.plan.workspace)!==nativeLocal.workspace)throw new TaskError(409,'Native work requires the locked Echo build/Nims review scope and matching workspace.');
        const peers=store.list().map(task=>get(task.id)).filter(task=>!task.plan?.workspace||canonicalWorkspace(task.plan.workspace)===nativeLocal.workspace||task.messages.some(message=>message.nativeLocal&&!message.nativeLocal.writerQuiescence&&message.nativeLocal.profile.workspace===nativeLocal.workspace));
        if(writerQuiescenceBlockers(peers).filter(blocker=>!(team&&blocker.taskId===id&&blocker.reason==='active_team')).length)throw new TaskError(409,'Resolve the existing workspace writer before preparing native work.');
      }
      if(phase==='work'&&task.plan){
        const peers=db.prepare("SELECT s.taskId,s.id,p.workspace FROM workroom_sends s LEFT JOIN workroom_plans p ON p.taskId=s.taskId WHERE s.phase='work' AND s.taskId<>? AND s.state IN ('prepared','unknown','accepted')").all(id);
        for(const peer of peers){
          const other=get(peer.taskId),native=localSessions.read(peer.taskId,peer.id);
          if(native){
            if(native.writerQuiescence)continue;
            if(native.profile.workspace===canonicalWorkspace(task.plan.workspace))throw new TaskError(409,'A dedicated native writer still holds this workspace.');
            continue;
          }
          if(other.messages.find(m=>m.id===peer.id)?.outcome||(process.env.MESH_SIMPLE_FLOW!=='1'&&other.agentUpdates.some(u=>u.sendId===peer.id&&u.applied)))continue;
          if(!peer.workspace||canonicalWorkspace(peer.workspace)===canonicalWorkspace(task.plan.workspace))throw new TaskError(409,'Resolve the other worker before starting a second writer in this workspace.'+(process.env.MESH_SIMPLE_FLOW==='1'?' Managed assignments require its verified terminal receipt.':''));
        }
      }
      // Recheck under the reservation transaction, after asynchronous capability
      // and agent reads. Two browsers must not start two workers for one task.
      if(phase!=='message' && (task.status==='done' || task.progress.decision==='approved'))throw new TaskError(409,'Reopen the task before a new handoff.');
      if(phase==='work' && (!task.description.trim() || !task.progress.goal.trim() || !task.progress.checklist.length ||
        task.messages.some(message=>message.phase==='work' && ['prepared','unknown','accepted'].includes(message.state) && (message.nativeLocal?!message.nativeLocal.writerQuiescence:!message.outcome && !task.agentUpdates.some(update=>update.sendId===message.id && update.applied)))))throw new TaskError(409,'Save a bounded task and resolve the existing worker handoff first.');
      if(phase==='review' && (!task.worker || task.worker.agentId===body.agentId || !task.progress.result.trim() || !task.progress.evidence.trim() || task.progress.checklist.some(step=>step.status!=='done')))throw new TaskError(409,'A fresh completed worker result and different reviewer are required.');
      const payload=`Workroom message ${body.id}\nPhase: ${phase}\nWorkroom task ${id}: ${task.title}\nProject: ${task.workroom.project}\nOwner: ${task.workroom.owner || 'unassigned'}\nGoal: ${task.progress.goal}\nChecklist: ${task.progress.checklist.map(step=>`[${step.status}] ${step.id}: ${step.text}`).join('; ')}\nAcceptance criteria: ${task.workroom.criteria}\nBrief: ${task.description}\nSaved result: ${task.progress.result}\nVerification evidence: ${task.progress.evidence}\nRecent saved replies (excerpts, last two): ${task.replies.slice(-2).map(reply=>`${reply.agentId}: ${reply.text.slice(0,2000)}`).join('\n')}\n${planBrief(task.plan)}\n${body.text}`+(phase==='review'?agentReviewInstruction(id,body.id):agentUpdateInstruction(id,body.id,phase==='work'?task.progress:undefined));
      db.prepare('INSERT INTO workroom_sends(id,taskId,agentId,conversationId,text,fingerprint,state,at,payload) VALUES(?,?,?,?,?,?,?,?,?)')
        .run(body.id,id,body.agentId,body.conversationId,body.text,fingerprint,'prepared',new Date().toISOString(),payload);
      db.prepare('UPDATE workroom_sends SET basis=?,phase=? WHERE id=?').run(JSON.stringify({taskRevision:task.revision,progressRevision:task.progress.revision,briefFingerprint:briefFingerprint(task,task.workroom),planRevision:task.plan?.revision,workerSendId:task.worker?.sendId,workerHash:task.worker?.hash,workerAgentId:task.worker?.agentId}),phase,body.id);
      const local=nativeLocal?localSessions.prepare(id,body.id,nativeLocal,team):null;
      event(id,'message_prepared',`Message ${body.id} prepared for ${body.agentId}.`);
      db.exec('COMMIT;');
      return {...body,taskId:id,state:'prepared',payload,...(local?{nativeLocal:local}:{}),replayed:false};
    } catch(error) {db.exec('ROLLBACK;');throw error;}
  }
  function settle(id, state) {
    if(db.prepare('SELECT sendId FROM workroom_local_sessions WHERE sendId=?').get(id))throw new TaskError(409,'Use the dedicated native receipt; delivery alone cannot release its writer.');
    if(!['accepted','unknown','rejected'].includes(state)) throw new TaskError(400,'Invalid delivery state.');
    const row=db.prepare('SELECT * FROM workroom_sends WHERE id=?').get(id);
    if(!row) throw new TaskError(404,'Message not found.');
    db.exec('BEGIN IMMEDIATE;');
    try {
      db.prepare('UPDATE workroom_sends SET state=? WHERE id=?').run(state,id);
      event(row.taskId,'message_'+state,`Message ${id}: ${state}. Acceptance is not task completion.`);
      db.exec('COMMIT;');
    } catch(error){db.exec('ROLLBACK;');throw error;}
    return get(row.taskId);
  }
  function captureReplies(taskId,sendId,messages){
    const send=get(taskId).messages.find(message=>message.id===sendId && message.state==='accepted');
    if(!send)throw new TaskError(409,'Only an accepted task message can receive replies.');
    if(send.nativeLocal)throw new TaskError(409,'Dedicated native results require their exact saved receipt.');
    if(!Array.isArray(messages))throw new TaskError(503,'Relay message history unavailable.');
    const frozen=db.prepare('SELECT payload FROM workroom_sends WHERE id=?').get(sendId).payload;
    const matches=messages.map((message,index)=>({message,index})).filter(({message})=>message.k==='you' &&
      (String(message.id)===sendId || message.t===frozen));
    const index=matches.length===1?matches[0].index:-1;
    // Relay assigns numeric transcript IDs. Match the unique frozen payload (which
    // includes our send identity) or exact send ID; never timestamps or fuzzy text.
    if(index<0)return;
    db.exec('BEGIN IMMEDIATE;');
    try{
      for(const message of messages.slice(index+1)){
        if(message.k==='you')break;
        if(!message.id || !text(message.t,64000) || !message.t)continue;
        db.prepare(`INSERT INTO workroom_replies VALUES(?,?,?,?,?,?) ON CONFLICT(taskId,sendId,messageId)
          DO UPDATE SET text=excluded.text`).run(taskId,sendId,String(message.id),send.agentId,message.t,String(message.created_at||send.at));
      }
      db.exec('COMMIT;');
    }catch(error){db.exec('ROLLBACK;');throw error;}
  }
  function applyAssignment(id,body){
    if(!body||Object.keys(body).sort().join(',')!=='briefRevision,hash,messageId,progressRevision,revision,sendId,taskRevision')throw new TaskError(400,'Choose the exact current lead proposal.');
    const task=get(id),offer=task.assignments?.find(a=>a.sendId===body.sendId&&a.messageId===body.messageId&&a.hash===body.hash);if(!offer||offer.agentId!==task.workroom.owner||!['nims','echo'].includes(offer.agentId))throw new TaskError(409,'Current lead proposal changed or is unavailable.');
    const source=db.prepare("SELECT basis FROM workroom_sends WHERE id=? AND taskId=? AND phase='plan' AND state='accepted'").get(body.sendId,id);let basis;try{basis=JSON.parse(source?.basis);}catch{throw new TaskError(409,'No current proposal source.');}
    const ownUpdate=task.agentUpdates.some(u=>u.sendId===offer.sendId&&u.applied&&u.update.goal===task.progress.goal&&u.update.result===task.progress.result&&u.update.evidence===task.progress.evidence&&JSON.stringify(u.update.checklist)===JSON.stringify(task.progress.checklist));
    if(basis.taskRevision!==task.revision||basis.briefFingerprint!==briefFingerprint(task,task.workroom)||(basis.progressRevision!==task.progress.revision&&!ownUpdate))throw new TaskError(409,'The task changed after this proposal. Ask for a fresh plan.');
    const {schema,taskId,sendId,...fields}=offer.proposal;return savePlan(db,get,id,{...fields,lead:task.workroom.owner,state:'draft',revision:body.revision,taskRevision:body.taskRevision,briefRevision:body.briefRevision,progressRevision:body.progressRevision});
  }
  function applyAgentUpdate(id,body){
    if(!body || Object.keys(body).sort().join(',')!=='briefRevision,hash,messageId,revision,sendId,taskRevision' ||
       !identifier(body.sendId) || !text(body.messageId,100) || !/^[a-f0-9]{64}$/.test(body.hash))throw new TaskError(400,'Invalid agent update selection.');
    const task=get(id);
    const offer=task.agentUpdates.find(update=>update.sendId===body.sendId && update.messageId===body.messageId && update.hash===body.hash);
    if(!offer)throw new TaskError(409,'Agent report changed or is unavailable. Refresh before applying.');
    const native=localSessions.read(id,body.sendId);
    if(native&&(!native.writerQuiescence||native.nativeOutcome!=='completed'))throw new TaskError(409,'Native worker result is saved for inspection; retirement verification is required before applying it.');
    if(offer.applied)return {task,duplicate:true};
    const send=db.prepare("SELECT basis FROM workroom_sends WHERE taskId=? AND id=? AND state='accepted'").get(id,body.sendId);
    let basis;try{basis=JSON.parse(send?.basis);}catch{throw new TaskError(409,'This older message has no current task basis. Request a fresh update.');}
    if(task.status==='done' || task.progress.decision==='approved' || basis.taskRevision!==task.revision || basis.progressRevision!==task.progress.revision ||
       basis.briefFingerprint!==briefFingerprint(task,task.workroom))throw new TaskError(409,'The task changed or was reviewed after this message. Request a fresh agent update.');
    if(offer.phase==='work'&&task.plan&&(!Number.isSafeInteger(basis.planRevision)||task.plan.state!=='locked'||basis.planRevision!==task.plan.revision))throw new TaskError(409,'This report belongs to an older or unlocked plan. Inspect it and request a fresh result.');
    const {goal,checklist,result,evidence}=offer.update;
    if(offer.phase==='work'&&task.plan&&(goal!==task.progress.goal||checklist.length!==task.progress.checklist.length||
       checklist.some((step,index)=>step.id!==task.progress.checklist[index].id||step.text!==task.progress.checklist[index].text)))
      throw new TaskError(409,'Worker report changed the locked goal or checklist. Inspect the report; the original scope was preserved.');
    const updated=saveProgress(id,{goal,checklist,result,evidence,reviewer:'',decision:'pending',revision:body.revision,taskRevision:body.taskRevision,briefRevision:body.briefRevision},offer);
    return {task:updated,duplicate:false};
  }
  function applyAgentReview(id,body){
    if(!body || Object.keys(body).sort().join(',')!=='briefRevision,hash,messageId,revision,sendId,taskRevision')throw new TaskError(400,'Invalid review selection.');
    const task=get(id);const offer=task.agentReviews.find(review=>review.sendId===body.sendId && review.messageId===body.messageId && review.hash===body.hash);
    if(!offer)throw new TaskError(409,'Review changed or is unavailable. Refresh before recording.');
    if(offer.applied)return {task,duplicate:true};
    const send=db.prepare("SELECT basis FROM workroom_sends WHERE taskId=? AND id=? AND phase='review' AND state='accepted'").get(id,body.sendId);
    const nativeOutcome=task.messages.find(message=>message.id===body.sendId)?.outcome;
    if(nativeOutcome && nativeOutcome.state!=='TASK_STATE_COMPLETED')throw new TaskError(409,'This review attempt ended unsuccessfully. Request a fresh independent review.');
    let basis;try{basis=JSON.parse(send?.basis);}catch{throw new TaskError(409,'Review source is unavailable.');}
    if(task.plan&&(task.plan.state!=='locked'||basis.planRevision!==task.plan.revision))throw new TaskError(409,'This review belongs to an older or unlocked plan. Request a fresh review.');
    if(!task.worker || task.worker.agentId===offer.agentId || basis.workerAgentId!==task.worker.agentId || basis.workerSendId!==task.worker.sendId || basis.workerHash!==task.worker.hash ||
       basis.taskRevision!==task.revision || basis.progressRevision!==task.progress.revision || basis.briefFingerprint!==briefFingerprint(task,task.workroom) || task.status==='done')throw new TaskError(409,'Work changed or the reviewer is not independent. Request a fresh review.');
    const {goal,checklist,result,evidence}=task.progress;
    const reviewed=saveProgress(id,{goal,checklist,result,evidence,
      reviewer:offer.agentId,decision:offer.review.verdict,revision:body.revision,taskRevision:body.taskRevision,briefRevision:body.briefRevision},{...offer,review:true});
    return {task:reviewed,duplicate:false};
  }
  function canApproveHandoff(id,sendId){
    const task=get(id);const row=db.prepare('SELECT basis,state FROM workroom_sends WHERE taskId=? AND id=?').get(id,sendId);
    if(task.messages.find(message=>message.id===sendId)?.outcome)return false;
    let basis;try{basis=JSON.parse(row?.basis);}catch{return false;}
    if(!basis || typeof basis!=='object')return false;
    const message=task.messages.find(message=>message.id===sendId);
    if(task.plan&&['work','review'].includes(message?.phase)&&!Number.isSafeInteger(basis.planRevision))return false;
    try{assertPlanDispatch(task,message?.agentId,message?.phase,basis.planRevision);}catch{return false;}
    return row?.state==='accepted' && task.status!=='done' && task.progress.decision!=='approved' && basis.taskRevision===task.revision && basis.progressRevision===task.progress.revision && basis.briefFingerprint===briefFingerprint(task,task.workroom);
  }
  function sendBinding(id,sendId){
    get(id);const source=db.prepare("SELECT id,taskId,agentId,conversationId,payload FROM workroom_sends WHERE taskId=? AND id=? AND agentId='dsh' AND state='accepted'").get(id,sendId);
    if(!source)throw new TaskError(409,'Only this taskÃ¢â‚¬â„¢s accepted DeepSeek send can be reconciled.');return source;
  }
  function recordSendOutcome(id,sendId,outcome){
    sendBinding(id,sendId);
    if(!outcome || !identifier(outcome.peerTaskId) || !['TASK_STATE_COMPLETED','TASK_STATE_CANCELED','TASK_STATE_FAILED','TASK_STATE_REJECTED'].includes(outcome.state) || !/^[a-f0-9]{64}$/.test(outcome.proofHash) || !Number.isFinite(Date.parse(outcome.verifiedAt)))throw new TaskError(400,'Invalid verified native outcome.');
    db.exec('BEGIN IMMEDIATE;');
    try{
      const previous=db.prepare('SELECT * FROM workroom_send_outcomes WHERE sendId=?').get(sendId);
      if(previous){if(previous.peerTaskId!==outcome.peerTaskId || previous.state!==outcome.state || previous.proofHash!==outcome.proofHash)throw new TaskError(409,'A different native outcome was already recorded.');db.exec('COMMIT;');return {task:get(id),duplicate:true};}
      db.prepare('INSERT INTO workroom_send_outcomes VALUES(?,?,?,?,?,?)').run(sendId,id,outcome.peerTaskId,outcome.state,outcome.proofHash,outcome.verifiedAt);
      event(id,'native_outcome_verified',`Send ${sendId}: ${outcome.state}; native task ${outcome.peerTaskId}. Delivery receipt and Relay queue unchanged.`);
      db.exec('COMMIT;');return {task:get(id),duplicate:false};
    }catch(error){db.exec('ROLLBACK;');throw error;}
  }
  return {get,nims,nativeReceipts,localSessions,automation,flow,rook,ownerReview,applyAssignment,list:()=>store.list().map(task=>get(task.id)),savePlan:(id,body)=>savePlan(db,get,id,body),save,saveProgress,assertCanComplete,isEnrolled,reserve,settle,captureReplies,applyAgentUpdate,applyAgentReview,canApproveHandoff,sendBinding,recordSendOutcome};
}

export async function syncTaskReplies({workroom,taskId,relay,admitted,sendId}){
  const task=workroom.get(taskId);const sessions=new Map();
  for(const message of task.messages.filter(message=>message.state==='accepted'&&!message.nativeLocal&&(!sendId||message.id===sendId))){
    if(!admitted())throw new TaskError(403,'Session expired.');
    const route=`/api/agents/${encodeURIComponent(message.agentId)}/sessions/${encodeURIComponent(message.conversationId)}/messages`;
    if(message.agentId==='nims'&&typeof relay.recoverTaskReply==='function'){const recovered=await relay.recoverTaskReply({taskId,sendId:message.id,admitted});if(recovered.recovered)sessions.delete(route);}
    if(!sessions.has(route))sessions.set(route,await relay.nativeRead(route));
    if(!admitted())throw new TaskError(403,'Session expired.');
    workroom.captureReplies(taskId,message.id,sessions.get(route)?.messages);
    if(message.agentId==='echo' && typeof relay.nativeRunReceipt==='function') {
      const binding=workroom.nativeReceipts.binding(taskId,message.id);
      try {
        const receipt=await relay.nativeRunReceipt(binding);
        if(!admitted())throw new TaskError(403,'Session expired.');
        workroom.nativeReceipts.save(taskId,message.id,binding.revision,receipt);
      } catch(error) {
        if(!admitted() || error.status===403)throw new TaskError(403,'Session expired.');
        try {workroom.nativeReceipts.unavailable(taskId,message.id,binding.revision);}
        catch(conflict) {if(conflict.status!==409)throw conflict;}
      }
    }
  }
  return {task:workroom.get(taskId)};
}

export async function sendTaskMessage({workroom, taskId, body, relay, admitted,phase='message',allowUncertainReplay=true}) {
  if(workroom.get(taskId).messages.find(message=>message.id===body.id)?.nativeLocal)throw new TaskError(409,'Use the saved dedicated native transport, not Relay.');
  // A receiver must enforce session binding; never silently rely on an older API.
  const capabilities=await relay.nativeRead(body.agentId==='nims'?'/api/nims/capabilities':'/api/mesh-capabilities');
  if(capabilities?.taskSessionBinding !== 1) throw new TaskError(503,'Relay needs the session-binding update before task messages can run.');
  if(!admitted()) throw new TaskError(403,'Session expired.');
  const message=workroom.reserve(taskId,body,phase);
  if(message.state==='accepted') return {task:workroom.get(taskId),duplicate:true};
  if(message.replayed&&!allowUncertainReplay)throw new TaskError(409,'Automatic replay refused. Reconcile the original dispatch receipt before retrying.');
  if(message.replayed && message.state==='prepared') throw new TaskError(409,'This send has no confirmed outcome. Inspect or retry it deliberately after recovery.');
  try {
    await relay.taskMessage({...body,text:message.payload},admitted);
  } catch(error) {
    workroom.settle(body.id,[400,403,409].includes(error.status)?'rejected':'unknown');
    throw error;
  }
  return {task:workroom.settle(body.id,'accepted'),duplicate:message.replayed};
}

export async function sendTaskHandoff({workroom,taskId,body,relay,admitted,allowUncertainReplay=true}){
  if(!body || Object.keys(body).sort().join(',')!=='agentId,conversationId,id,phase' || !['plan','work','review'].includes(body.phase))throw new TaskError(400,'Choose a valid handoff.');
  const task=workroom.get(taskId);
  const existing=task.messages.find(message=>message.id===body.id);
  if(existing){
    if(existing.nativeLocal)throw new TaskError(409,'Use the saved dedicated native transport, not Relay.');
    if(existing.agentId!==body.agentId || existing.conversationId!==body.conversationId || existing.phase!==body.phase)throw new TaskError(409,'Retry the original handoff identity and destination unchanged.');
    if(existing.state!=='accepted' && (task.status==='done' || task.progress.decision==='approved'))throw new TaskError(409,'Completed work cannot dispatch an uncertain handoff. Inspect its original receipt.');
    // A retry recovers a frozen send, not a new job. Live busy state and later
    // task edits cannot invalidate a receipt; Relay still enforces session binding.
    return sendTaskMessage({workroom,taskId,body:{id:body.id,agentId:body.agentId,conversationId:body.conversationId,text:existing.text},relay,admitted,phase:body.phase,allowUncertainReplay});
  }
  if(task.status==='done' || task.progress.decision==='approved')throw new TaskError(409,'Reopen the task before a new handoff.');
  if(body.phase==='plan' && task.workroom.owner==='nims' && body.agentId!=='nims')throw new TaskError(409,'Nims is the project lead. Its connection is required; do not silently route to another peer.');
  if(body.phase==='plan' && task.workroom.owner==='echo' && body.agentId!=='echo')throw new TaskError(409,'Echo is the project lead. Send planning to Echo or change the saved lead.');
  assertPlanDispatch(task,body.agentId,body.phase);
  if(body.phase==='work' && (!task.progress.goal.trim() || !task.progress.checklist.length || !task.description.trim()))throw new TaskError(409,'Save a bounded brief, goal and checklist before sending work.');
  if(body.phase==='work' && task.messages.some(message=>message.phase==='work' && message.id!==body.id && ['prepared','unknown','accepted'].includes(message.state) && (message.nativeLocal?!message.nativeLocal.writerQuiescence:!message.outcome && !task.agentUpdates.some(update=>update.sendId===message.id && update.applied))))throw new TaskError(409,'Resolve or apply the existing worker handoff before starting another.');
  if(body.phase==='review' && (!task.worker || task.worker.agentId===body.agentId || !task.progress.result.trim() || !task.progress.evidence.trim() || task.progress.checklist.some(step=>step.status!=='done')))throw new TaskError(409,'Apply a completed worker result, then choose a different agent to review it.');
  const roster=await relay.agents();const agent=roster.find(agent=>agent.id===body.agentId);
  if(!agent || agent.conversation_id!==body.conversationId || !['hermes','a2a','codex'].includes(agent.backend) || !['idle','done','stopped'].includes(agent.status))throw new TaskError(409,'That agent is busy or its conversation changed. Refresh before sending.');
  if(body.phase==='work'&&agent.backend==='codex')throw new TaskError(409,'Nims is qualified for read-only planning/review, not edits. Choose a coding builder.');
  const instructions={plan:leadPlanningInstruction+assignmentInstruction(taskId,body.id,roster),
    work:WORKER_INSTRUCTION,
    review:'Independently inspect the saved worker result and named artifacts against the acceptance criteria. Verify the actual evidence, not just the worker claims. Return your review in the requested format. Read-only tools only; do not modify artifacts.'};
  const {id,agentId,conversationId,phase}=body;
  return sendTaskMessage({workroom,taskId,body:{id,agentId,conversationId,text:instructions[phase]+(process.env.MESH_SIMPLE_FLOW==='1'?(phase==='plan'?'\nManaged Mesh flow: use the current Mesh checkout only. If the request is sufficiently clear, return the source-bound workroom-assignment proposal with explicit permitted files/checks, Echo building and Nims independently reviewing. Otherwise ask the specific missing question. Your proposal will be validated before work starts.':phase==='work'&&workroom.get(taskId).flow?.ownerNote?'\nOwner requested changes (within the saved scope only; ask if scope must change): '+workroom.get(taskId).flow.ownerNote:''):'')},relay,admitted,phase,allowUncertainReplay});
}
