import {createHash} from 'node:crypto';
import {resolve,isAbsolute} from 'node:path';
import {TaskError} from './task-store.mjs';

const digest=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const workspace=value=>resolve(value).toLowerCase();
const label=value=>typeof value==='string'&&/^[A-Za-z0-9_-]{1,100}$/.test(value);
const session=value=>typeof value==='string'&&/^local-[a-f0-9]{64}$/.test(value);
const admission=value=>typeof value==='string'&&/^[a-f0-9]{32}$/.test(value);
export function localSessionProfile(value){
  if(!value||Object.keys(value).sort().join(',')!=='baseUrl,identityRef,model,profileRef,workspace'
    ||!label(value.profileRef)||!label(value.identityRef)||typeof value.model!=='string'||!value.model.trim()
    ||value.model.length>200||/[\x00-\x1f]/.test(value.model)||typeof value.workspace!=='string'||!isAbsolute(value.workspace))
    throw new TaskError(400,'A fixed native worker profile is required.');
  let url;try{url=new URL(value.baseUrl);}catch{throw new TaskError(400,'Invalid native provider endpoint.');}
  if(!['http:','https:'].includes(url.protocol)||url.username||url.password||url.search||url.hash)
    throw new TaskError(400,'Native profile metadata cannot contain endpoint credentials.');
  return {profileRef:value.profileRef,identityRef:value.identityRef,model:value.model,
    baseUrl:url.href.replace(/\/$/,''),workspace:workspace(value.workspace)};
}

