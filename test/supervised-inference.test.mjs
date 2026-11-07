import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {supervisedModelFixture} from './supervised-model-fixture.mjs';
const fixture=supervisedModelFixture;
const propose=async(c,action='load',admitted=()=>true)=>(await c.propose(action,{},'owner',admitted)).proposal;
const approve=(c,p,admitted=()=>true)=>c.approve({proposalId:p.id,confirm:true},'owner',admitted);
test('propose does no work; confirm persists one operation and polls to completion before verified model/chat controls',async()=>{
  const f=fixture(),c=f.make();assert.equal((await c.status()).controls.load,true);
  const p=await propose(c);assert.equal(f.calls.length,0);const ack=await approve(c,p);assert.equal(f.calls.length,1);assert.equal(ack.receipt.state,'ACCEPTED');
  await assert.rejects(approve(c,p));assert.equal(f.calls.length,1);
  assert.equal((await c.status()).state,'STARTING');f.finish(ack.receipt.id);
  const s=await c.status();assert.equal(s.state,'RUNNING');assert.equal(s.controls.chat,true);assert.equal(s.operation.readBackVerified,true);
  assert.equal((await c.chat({prompt:'hello'},()=>true)).response,'Fixture answer');
  const stop=await approve(c,await propose(c,'stop'));f.finish(stop.receipt.id);assert.equal((await c.status()).state,'STOPPED');
  await c.close();f.db.close();
});
test('lost acceptance and app restart reconcile the same original receipt, never another POST',async()=>{
  const f=fixture();let c=f.make();f.loseDelivery();const ack=await approve(c,await propose(c));assert.equal(ack.receipt.state,'UNKNOWN');
  await c.close();c=f.make();assert.equal((await c.status()).state,'STARTING');assert.equal(f.calls.length,1);
  f.loseRead(true);assert.equal((await c.status()).state,'UNKNOWN');assert.equal(f.operations.unresolved().length,1);
  await assert.rejects(propose(c));assert.equal(f.calls.length,1);f.loseRead(false);f.finish(ack.receipt.id);
  assert.equal((await c.status()).state,'RUNNING');assert.equal(f.calls.length,1);await c.close();f.db.close();
});
test('stale/session/admission/edited proposal fails without model work',async()=>{
  const f=fixture(),c=f.make();await assert.rejects(c.propose('load',{path:'elsewhere'},'owner',()=>true));
  const p=await propose(c);await assert.rejects(c.approve({proposalId:p.id,confirm:true},'another',()=>true));
  await assert.rejects(approve(c,p,()=>false));assert.equal(f.calls.length,0);
  f.advance(30001);await assert.rejects(approve(c,p));assert.equal(f.calls.length,0);await c.close();f.db.close();
});
test('a verified owner remains stoppable when health/GPU proof fails; uncertain ownership never is',async()=>{
  const f=fixture(),c=f.make();const ack=await approve(c,await propose(c));f.finish(ack.receipt.id);f.unverify();
  let s=await c.status();assert.equal(s.state,'OWNED');assert.equal(s.controls.stop,true);assert.equal(s.controls.chat,false);
  f.setNative({...f.getNative(),owner:{state:'uncertain'},unload:true});s=await c.status();assert.equal(s.controls.stop,false);
  await c.close();f.db.close();
});
test('no-dispatch refusal releases the reservation; accepted/unknown work remains exclusive',async()=>{
  const f=fixture(),c=f.make();f.client.command=async()=>{throw Object.assign(Error(),{code:'OWNER_CHANGED',notSent:true});};
  const ack=await approve(c,await propose(c));assert.equal(ack.receipt.state,'REFUSED');assert.equal(f.operations.unresolved().length,0);assert.equal(f.calls.length,0);
  assert.equal((await c.status()).controls.load,true);await c.close();f.db.close();
});
test('explicit recovery after missing receipt/new boot fences the original request and preserves UNKNOWN',async()=>{
  const f=fixture();let c=f.make();const ack=await approve(c,await propose(c));await c.close();
  f.receipts.clear();f.setNative({...f.getNative(),bootId:randomUUID(),active:null});c=f.make();
  let s=await c.status();assert.equal(s.state,'UNKNOWN');assert.equal(s.controls.recover,true);assert.equal(s.controls.load,false);
  const recovery=await propose(c,'recover');assert.equal(f.recoveries.length,0);assert.equal(f.calls.length,1);
  assert.equal(JSON.stringify(recovery).includes('expected'),false);
  await assert.rejects(c.approve({proposalId:recovery.id,confirm:true},'other',()=>true));
  const result=await approve(c,recovery);assert.equal(result.receipt.state,'UNKNOWN');assert.equal(result.receipt.reason,'OUTCOME_FENCED');
  assert.equal(result.receipt.readBackVerified,false);assert.equal(f.operations.unresolved().length,0);assert.equal(f.recoveries.length,1);assert.equal(f.calls.length,1);
  await c.close();c=f.make();s=await c.status();assert.equal(s.state,'STOPPED');assert.equal(s.controls.load,true);assert.equal(s.operation.reason,'OUTCOME_FENCED');
  assert.equal(f.calls.length,1);await c.close();f.db.close();
});
test('active or uncertain owner cannot be recovered; stale and expired recovery confirmation never dispatches',async()=>{
  const f=fixture(),c=f.make();await approve(c,await propose(c));f.receipts.clear();
  assert.equal((await c.status()).controls.recover,false);await assert.rejects(propose(c,'recover'));
  f.setNative({...f.getNative(),active:null,owner:{state:'uncertain'}});assert.equal((await c.status()).controls.recover,false);
  f.setNative({...f.getNative(),owner:{state:'empty',identity:null,clear:true}});const p=await propose(c,'recover');
  f.advance(30001);await assert.rejects(approve(c,p));assert.equal(f.recoveries.length,0);assert.equal(f.operations.unresolved().length,1);
  await c.close();f.db.close();
});
test('lost fencing response stays blocked through reads/restart until a separate explicit confirmation retrieves the same proof',async()=>{
  const f=fixture();f.client.command=async()=>{throw Object.assign(Error(),{code:'BRIDGE_UNAVAILABLE'});};
  let c=f.make();await approve(c,await propose(c));const originalRecover=f.client.recover;let saved,recoveryPosts=0;
  f.client.recover=async(...args)=>{recoveryPosts++;if(saved)return saved;saved=await originalRecover(...args);throw Object.assign(Error(),{code:'BRIDGE_UNAVAILABLE'});};
  const first=await approve(c,await propose(c,'recover'));assert.equal(first.receipt.state,'UNKNOWN');assert.equal(f.operations.unresolved().length,1);
  await c.status();await c.status();assert.equal(recoveryPosts,1);await c.close();c=f.make();await c.status();assert.equal(recoveryPosts,1);
  assert.equal((await c.status()).controls.load,false);await approve(c,await propose(c,'recover'));
  assert.equal(recoveryPosts,2);assert.equal(f.recoveries.length,1);assert.equal(f.operations.unresolved().length,0);assert.equal(f.operations.latest().reason,'OUTCOME_FENCED');assert.equal(f.calls.length,0);
  await c.close();f.db.close();
});
