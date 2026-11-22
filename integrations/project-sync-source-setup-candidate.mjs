// Explicit owner action only. No startup, HTTP route, migration or Mind access.
import {DatabaseSync} from 'node:sqlite';
import {realpathSync,statSync} from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {readWorkroomCardState} from '../lib/workroom-card-state.mjs';
import {createWorkroomProjectSyncCandidate,projectSnapshot} from './workroom-project-sync-candidate.mjs';
import {canonicalProjectEvent,validateProjectEvent} from './project-sync-outbox-candidate.mjs';

const exact=(v,keys)=>v?.constructor===Object&&Object.keys(v).sort().join(',')===[...keys].sort().join(',');
const id=v=>typeof v==='string'&&/^[A-Za-z0-9_-]{1,100}$/.test(v);
const require=ok=>{if(!ok)throw Error('Project source setup refused; preserve state.');};
const hash=v=>createHash('sha256').update(canonicalProjectEvent(v)).digest('hex');
const tables=['mind_project_links','mind_project_outbox','mind_project_capture_policy'];

function checked(value){
  const p=JSON.parse(canonicalProjectEvent(value));
  require(exact(p,['schema','workspace','dataDir','source','storeId','links'])&&p.schema==='onoes-mesh-project-source-setup/v1');
  require(typeof p.workspace==='string'&&path.isAbsolute(p.workspace)&&realpathSync(p.workspace)===p.workspace&&
    typeof p.dataDir==='string'&&/^data\/[A-Za-z0-9_-]+$/.test(p.dataDir)&&id(p.storeId));
  require(exact(p.source,['databasePath','fileDevice','fileInode'])&&
    p.source.databasePath===path.join(p.workspace,p.dataDir,'tasks.sqlite')&&
    realpathSync(p.source.databasePath)===p.source.databasePath&&
    ['fileDevice','fileInode'].every(n=>typeof p.source[n]==='string'&&/^(0|[1-9][0-9]{0,19})$/.test(p.source[n])));
  require(Array.isArray(p.links)&&p.links.length>0&&p.links.length<=32);
  const seen=new Set();
  for(const link of p.links){
    require(exact(link,['cardId','projectId','approvalRef','fields','revisions','projectionSha256'])&&
      id(link.cardId)&&id(link.projectId)&&!seen.has(link.cardId)&&typeof link.approvalRef==='string'&&
      link.approvalRef.trim()===link.approvalRef&&link.approvalRef.length>0&&link.approvalRef.length<=300&&
      !/[\x00-\x1f\x7f]/.test(link.approvalRef)&&Array.isArray(link.fields)&&
      link.fields.includes('title')&&link.fields.includes('stage')&&new Set(link.fields).size===link.fields.length&&
      link.fields.every(f=>['title','goal','owner','stage','result','blocker'].includes(f))&&
      exact(link.revisions,['task','brief','progress'])&&Object.values(link.revisions).every(n=>Number.isSafeInteger(n)&&n>=0)&&
      link.revisions.task>0&&typeof link.projectionSha256==='string'&&/^[a-f0-9]{64}$/.test(link.projectionSha256));
    seen.add(link.cardId);
  }
  require(Buffer.byteLength(canonicalProjectEvent(p))<=32768);identity(p);return p;
}

function identity(p){
  require(realpathSync(p.source.databasePath)===p.source.databasePath);
  const s=statSync(p.source.databasePath,{bigint:true});
  require(s.isFile()&&String(s.dev)===p.source.fileDevice&&String(s.ino)===p.source.fileInode);
}

function open(p,readOnly){
  identity(p);const db=new DatabaseSync(p.source.databasePath,{readOnly});
  try{
    db.exec('PRAGMA busy_timeout=2000; PRAGMA foreign_keys=ON;');
    if(readOnly)db.exec('PRAGMA query_only=ON');
    require(db.prepare('PRAGMA user_version').get().user_version===5&&
      db.prepare('PRAGMA quick_check').get().quick_check==='ok'&&!db.prepare('PRAGMA foreign_key_check').all().length);
    identity(p);return db;
  }catch(e){db.close();throw e;}
}

function card(db,cardId){
  const task=db.prepare('SELECT * FROM tasks WHERE id=?').get(cardId);require(task);
  return {...task,...readWorkroomCardState(db,task)};
}

function snapshots(db,p){
  return p.links.map(link=>{
    const snapshot=projectSnapshot(card(db,link.cardId),link.fields);
    require(canonicalProjectEvent(snapshot.revisions)===canonicalProjectEvent(link.revisions)&&
      hash({revisions:snapshot.revisions,snapshot:snapshot.snapshot})===link.projectionSha256);
    validateProjectEvent({schema:'onoes-mind-project-event/v1',eventId:'source-setup-preview',
      cardId:link.cardId,projectId:link.projectId,sequence:1,kind:'created',...snapshot});
    return snapshot;
  });
}