export function createLocalSessionStore(db,get,reserve){
  db.exec(`CREATE TABLE IF NOT EXISTS workroom_local_sessions (
    sendId TEXT PRIMARY KEY REFERENCES workroom_sends(id),taskId TEXT NOT NULL REFERENCES tasks(id),
    profile TEXT NOT NULL,profileHash TEXT NOT NULL,createRequestId TEXT NOT NULL,submissionId TEXT NOT NULL,
    state TEXT NOT NULL,sessionId TEXT,admissionId TEXT,nativeStatus TEXT,nativeGeneration INTEGER,nativeProfileId TEXT,nativeEpoch INTEGER,
    revision INTEGER NOT NULL,createdAt TEXT NOT NULL,lastCheckedAt TEXT NOT NULL)`);
  for(const [name,type] of [['nativeProfileId','TEXT'],['nativeEpoch','INTEGER']])if(!db.prepare('PRAGMA table_info(workroom_local_sessions)').all().some(column=>column.name===name))db.exec(`ALTER TABLE workroom_local_sessions ADD COLUMN ${name} ${type}`);
  function read(taskId,sendId){
    const row=db.prepare('SELECT * FROM workroom_local_sessions WHERE taskId=? AND sendId=?').get(taskId,sendId);
    return row?{...row,profile:JSON.parse(row.profile),writerQuiescence:false}:null;
  }
  function prepare(taskId,sendId,profile){
    profile=localSessionProfile(profile);
    if(!db.isTransaction)throw new TaskError(409,'Native intent must share the dispatch transaction.');
    const source=db.prepare("SELECT * FROM workroom_sends WHERE taskId=? AND id=? AND agentId='echo' AND phase='work' AND state='prepared'").get(taskId,sendId);
    if(!source)throw new TaskError(409,'Only a new saved Echo build can select this transport.');
    const hash=digest(profile),key=digest([taskId,sendId,source.fingerprint,hash]),stamp=new Date().toISOString();
    db.prepare('INSERT INTO workroom_local_sessions(sendId,taskId,profile,profileHash,createRequestId,submissionId,state,sessionId,admissionId,nativeStatus,nativeGeneration,nativeProfileId,nativeEpoch,revision,createdAt,lastCheckedAt) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)')
      .run(sendId,taskId,JSON.stringify(profile),hash,'mesh-local-create-'+key,'mesh-local-submit-'+key,
        'prepared',null,null,null,null,null,null,1,stamp,stamp);
    return read(taskId,sendId);
  }
  function change(taskId,sendId,revision,fn){
    db.exec('BEGIN IMMEDIATE');
    try{
      const row=read(taskId,sendId);
      if(!row||!Number.isSafeInteger(revision)||row.revision!==revision)throw new TaskError(409,'Native binding changed; read the saved intent again.');
      const next=fn(row);
      db.prepare(`UPDATE workroom_local_sessions SET state=?,sessionId=?,admissionId=?,nativeStatus=?,nativeGeneration=?,nativeProfileId=?,nativeEpoch=?,revision=revision+1,lastCheckedAt=?
        WHERE taskId=? AND sendId=? AND revision=?`).run(next.state,next.sessionId,next.admissionId,next.nativeStatus,next.nativeGeneration,next.nativeProfileId,next.nativeEpoch,new Date().toISOString(),taskId,sendId,revision);
      db.prepare('UPDATE workroom_sends SET state=? WHERE taskId=? AND id=?')
        .run(next.admissionId?'accepted':next.state==='prepared'?'prepared':'unknown',taskId,sendId);
      db.exec('COMMIT');return read(taskId,sendId);
    }catch(error){db.exec('ROLLBACK');throw error;}
  }
  return {read,prepare,
    pendingReads:()=>db.prepare("SELECT taskId,sendId FROM workroom_local_sessions WHERE sessionId IS NOT NULL AND state IN ('submit_pending','submit_unknown','observed','unavailable') AND NOT (state='observed' AND nativeStatus='terminal') ORDER BY lastCheckedAt,sendId").all(),
    reserve:(taskId,body,profile)=>reserve(taskId,body,'work',localSessionProfile(profile)),
    startCreate:(taskId,sendId,revision)=>change(taskId,sendId,revision,row=>{
      if(row.state!=='prepared')throw new TaskError(409,'Reconcile the original native creation; do not create a replacement.');
      return {...row,state:'create_pending'};
    }),
    bindSession:(taskId,sendId,revision,value)=>change(taskId,sendId,revision,row=>{
      if(!['create_pending','create_unknown'].includes(row.state)||!session(value?.session_id)
        ||row.sessionId&&row.sessionId!==value.session_id)throw new TaskError(409,'Native session does not match the saved creation.');
      return {...row,sessionId:value.session_id,state:'session_bound'};
    }),
    startSubmit:(taskId,sendId,revision)=>change(taskId,sendId,revision,row=>{
      if(row.state!=='session_bound'||row.admissionId)throw new TaskError(409,'Only the first native submission can start; use read-only reconciliation.');
      const task=get(taskId),source=db.prepare('SELECT basis FROM workroom_sends WHERE id=? AND taskId=?').get(sendId,taskId),basis=JSON.parse(source.basis);
      if(task.status==='done'||task.plan?.state!=='locked'||task.plan.revision!==basis.planRevision
        ||task.revision!==basis.taskRevision||task.progress.revision!==basis.progressRevision)
        throw new TaskError(409,'The saved work changed before native submission.');
      return {...row,state:'submit_pending'};
    }),
    observe:(taskId,sendId,revision,value)=>change(taskId,sendId,revision,row=>{
      if(!['submit_pending','submit_unknown','observed','unavailable'].includes(row.state)
        ||value?.session_id!==row.sessionId||value?.submission_id!==row.submissionId||typeof value.found!=='boolean')
        throw new TaskError(409,'Native lookup is not this saved submission.');
      if(!value.found)return {...row,state:row.admissionId?'unavailable':'submit_unknown'};
      const receipt=value.receipt;
      const rawGeneration=receipt?.execution_generation??null,generation=rawGeneration===0?null:rawGeneration;
      if(!admission(receipt?.admission_id)||row.admissionId&&row.admissionId!==receipt.admission_id
        ||receipt?.ref?.session_id!==row.sessionId||typeof receipt?.ref?.profile_id!=='string'||!receipt.ref.profile_id
        ||row.nativeProfileId&&row.nativeProfileId!==receipt.ref.profile_id
        ||!Number.isSafeInteger(receipt.authority_epoch)||receipt.authority_epoch<1
        ||row.nativeEpoch!==null&&row.nativeEpoch!==receipt.authority_epoch
        ||!['queued','started','terminal','unknown'].includes(receipt.status)
        ||rawGeneration!==null&&(!Number.isSafeInteger(rawGeneration)||rawGeneration<0)
        ||row.nativeGeneration!==null&&generation!==row.nativeGeneration)
        throw new TaskError(409,'Native admission identity changed; keep the workspace held.');
      return {...row,state:'observed',admissionId:receipt.admission_id,nativeStatus:receipt.status,nativeGeneration:generation,nativeProfileId:receipt.ref.profile_id,nativeEpoch:receipt.authority_epoch};
    }),
    unavailable:(taskId,sendId,revision)=>change(taskId,sendId,revision,row=>{
      if(['create_pending','create_unknown'].includes(row.state))return {...row,state:'create_unknown'};
      if(['submit_pending','submit_unknown','observed','unavailable'].includes(row.state))return {...row,state:row.admissionId?'unavailable':'submit_unknown'};
      throw new TaskError(409,'No native delivery is pending.');
    })};
}

