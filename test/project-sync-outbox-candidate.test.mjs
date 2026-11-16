import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {DatabaseSync} from 'node:sqlite';
import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {openTaskStore} from '../lib/task-store.mjs';
import {initializeProjectOutbox,ProjectOutboxCandidate} from '../integrations/project-sync-outbox-candidate.mjs';

function fixture(t,storeId='synthetic-store') {
  const dir=mkdtempSync(join(tmpdir(),'mesh-outbox-'));
  const filename=join(dir,'tasks.sqlite');
  const store=openTaskStore(filename);
  const card=store.create({title:'Synthetic guide',description:'Write a guide',label:'',status:'open'});
  store.close();
  let db=new DatabaseSync(filename);
  db.exec('PRAGMA foreign_keys=ON');
  initializeProjectOutbox(db);
  function reader(cardId) {
    const row=db.prepare('SELECT * FROM tasks WHERE id=?').get(cardId);
    return {revisions:{task:row.revision,brief:0,progress:0},
      snapshot:{title:row.title,goal:row.description,owner:'nims',stage:'backlog',result:'',blocker:''},evidence:[]};
  }
  let queue=new ProjectOutboxCandidate(db,{storeId,readSnapshot:reader});
  const transaction=fn=>{db.exec('BEGIN IMMEDIATE');try{const value=fn();db.exec('COMMIT');return value;}catch(e){db.exec('ROLLBACK');throw e;}};
  transaction(()=>queue.linkCard(card.id,'project-A','synthetic-owner-approved-fields'));
  t.after(()=>{db.close();rmSync(dir,{recursive:true,force:true});});
  return {card,filename,transaction,get db(){return db;},get queue(){return queue;},
    capture:()=>transaction(()=>queue.capture(card.id,'created')),
    reopen:()=>{db.close();db=new DatabaseSync(filename);queue=new ProjectOutboxCandidate(db,{storeId,readSnapshot:reader});}};
}

async function mind(t,persistentRoot=null) {
  const child=spawn('python',['-B',resolve('test/project-sync-mind-fixture.py'),
    process.env.MIND_CANDIDATE_SOURCE || 'D:/Dev/Onoes-Mind',...(persistentRoot?[persistentRoot]:[])],{windowsHide:true,stdio:['pipe','pipe','pipe']});
  const terminal=new Promise(resolve=>child.once('exit',(code,signal)=>resolve({code,signal})));
  let stderr='';child.stderr.on('data',data=>{stderr+=data;});
  const lines=createInterface({input:child.stdout});
  const iterator=lines[Symbol.asyncIterator]();
  async function read(){const row=await iterator.next();assert.equal(row.done,false,stderr);return JSON.parse(row.value);}
  const {storeId}=await read();
  const rpc=async command=>{child.stdin.write(JSON.stringify(command)+'\n');return read();};
  const close=async()=>{if(child.exitCode===null&&child.signalCode===null){await rpc({op:'close'});child.stdin.end();}await terminal;lines.close();};
  t.after(close);
  return {storeId,rpc,terminal,close,transport:{lookup:q=>rpc({op:'lookup',...q}),submit:event=>rpc({op:'submit',event})}};
}

function absence(storeId,event) {return {schema:'onoes-mind-project-absence/v1',storeId,
  scope:'project/onoes-mind/shared',principal:'mesh-project-sync',eventId:event.eventId,
  projectId:'project-A',found:false};}

test('card mutation and queue insertion commit or roll back together', t=>{
  const f=fixture(t);
  assert.throws(()=>f.queue.capture(f.card.id,'created'),/transaction/);
  assert.throws(()=>f.transaction(()=>{f.db.prepare('UPDATE tasks SET title=?,revision=revision+1 WHERE id=?').run('Unsaved',f.card.id);f.queue.capture(f.card.id,'created');throw Error('rollback');}));
  assert.equal(f.db.prepare('SELECT title FROM tasks').get().title,'Synthetic guide');
  assert.equal(f.queue.status(f.card.id).length,0);
  f.capture();f.reopen();assert.equal(f.queue.status(f.card.id)[0].state,'pending');
});

