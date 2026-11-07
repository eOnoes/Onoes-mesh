import test from 'node:test';
import assert from 'node:assert/strict';
import {agentWorkspace,agentObservationLabel,agentAssignmentLabel,agentCapabilityLabel} from '../public/agent-workspace.mjs';
import {automationPolicy} from '../lib/workroom-automation-store.mjs';

test('adapter capability observations distinguish read-only review from coding and unknown peers',()=>{
  const capabilities={plan:true,review:true,work:false,mode:'read-only'};
  const label=agentCapabilityLabel(capabilities);
  assert.match(label,/Adapter reports: planning, review\./);
  assert.match(label,/Unavailable: building\./);
  assert.match(label,/Read-only connection/);
  assert.match(label,/Saved observation/);
  for(const value of [undefined,{}, {...capabilities,work:'true'}, {...capabilities,plan:null}]){
    assert.match(agentCapabilityLabel(value),/not declared/);
  }
  assert.match(agentCapabilityLabel({plan:false,review:false,work:false}),/no task roles/);
  assert.equal(agentWorkspace({agents:[{id:'nims',capabilities}]},[])[0].capabilities,capabilities);
});

test('Agent role labels use enforced policy and never infer connection or coding access',()=>{
  const policy=automationPolicy('C:/Qualified Mesh');
  assert.match(agentAssignmentLabel('echo',policy),/role: builder\./);
  for(const id of ['dsh','nims']) assert.match(agentAssignmentLabel(id,policy),/role: reviewer\./);
  assert.ok(agentAssignmentLabel('echo',policy).includes(`Workspace: ${policy.workspace}. Limit: 50 actions`));
  assert.match(agentAssignmentLabel('echo',policy),/not proof of current coding access/);
  assert.match(agentAssignmentLabel('tripp',policy),/No automatic build or review role/);
  for(const invalid of [null,{}, {...policy,schema:'other'}, {...policy,actionLimit:500}, {...policy,workspace:''}, {...policy,builderIds:[{}]}]){
    assert.match(agentAssignmentLabel('echo',invalid),/roles unavailable/);
  }
});

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
  assert.deepEqual(row.tasks.map(t=>t.sessionRelation),['matches observed session','historical session']);
  assert.deepEqual(agentWorkspace(undefined,tasks),[]);
  assert.equal(agentWorkspace({agents:[{id:'no-session'}]},tasks)[0].session,null);
});

test('missing observed or saved session never implies a historical handoff',()=>{
  for(const [observed,saved] of [[null,'old'],['new',null],[null,null]]){
    const [row]=agentWorkspace({agents:[{id:'echo',conversation_id:observed}]},[
      {id:'task',messages:[{agentId:'echo',conversationId:saved,state:'accepted'}]}
    ]);
    assert.equal(row.tasks[0].sessionRelation,'session comparison unavailable');
    assert.equal(row.tasks[0].sameSession,false);
    assert.equal(row.tasks[0].decision,'pending');
  }
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