// Trusted service entry only. The server does not enroll or select a live transport here.
export async function dispatchLocalSession({workroom,taskId,body,profile,rpc,credential,admitted}){
  if(typeof rpc!=='function'||typeof credential!=='function'||typeof admitted!=='function'||admitted()!==true)
    throw new TaskError(403,'An active dedicated worker transport is required.');
  const send=workroom.localSessions.reserve(taskId,body,profile),store=workroom.localSessions;
  let row=store.read(taskId,send.id);
  const active=()=>{if(admitted()!==true)throw new TaskError(403,'Dedicated worker access ended.');};
  try{
    if(['prepared','create_pending','create_unknown'].includes(row.state)){
      if(row.state==='prepared')row=store.startCreate(taskId,send.id,row.revision);
      const key=await credential(row.profile.identityRef);active();
      if(typeof key!=='string'||!key.trim())throw new TaskError(503,'Dedicated worker credential is unavailable.');
      const created=await rpc('session.create',{request_id:row.createRequestId,source:'tool',model:row.profile.model,
        provider:'custom',base_url:row.profile.baseUrl,api_key:key,toolsets:['file'],safe_mode:true,ignore_rules:true,
        cwd:row.profile.workspace,max_turns:50});active();
      row=store.bindSession(taskId,send.id,row.revision,created);
    }
    if(row.state==='session_bound'){
      active();row=store.startSubmit(taskId,send.id,row.revision);
      await rpc('prompt.submit',{session_id:row.sessionId,submission_id:row.submissionId,text:send.payload,finite:true});active();
    }
    const receipt=await rpc('prompt.lookup',{session_id:row.sessionId,submission_id:row.submissionId});active();
    return store.observe(taskId,send.id,row.revision,receipt);
  }catch(error){
    try{store.unavailable(taskId,send.id,row.revision);}catch(conflict){if(conflict.status!==409)throw conflict;}
    if(error.status===403||error.status===409)throw error;
    throw new TaskError(503,'Native delivery is uncertain. Reconcile the saved IDs; do not start another worker.');
  }
}

// Observation never reserves, creates, submits, or selects a replacement profile.
// A trusted caller may keep this read permission after orchestration has paused.
export async function reconcileLocalSession({workroom,taskId,sendId,rpc,authorized}){
  const active=row=>{
    if(typeof rpc!=='function'||typeof authorized!=='function'||authorized(row.profile)!==true)
      throw new TaskError(403,'Dedicated worker observation is not authorized.');
  };
  const store=workroom.localSessions;
  let row=store.read(taskId,sendId);
  if(!row)throw new TaskError(404,'No saved native binding exists.');
  active(row);
  if(!row.sessionId||!['submit_pending','submit_unknown','observed','unavailable'].includes(row.state))
    return row;
  try{
    const value=await rpc('prompt.lookup',{session_id:row.sessionId,submission_id:row.submissionId});
    active(row);
    return store.observe(taskId,sendId,row.revision,value);
  }catch(error){
    try{store.unavailable(taskId,sendId,row.revision);}catch(conflict){if(conflict.status!==409)throw conflict;}
    if(error.status===403||error.status===409)throw error;
    throw new TaskError(503,'Native observation is unavailable. The saved worker remains held.');
  }
}