function present(db){
  return db.prepare("SELECT name FROM sqlite_schema WHERE type='table' AND name LIKE 'mind_project_%'").all().map(r=>r.name).sort();
}

function receipt(db,p){
  require(canonicalProjectEvent(present(db))===canonicalProjectEvent([...tables].sort()));
  require(db.prepare('SELECT count(*) AS n FROM mind_project_links').get().n===p.links.length&&
    db.prepare('SELECT count(*) AS n FROM mind_project_capture_policy').get().n===p.links.length);
  const baselines=p.links.map(link=>{
    const row=db.prepare('SELECT * FROM mind_project_links WHERE cardId=?').get(link.cardId);
    const policy=db.prepare('SELECT fields FROM mind_project_capture_policy WHERE cardId=?').get(link.cardId);
    require(row&&row.projectId===link.projectId&&row.storeId===p.storeId&&row.approvalRef===link.approvalRef&&
      row.active===1&&row.sequence>=1&&policy&&canonicalProjectEvent(JSON.parse(policy.fields))===canonicalProjectEvent(link.fields));
    const first=db.prepare('SELECT * FROM mind_project_outbox WHERE cardId=? AND sequence=1').get(link.cardId);
    require(first);const event=JSON.parse(first.payload),validated=validateProjectEvent(event);
    require(validated.hash===first.payloadHash&&event.eventId===first.eventId&&event.cardId===link.cardId&&
      event.projectId===link.projectId&&event.sequence===1&&event.kind==='created'&&
      canonicalProjectEvent(event.revisions)===canonicalProjectEvent(link.revisions)&&
      hash({revisions:event.revisions,snapshot:event.snapshot})===link.projectionSha256);
    return {cardId:link.cardId,eventId:first.eventId,payloadHash:first.payloadHash};
  });
  return {schema:'onoes-mesh-project-source-receipt/v1',planSha256:hash(p),source:p.source,baselines,startsDelivery:false};
}

export function inspectProjectSource(value){
  const p=checked(value),db=open(p,true);
  try{
    db.exec('BEGIN');const existing=present(db);
    let result;
    if(existing.length){result={state:'prepared',...receipt(db,p)};}
    else{snapshots(db,p);result={state:'unprepared',ready:true,createsNothing:true,planSha256:hash(p),cardCount:p.links.length};}
    db.exec('COMMIT');identity(p);return result;
  }finally{db.close();}
}

export function prepareProjectSource(value,approval){
  const p=checked(value);
  require(exact(approval,['decision','planSha256'])&&approval.decision==='approve_exact_mesh_project_source_setup'&&approval.planSha256===hash(p));
  return writeProjectSource(p,null);
}

function addedLink(db,p,cardId){
  const link=p.links.find(row=>row.cardId===cardId);
  require(link && p.links.length>=2);
  // Previously shared cards may have changed. Compare their original baselines
  // and current sharing policy. Only the new card must match its current contents.
  receipt(db,{...p,links:p.links.filter(row=>row.cardId!==cardId)});
  snapshots(db,{links:[link]});
  return link;
}

export function inspectProjectSourceAddition(value,cardId){
  const p=checked(value),db=open(p,true);
  try{
    db.exec('BEGIN');
    addedLink(db,p,cardId);
    db.exec('COMMIT');identity(p);
    return {state:'ready_to_add',createsNothing:true,addedCardId:cardId,planSha256:hash(p)};
  }finally{db.close();}
}

export function prepareProjectSourceAddition(value,approval){
  const p=checked(value);
  require(exact(approval,['decision','planSha256','addedCardId'])&&
    approval.decision==='approve_exact_mesh_project_source_addition'&&approval.planSha256===hash(p)&&id(approval.addedCardId));
  return writeProjectSource(p,approval.addedCardId);
}

function writeProjectSource(p,addedCardId){
  const db=open(p,false);let commitAttempted=false;
  try{
    db.exec('BEGIN IMMEDIATE');
    let links=p.links;
    if(addedCardId===null){
      require(present(db).length===0);snapshots(db,p);
    }else{
      links=[addedLink(db,p,addedCardId)];
    }
    const store={workroom:{get:cardId=>card(db,cardId)}};
    const controller=createWorkroomProjectSyncCandidate({db,store},{storeId:p.storeId,initialize:addedCardId===null,joinTransaction:true});
    for(const {cardId,projectId,approvalRef,fields} of links)controller.link({cardId,projectId,approvalRef,fields});
    const result=receipt(db,p);identity(p);commitAttempted=true;db.exec('COMMIT');return result;
  }catch(error){
    if(db.isTransaction){try{db.exec('ROLLBACK');}catch{commitAttempted=true;}}
    if(commitAttempted)throw Object.assign(Error('Project source setup outcome uncertain; inspect the same plan, do not retry.'),{projectSourceOutcomeUnknown:true});
    throw error;
  }finally{db.close();}
}
