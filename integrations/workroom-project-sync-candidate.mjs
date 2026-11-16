// Explicit factory for isolated application qualification. Never enabled by env/UI.
import {createHash} from 'node:crypto';
import {ProjectOutboxCandidate,initializeProjectOutbox,canonicalProjectEvent,validateProjectEvent} from './project-sync-outbox-candidate.mjs';

const allowed = ['title','goal','owner','stage','result','blocker'];

export function createWorkroomProjectSyncCandidate({db,store},
  {storeId,initialize=false,approveCreation=null}={}) {
  if(initialize){
    initializeProjectOutbox(db);
    db.exec('CREATE TABLE mind_project_capture_policy(cardId TEXT PRIMARY KEY REFERENCES mind_project_links(cardId), fields TEXT NOT NULL)');
  }
  function readSnapshot(cardId) {
    const policy=db.prepare('SELECT fields FROM mind_project_capture_policy WHERE cardId=?').get(cardId);
    if(!policy)throw Error('Explicit shared-field policy required.');
    const fields=JSON.parse(policy.fields);
    if(!Array.isArray(fields)||!fields.includes('title')||!fields.includes('stage')||
      fields.some(f=>!allowed.includes(f))||new Set(fields).size!==fields.length)throw Error('Invalid sharing policy.');
    const task=store.workroom.get(cardId);
    const blocked=task.progress.checklist.filter(step=>step.status==='blocked').length;
    const values={title:task.title,goal:task.progress.goal,owner:task.workroom.owner,
      stage:task.workroom.stage,result:task.progress.result,
      blocker:blocked?`${blocked} checklist step(s) blocked.`:task.progress.decision==='changes_requested'?'Review changes requested.':''};
    const snapshot=Object.fromEntries(allowed.map(f=>[f,fields.includes(f)?values[f]:'']));
    const revisions={task:task.revision,brief:task.workroom.revision,progress:task.progress.revision};
    const digest=createHash('sha256').update(canonicalProjectEvent({revisions,snapshot})).digest('hex');
    // A source pointer/hash, never raw chat, free-form evidence or a fetched file.
    return {revisions,snapshot,evidence:[{type:'workroom',
      ref:`card:${cardId}@${revisions.task}/${revisions.brief}/${revisions.progress}`,content_hash:`sha256:${digest}`}]};
  }
  const outbox=new ProjectOutboxCandidate(db,{storeId,readSnapshot});
  function atomic(fn){
    const own=!db.isTransaction;
    if(own)db.exec('BEGIN IMMEDIATE');
    try{const result=fn();if(own)db.exec('COMMIT');return result;}
    catch(error){if(own)db.exec('ROLLBACK');throw error;}
  }
  function link({cardId,projectId,approvalRef,fields}) {
    return atomic(()=>{
      outbox.linkCard(cardId,projectId,approvalRef);
      db.prepare('INSERT INTO mind_project_capture_policy VALUES(?,?)').run(cardId,JSON.stringify(fields));
      return outbox.capture(cardId,'created');
    });
  }
  function capture(cardId,kind) {
    let linked=db.prepare('SELECT active FROM mind_project_links WHERE cardId=?').get(cardId);
    if(!linked&&kind==='created'&&approveCreation){
      const approval=approveCreation(store.workroom.get(cardId));
      if(approval)return link({...approval,cardId});
    }
    if(!linked?.active)return null;
    const last=db.prepare('SELECT payload FROM mind_project_outbox WHERE cardId=? ORDER BY sequence DESC LIMIT 1').get(cardId);
    const current=readSnapshot(cardId);
    if(last){
      const previous=JSON.parse(last.payload);
      if(canonicalProjectEvent(previous.revisions)===canonicalProjectEvent(current.revisions)){
        if(canonicalProjectEvent(previous.snapshot)!==canonicalProjectEvent(current.snapshot))throw Error('Shared facts changed without a source revision.');
        return null;
      }
    }
    return outbox.capture(cardId,current.snapshot.stage==='done'?'completed':kind);
  }
  function status(cardId){
    const link=db.prepare('SELECT * FROM mind_project_links WHERE cardId=?').get(cardId);
    if(!link)return {state:'not_shared'};
    if(!link.active)return {state:'withdrawn'};
    if(link.storeId!==storeId)return {state:'held'};
    const rows=db.prepare('SELECT * FROM mind_project_outbox WHERE cardId=? ORDER BY sequence').all(cardId);
    if(!rows.length)return {state:'held'};
    for(const row of rows){
      try{
        const event=JSON.parse(row.payload);
        if(validateProjectEvent(event).hash!==row.payloadHash||event.cardId!==cardId||event.projectId!==link.projectId||
          event.eventId!==row.eventId||event.sequence!==row.sequence)return {state:'held'};
        if(row.state==='saved'){
          const receipt=JSON.parse(row.receipt);
          if(!outbox._receipt(receipt,event,row.payloadHash)||!['active','superseded'].includes(receipt.recordState))return {state:'held'};
        }
      }catch{return {state:'held'};}
    }
    const latest=JSON.parse(rows.at(-1).payload),current=readSnapshot(cardId);
    if(canonicalProjectEvent(latest.revisions)!==canonicalProjectEvent(current.revisions)||
      canonicalProjectEvent(latest.snapshot)!==canonicalProjectEvent(current.snapshot))return {state:'held'};
    for(const state of ['held','uncertain','pending'])if(rows.some(row=>row.state===state))return {state};
    return {state:'saved'};
  }
  return {capture,link,outbox,status,withdraw:cardId=>atomic(()=>outbox.withdraw(cardId))};
}
