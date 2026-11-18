import test from 'node:test';
import assert from 'node:assert/strict';
import {workroomGuide} from '../public/workroom-guide.mjs';
import {randomUUID} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {startApp} from '../server.mjs';

const text=policy=>workroomGuide(policy).flat().join(' ');

test('managed board help explains intake and owner acceptance rather than manual handoff controls',()=>{
  const guide=text({simpleFlow:true});
  assert.match(guide,/Ideas stay unassigned/);
  assert.match(guide,/Work on this/);
  assert.match(guide,/Accept result/);
  assert.match(guide,/Request changes/);
  assert.doesNotMatch(guide,/Choose Nims or Echo|Team handoffs|Start this worker|Record the review/);
});

test('manual board help distinguishes moving a card from explicitly starting work',()=>{
  const guide=text({simpleFlow:false});
  assert.match(guide,/Choose Nims or Echo/);
  assert.match(guide,/does not start an agent/);
  assert.match(guide,/Start this worker/);
  assert.match(guide,/record the review before moving to Done/);
  assert.doesNotMatch(guide,/Accept result/);
});

test('paused help never instructs a send and explains that moving cannot bypass maintenance',()=>{
  for(const simpleFlow of [true,false]){
    const guide=text({simpleFlow,dispatch:{state:'paused'}});
    assert.match(guide,/Team requests are paused/);
    assert.match(guide,/does not bypass that pause/);
    assert.match(guide,/do not resend work whose outcome is unknown/);
    assert.doesNotMatch(guide,/Start this worker sends/);
  }
});

test('help before board load does not invent the mode or claim execution is available',()=>{
  const guide=text(null);
  assert.match(guide,/Connect the workspace first/);
  assert.match(guide,/depends on the connected board/);
  assert.doesNotMatch(guide,/Choose Nims or Echo|Start this worker|queue team assessment/);
  assert.equal(workroomGuide(null).length,7);
});

test('the actual app serves the Help dependency with JavaScript MIME and exact source',async()=>{
  const app=await startApp({dataDir:'data/workroom-guide-http-'+randomUUID(),relayEnabled:false});
  try{
    const response=await fetch(app.url+'/workroom-guide.mjs');
    assert.equal(response.status,200);
    assert.match(response.headers.get('content-type'),/^text\/javascript/);
    assert.equal(await response.text(),await readFile(new URL('../public/workroom-guide.mjs',import.meta.url),'utf8'));
  }finally{await app.close();}
});
