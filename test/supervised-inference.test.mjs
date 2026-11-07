import test from 'node:test';
import assert from 'node:assert/strict';
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
