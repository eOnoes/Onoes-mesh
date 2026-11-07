import test from 'node:test';
import assert from 'node:assert/strict';
import {agentWorkspace,agentObservationLabel} from '../public/agent-workspace.mjs';

test('agent workspace links exact peer receipts while preserving historical sessions and pending review', () => {
  const snapshot = {agents:[{id:'deep',name:'Deep',backend:'a2a',status:'done',conversation_id:'new',approval:null}]};
  const tasks = [
    {id:'one',title:'Current task',progress:{decision:'pending'},messages:[{agentId:'deep',conversationId:'new',phase:'work',state:'accepted'}]},
    {id:'two',title:'Old task',messages:[{agentId:'deep',conversationId:'old',phase:'review',state:'accepted'}]},
    {id:'other',title:'Different peer',messages:[{agentId:'echo',conversationId:'new',phase:'work',state:'accepted'}]}
  ];
  const [row] = agentWorkspace(snapshot,tasks);
  assert.equal(row.status,'done');
  assert.deepEqual(row.tasks.map(t=>[t.id,t.sameSession,t.decision]),[['one',true,'pending'],['two',false,'pending']]);
  assert.equal(tasks[0].progress.decision,'pending');
  assert.deepEqual(agentWorkspace(undefined,tasks),[]);
  assert.equal(agentWorkspace({agents:[{id:'no-session'}]},tasks)[0].session,null);
});


test('agent roster check time comes from its observation and never from repaint time',()=>{
  const snapshot={observedAt:'2026-11-07T19:00:00.000Z'};
  const label=agentObservationLabel(snapshot);
  assert.match(label,/Relay roster read at 2026-11-07T19:00:00.000Z/);
  assert.match(label,/Saved observation; refresh/);
  assert.equal(agentObservationLabel(snapshot),label);
  for(const observedAt of [undefined,null,'invalid',42]){
    assert.match(agentObservationLabel({observedAt}),/check time unavailable/);
    assert.doesNotMatch(agentObservationLabel({observedAt}),/read at/);
  }
});
