import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {resolve} from 'node:path';
import {makeLegacyRecoveryPlan,makeCurrentBootLegacyRecoveryPlan,assessLegacyRecovery,legacyRecoveryFingerprint} from '../lib/workroom-legacy-evidence.mjs';

const sourceKey='legacyRetirementWitness';
function fixture() {
  const original={workspace:resolve('synthetic-mesh'),databasePath:resolve('synthetic.sqlite'),databaseIdentity:'d'.repeat(64),
    boardSha256:'a'.repeat(64),taskCount:14,host:'SYNTHETIC',machineIdentity:'1'.repeat(64),
    bootedAt:'2026-11-13T01:00:00Z',observedAt:'2026-11-14T01:00:00Z',
    sources:Object.fromEntries(['mesh','relay','hermes','dsh'].map(k=>[k,'a'.repeat(64)])),
    targets:Array.from({length:8},(_,n)=>({sendId:'send-'+n,taskId:'task-'+n,agentId:n<6?'echo':'dsh',state:'accepted',phase:'work',nativeBound:false,fingerprint:'b'.repeat(64)})),
    otherWorkSendIds:[],otherWriterHolds:[]};
  const historical=makeLegacyRecoveryPlan(original),raw=JSON.stringify(historical,null,2)+'\n';
  const current={...structuredClone(original),bootedAt:'2026-11-15T01:00:00Z',observedAt:'2026-11-16T01:00:00Z',
    boardSha256:'c'.repeat(64),taskCount:15,sources:{...original.sources,mesh:'e'.repeat(64),[sourceKey]:createHash('sha256').update(raw).digest('hex')}};
  return {historical,raw,current,plan:()=>makeCurrentBootLegacyRecoveryPlan(current,{sourceKey,raw})};
}

test('existing later boot and exact original targets can prepare fresh current-state review only',()=>{
  const f=fixture(),plan=f.plan(),result=assessLegacyRecovery(plan,f.current);
  assert.equal(plan.schema,'mesh/legacy-recovery-plan/v3');
  assert.equal(plan.preparedAt,f.current.observedAt);assert.notEqual(plan.preparedAt,f.historical.preparedAt);
  assert.equal(plan.boardSha256,f.current.boardSha256);assert.deepEqual(plan.sources,f.current.sources);
  assert.equal(result.status,'ready_for_operator_review');assert.equal(result.canRelease,false);
  assert.equal(result.pcCustody.historicalPlanHash,f.historical.planHash);
  assert.equal(result.pcCustody.workerRetirementEstablished,false);
  assert.equal(result.pcCustody.newOwnerAndOfflineWriterFencesStillRequired,true);
  assert.equal(assessLegacyRecovery(makeLegacyRecoveryPlan(f.current),f.current).status,'blocked');
});

test('current-boot planning requires pinned original bytes, a real prior boot boundary, and the same machine and eight targets',()=>{
  for(const change of [
    {host:'OTHER'},{machineIdentity:'2'.repeat(64)},{workspace:resolve('other')},{databaseIdentity:'e'.repeat(64)},
    {databasePath:resolve('other.sqlite')},{bootedAt:'2026-11-14T01:00:00Z'},
    {targets:fixture().current.targets.map((t,n)=>n?t:{...t,fingerprint:'f'.repeat(64)})},
    {otherWorkSendIds:['other']},{otherWriterHolds:[{reason:'active_team'}]},
    {sources:fixture().historical.sources},
  ]){
    const f=fixture();assert.throws(()=>makeCurrentBootLegacyRecoveryPlan({...f.current,...change},{sourceKey,raw:f.raw}));
  }
  const f=fixture();assert.throws(()=>makeCurrentBootLegacyRecoveryPlan(f.current,{sourceKey,raw:f.raw+' '}));
  assert.throws(()=>makeCurrentBootLegacyRecoveryPlan(f.current,{sourceKey:'unreviewed',raw:f.raw}));
});

test('current-board/code/boot changes and additional work stay blocked after fresh preparation',()=>{
  const f=fixture(),plan=f.plan();
  for(const [change,reason] of [
    [{boardSha256:'f'.repeat(64)},'saved_board_changed'],[{taskCount:16},'saved_board_changed'],
    [{sources:{...f.current.sources,relay:'f'.repeat(64)}},'source_changed'],
    [{sources:{...f.current.sources,[sourceKey]:'f'.repeat(64)}},'source_changed'],
    [{bootedAt:'2026-11-15T02:00:00Z'},'reviewed_current_boot_changed'],
    [{observedAt:'2026-11-15T23:59:00Z'},'observation_predates_plan'],
    [{otherWorkSendIds:['other']},'other_work_requires_reconciliation'],
    [{otherWriterHolds:[{reason:'active_team'}]},'other_writer_holds_require_reconciliation'],
  ])assert.ok(assessLegacyRecovery(plan,{...f.current,...change}).reasons.includes(reason),reason);
});

test('rehashed tampering cannot turn a modified, nested, or unpinned historical witness into authority',()=>{
  const f=fixture();
  for(const change of ['bytes','source','old-checksum','nested']){
    const plan=structuredClone(f.plan());
    if(change==='bytes')plan.retirementWitness.raw+=' ';
    if(change==='source')plan.retirementWitness.sourceKey='other';
    if(change==='old-checksum'||change==='nested'){
      const old=JSON.parse(plan.retirementWitness.raw);old.host='EDITED';if(change==='nested')old.schema='mesh/legacy-recovery-plan/v3';
      plan.retirementWitness.raw=JSON.stringify(old);plan.retirementWitness.sha256=createHash('sha256').update(plan.retirementWitness.raw).digest('hex');
      plan.sources[sourceKey]=plan.retirementWitness.sha256;
    }
    const {planHash,...body}=plan;plan.planHash=legacyRecoveryFingerprint(body);
    assert.throws(()=>assessLegacyRecovery(plan,f.current));
  }
});