test('real Node queue reaches canonical Python records and durable receipts',async t=>{
  const m=await mind(t), f=fixture(t,m.storeId);
  f.transaction(()=>{f.db.prepare('UPDATE tasks SET title=? WHERE id=?').run('Guide café 🚀',f.card.id);f.queue.capture(f.card.id,'created');});
  assert.equal((await f.queue.drainOne(m.transport)).state,'saved');
  assert.deepEqual(await m.rpc({op:'stats'}),{records:1,receipts:1});
  assert.equal(f.queue.status(f.card.id)[0].state,'saved');
});

test('lost reply after Mind commit recovers exact receipt after Mesh queue restart',async t=>{
  const m=await mind(t), f=fixture(t,m.storeId);const eventId=f.capture();let sends=0;
  const transport={...m.transport,submit:async event=>{sends++;await m.transport.submit(event);throw Error('lost response');}};
  assert.equal((await f.queue.drainOne(transport)).state,'uncertain');
  f.reopen();assert.equal((await f.queue.drainOne(transport)).state,'saved');
  assert.equal(sends,1);assert.equal(f.queue.status(f.card.id)[0].eventId,eventId);
  assert.deepEqual(await m.rpc({op:'stats'}),{records:1,receipts:1});
});

test('offline lookup stays uncertain and makes no submit',async t=>{
  const f=fixture(t);f.capture();let sends=0;
  const outcome=await f.queue.drainOne({lookup:async()=>{throw Error('offline');},submit:async()=>{sends++;}});
  assert.equal(outcome.state,'uncertain');assert.equal(sends,0);f.reopen();assert.equal(f.queue.status(f.card.id)[0].state,'uncertain');
});

test('unproven absence and forged receipts hold instead of claiming success',async t=>{
  for(const reply of [null,{}, {found:false}]) {
    const f=fixture(t);f.capture();let sends=0;
    assert.equal((await f.queue.drainOne({lookup:async()=>reply,submit:async()=>{sends++;}})).state,'held');
    assert.equal(sends,0);
  }
});

test('wrong-store receipt is refused after actual successful Mind commit',async t=>{
  const m=await mind(t),f=fixture(t,m.storeId);f.capture();
  const transport={...m.transport,submit:async event=>({...await m.transport.submit(event),storeId:'wrong-store'})};
  assert.equal((await f.queue.drainOne(transport)).state,'held');
  assert.equal(f.queue.status(f.card.id)[0].reason,'invalid_receipt');
});

test('withdrawing while lookup waits prevents a later submit',async t=>{
  const f=fixture(t);const eventId=f.capture();let release;let sends=0;
  const pending=f.queue.drainOne({lookup:()=>new Promise(r=>{release=r;}),submit:async()=>{sends++;}});
  f.transaction(()=>f.queue.withdraw(f.card.id));
  release(absence('synthetic-store',{eventId}));
  assert.equal((await pending).state,'held');assert.equal(sends,0);
  assert.equal(f.queue.status(f.card.id)[0].reason,'sharing_withdrawn');
});

test('tampered local payload is held before any transport contact',async t=>{
  const f=fixture(t);f.capture();
  f.db.prepare("UPDATE mind_project_outbox SET payload=replace(payload,'Write a guide','Changed text')").run();let calls=0;
  assert.equal((await f.queue.drainOne({lookup:async()=>{calls++;},submit:async()=>{calls++;}})).state,'held');
  assert.equal(calls,0);assert.equal(f.queue.status(f.card.id)[0].reason,'invalid_local_event');
});

test('outbox cannot silently adopt another Mind store',t=>{
  const f=fixture(t);assert.throws(()=>new ProjectOutboxCandidate(f.db,{storeId:'different-store',readSnapshot:()=>({})}),/binding mismatch/);
});

