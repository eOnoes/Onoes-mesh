import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {startApp} from '../server.mjs';
import {taskTimeline} from '../public/workroom-status.mjs';

test('actual saved progress survives readback and appears in the timeline without approval or inferred work',async()=>{
  const app=await startApp({dataDir:'data/progress-timeline-'+randomUUID(),relayEnabled:false});
  try{
    const admission=await fetch(app.url+'/api/trial-session/bootstrap',{method:'POST',headers:{Origin:app.url,'Content-Type':'application/json'},body:'{}'});
    assert.equal(admission.status,201);const {csrfToken}=await admission.json();
    const headers={Origin:app.url,'Content-Type':'application/json',Cookie:admission.headers.get('set-cookie').split(';')[0],'X-Trial-CSRF':csrfToken};
    const api=async(path,method='GET',body)=>{const r=await fetch(app.url+path,{method,headers,...(body?{body:JSON.stringify(body)}:{})});assert.ok(r.ok,'HTTP '+r.status);return r.json();};
    const {task:created}=await api('/api/tasks','POST',{title:'Progress timeline fixture'});let {task}=await api('/api/workroom/'+created.id);
    for(const status of ['working','done']){
      ({task}=await api('/api/workroom/'+task.id+'/progress','PATCH',{goal:'Inspect one local flow',checklist:[{id:'inspect',text:'Inspect the flow',status}],result:'Saved report; review remains pending',evidence:'Local fixture readback',reviewer:'',decision:'pending',revision:task.progress.revision,taskRevision:task.revision,briefRevision:task.workroom.revision}));
    }
    ({task}=await api('/api/workroom/'+task.id));const before=JSON.stringify(task),events=taskTimeline(task),saved=task.history.filter(h=>h.kind==='progress_saved');
    assert.equal(saved.length,2);assert.deepEqual(events.filter(e=>e.label==='Progress saved').map(e=>e.id),saved.map(h=>'history-'+h.seq));
    assert.match(events.find(e=>e.id==='history-'+saved[1].seq).detail,/1\/1 steps done/);
    assert.equal(task.progress.decision,'pending');assert.notEqual(task.status,'done');assert.equal(task.messages.length,0);
    assert.equal(events.some(e=>/approved|Moved to Done|Worker assigned/.test(e.label)),false);assert.equal(JSON.stringify(task),before);
  }finally{await app.close();}
});

test('same-time saved history follows its numeric sequence without inventing events from current progress',()=>{
  const at='2026-11-07T00:00:00Z';
  assert.deepEqual(taskTimeline({history:[{seq:10,kind:'progress_saved',at,detail:'later'},{seq:2,kind:'progress_saved',at,detail:'earlier'}]}).map(e=>e.id),['history-2','history-10']);
  assert.deepEqual(taskTimeline({progress:{goal:'No history',decision:'pending'}}),[]);
});
