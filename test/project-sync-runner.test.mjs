import test from 'node:test';
import assert from 'node:assert/strict';
import {createProjectSyncRunner} from '../integrations/project-sync-runner-candidate.mjs';

function clock(){
  const timers=new Map();let next=0;
  return {timers,schedule(fn,delay){const id=++next;timers.set(id,{fn,delay});return id;},
    cancel(id){timers.delete(id);},fire(){const [id,entry]=timers.entries().next().value;timers.delete(id);entry.fn();}};
}
const transport={lookup(){},submit(){}};
function deferred(){let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};}

test('construction is inert; repeated start has one timer; passes are bounded',async()=>{
  const c=clock();let calls=0;
  const outbox={async drainOne(){calls++;return {state:'saved'};}};
  const r=createProjectSyncRunner({outbox,transport,...c,maxPerPass:2});
  assert.equal(c.timers.size,0);assert.equal(calls,0);
  r.start();r.start();assert.equal(c.timers.size,1);assert.equal([...c.timers.values()][0].delay,0);
  c.fire();await r.runOnce();assert.equal(calls,2);assert.equal(c.timers.size,1);
  assert.equal([...c.timers.values()][0].delay,5000);
  await r.stop();assert.equal(c.timers.size,0);assert.equal(r.status().state,'stopped');
  await r.runOnce();assert.equal(calls,2);assert.throws(()=>r.start());
});

test('concurrent passes coalesce and stop waits for exact in-flight operation',async()=>{
  const c=clock(),gate=deferred();let calls=0;
  const outbox={async drainOne(){calls++;await gate.promise;return {state:'saved'};}};
  const r=createProjectSyncRunner({outbox,transport,...c});r.start();
  const first=r.runOnce();assert.equal(r.runOnce(),first);await Promise.resolve();assert.equal(calls,1);
  const stopping=r.stop();assert.equal(stopping,first);
  assert.throws(()=>createProjectSyncRunner({outbox,transport,...c}));
  gate.resolve();await stopping;assert.equal(calls,1);assert.equal(c.timers.size,0);
  const replacement=createProjectSyncRunner({outbox,transport,...c});await replacement.stop();
});

test('unknown delivery backs off without a hot retry and recovery resets delay',async()=>{
  const c=clock();let state='uncertain',calls=0;
  const r=createProjectSyncRunner({outbox:{async drainOne(){calls++;return {state};}},transport,
    ...c,intervalMs:100,maxBackoffMs:400});r.start();
  await r.runOnce();assert.equal(calls,1);assert.equal(r.status().retryInMs,200);
  await r.runOnce();assert.equal(r.status().retryInMs,400);
  await r.runOnce();assert.equal(r.status().retryInMs,400);
  state='idle';await r.runOnce();assert.equal(r.status().retryInMs,100);
  await r.stop();
});

test('held card does not stop unrelated cards; busy never spins',async()=>{
  const c=clock(),states=['held','saved','busy'];let calls=0;
  const r=createProjectSyncRunner({outbox:{async drainOne(){calls++;return {state:states.shift()};}},transport,...c});
  r.start();await r.runOnce();assert.equal(calls,3);assert.equal(r.status().lastState,'busy');
  assert.equal(r.status().retryInMs,10000);await r.stop();
});

test('failures expose only a fixed local status; invalid limits are refused',async()=>{
  const c=clock(),outbox={async drainOne(){throw Error('synthetic private diagnostic');}};
  const r=createProjectSyncRunner({outbox,transport,...c});r.start();await r.runOnce();
  assert.deepEqual(r.status(),{state:'running',lastState:'unavailable',retryInMs:10000});await r.stop();
  for(const config of [{intervalMs:0},{maxPerPass:0},{maxBackoffMs:1}]){
    assert.throws(()=>createProjectSyncRunner({outbox,transport,...config}));
  }
});