test('next committed card revision produces an ordered replacement snapshot',async t=>{
  const m=await mind(t),f=fixture(t,m.storeId);f.capture();
  assert.equal((await f.queue.drainOne(m.transport)).state,'saved');
  f.transaction(()=>{f.db.prepare('UPDATE tasks SET description=?,revision=revision+1 WHERE id=?').run('Revised guide goal',f.card.id);f.queue.capture(f.card.id,'progress');});
  assert.equal((await f.queue.drainOne(m.transport)).state,'saved');
  assert.deepEqual(f.queue.status(f.card.id).map(r=>r.sequence),[1,2]);
  assert.deepEqual(await m.rpc({op:'stats'}),{records:2,receipts:2});
});

test('held first event prevents sending later revisions of that card',async t=>{
  const f=fixture(t);f.capture();
  f.transaction(()=>{f.db.prepare('UPDATE tasks SET revision=revision+1 WHERE id=?').run(f.card.id);f.queue.capture(f.card.id,'progress');});
  await f.queue.drainOne({lookup:async()=>null,submit:async()=>assert.fail('must not submit')});
  assert.equal((await f.queue.drainOne({lookup:async()=>assert.fail('held predecessor'),submit:async()=>assert.fail('must not submit')})).state,'idle');
  assert.deepEqual(f.queue.status(f.card.id).map(r=>r.state),['held','pending']);
});

test('withdrawal after a successful remote commit never displays saved',async t=>{
  const m=await mind(t),f=fixture(t,m.storeId);f.capture();
  const transport={...m.transport,submit:async event=>{const receipt=await m.transport.submit(event);f.transaction(()=>f.queue.withdraw(f.card.id));return receipt;}};
  assert.equal((await f.queue.drainOne(transport)).state,'held');
  assert.equal(f.queue.status(f.card.id)[0].reason,'sharing_withdrawn');
  assert.deepEqual(await m.rpc({op:'stats'}),{records:1,receipts:1});
});

test('removed-record receipt holds the event rather than claiming saved',async t=>{
  const m=await mind(t),f=fixture(t,m.storeId);f.capture();
  const transport={...m.transport,submit:async event=>({...await m.transport.submit(event),recordState:'purged'})};
  assert.equal((await f.queue.drainOne(transport)).state,'held');
  assert.equal(f.queue.status(f.card.id)[0].reason,'record_removed');
});

test('a repeated source revision cannot silently create another delivery',t=>{
  const f=fixture(t);f.capture();
  assert.throws(()=>f.transaction(()=>f.queue.capture(f.card.id,'progress')),/revision did not advance/);
  assert.equal(f.queue.status(f.card.id).length,1);
});

test('owned Mind process dies after commit; reopened receiver and queue reconcile without resubmit',async t=>{
  const root=mkdtempSync(join(tmpdir(),'mesh-project-sync-process-'));let first,second;
  try {
    first=await mind(t,root);const f=fixture(t,first.storeId);const eventId=f.capture();
    const transport={...first.transport,submit:event=>first.rpc({op:'submit_then_exit',event})};
    assert.equal((await f.queue.drainOne(transport)).state,'uncertain');
    assert.equal((await first.terminal).code,73);
    f.reopen();second=await mind(t,root);assert.equal(second.storeId,first.storeId);let sends=0;
    const recovered={...second.transport,submit:async event=>{sends++;return second.transport.submit(event);}};
    assert.equal((await f.queue.drainOne(recovered)).state,'saved');
    assert.equal(sends,0);assert.equal(f.queue.status(f.card.id)[0].eventId,eventId);
    assert.deepEqual(await second.rpc({op:'stats'}),{records:1,receipts:1});
  } finally {
    if(first)await first.close();if(second)await second.close();rmSync(root,{recursive:true,force:true});
  }
});
