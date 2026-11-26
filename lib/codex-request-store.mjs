import {DatabaseSync} from 'node:sqlite';
import {createHash} from 'node:crypto';

export class CodexRequestError extends Error{
  constructor(status,message){super(message);this.status=status;}
}

// Request receipts only: Codex remains the conversation/history authority.
// A claim is committed before any native call; reopening never dispatches it.
export function openCodexRequestStore(filename){
  const db=new DatabaseSync(filename);
  try{
    const version=db.prepare('PRAGMA user_version').get().user_version;
    const tables=db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").all();
    if(version!==0&&version!==1||version===0&&tables.length||version===1&&(tables.length!==1||tables[0].name!=='codex_requests'))throw Error('Unrecognized native request store; preserve it.');
    if(version===1){
      const columns=db.prepare('PRAGMA table_info(codex_requests)').all().map(v=>v.name).join(',');
      if(columns!=='request_id,scope_key,kind,target_id,payload_hash,state,native_thread_id,client_thread_id,created_at,updated_at')throw Error('Native request schema changed; preserve it.');
      const index=db.prepare("SELECT sql FROM sqlite_master WHERE type='index' AND name='codex_uncertain_payload'").get()?.sql;
      if(!index||index.replace(/\s+/g,'').toLowerCase()!=="createuniqueindexcodex_uncertain_payloadoncodex_requests(scope_key,kind,target_id,payload_hash)wherestatein('dispatching','unconfirmed')")throw Error('Native duplicate-send guard changed; preserve its receipts.');
    }
    db.exec('PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; PRAGMA busy_timeout=5000;');
    if(version===0)db.exec(`BEGIN IMMEDIATE;
      CREATE TABLE codex_requests(
        request_id TEXT PRIMARY KEY,scope_key TEXT NOT NULL,kind TEXT NOT NULL CHECK(kind IN ('send','new')),
        target_id TEXT NOT NULL,payload_hash TEXT NOT NULL,
        state TEXT NOT NULL CHECK(state IN ('dispatching','accepted','unconfirmed','not_sent')),
        native_thread_id TEXT,client_thread_id TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
      ) STRICT;
      CREATE UNIQUE INDEX codex_uncertain_payload ON codex_requests(scope_key,kind,target_id,payload_hash)
        WHERE state IN ('dispatching','unconfirmed');
      PRAGMA user_version=1; COMMIT;`);
  }catch(error){db.close();throw error;}
  const project=row=>row&&({requestId:row.request_id,kind:row.kind,targetId:row.target_id,payloadHash:row.payload_hash,state:row.state,
    nativeThreadId:row.native_thread_id,clientThreadId:row.client_thread_id,createdAt:row.created_at,updatedAt:row.updated_at});
  function existing(scope,request){
    const row=db.prepare('SELECT * FROM codex_requests WHERE request_id=?').get(request.requestId);
    if(!row)return null;
    if(row.scope_key!==scope||row.kind!==request.kind||row.target_id!==request.targetId||row.payload_hash!==request.hash)
      throw new CodexRequestError(409,'This request ID already belongs to another message. Nothing was sent again.');
    return project(row);
  }
  return {
    existing,
    claim(scope,request){
      const prior=existing(scope,request);if(prior)return {fresh:false,receipt:prior};
      const now=new Date().toISOString();
      try{db.prepare("INSERT INTO codex_requests VALUES(?,?,?,?,?,'dispatching',NULL,NULL,?,?)").run(request.requestId,scope,request.kind,request.targetId,request.hash,now,now);}
      catch(error){
        const raced=existing(scope,request);if(raced)return {fresh:false,receipt:raced};
        const uncertain=db.prepare("SELECT request_id FROM codex_requests WHERE scope_key=? AND kind=? AND target_id=? AND payload_hash=? AND state IN ('dispatching','unconfirmed')").get(scope,request.kind,request.targetId,request.hash);
        if(uncertain)throw new CodexRequestError(409,'That message has an unconfirmed send. Check the Codex conversation before trying it again.');
        throw error;
      }
      return {fresh:true,receipt:existing(scope,request)};
    },
    finish(scope,id,state,{nativeThreadId=null,clientThreadId=null}={}){
      if(!['accepted','unconfirmed','not_sent'].includes(state))throw Error('Invalid native receipt state.');
      const result=db.prepare("UPDATE codex_requests SET state=?,native_thread_id=?,client_thread_id=?,updated_at=? WHERE scope_key=? AND request_id=? AND state='dispatching'")
        .run(state,nativeThreadId,clientThreadId,new Date().toISOString(),scope,id);
      if(result.changes!==1)throw Error('Native receipt could not be finalized; preserve its original claim.');
      return project(db.prepare('SELECT * FROM codex_requests WHERE scope_key=? AND request_id=?').get(scope,id));
    },
    knowsNativePrompt(scope,threadId,name,text){
      if(name==='create_thread')return Boolean(db.prepare("SELECT 1 FROM codex_requests WHERE scope_key=? AND kind='new' AND state='accepted' AND native_thread_id=?").get(scope,threadId));
      if(name!=='send_message_to_thread')return false;
      const digest=createHash('sha256').update(JSON.stringify(['send',threadId,text])).digest('hex');
      return Boolean(db.prepare("SELECT 1 FROM codex_requests WHERE scope_key=? AND kind='send' AND target_id=? AND payload_hash=? AND state IN ('accepted','dispatching','unconfirmed')").get(scope,threadId,digest));
    },
    get(scope,id){return project(db.prepare('SELECT * FROM codex_requests WHERE scope_key=? AND request_id=?').get(scope,id))??null;},
    close(){db.close();}
  };
}
