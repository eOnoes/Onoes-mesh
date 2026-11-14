import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, realpathSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { runLegacyRecoveryConsole } from '../lib/workroom-legacy-console.mjs';
import { createLegacyAuthorizationReader } from '../lib/workroom-legacy-authorization.mjs';

function fixture(t) {
  const workspace=realpathSync.native(mkdtempSync(join(tmpdir(),'mesh-console-')));mkdirSync(join(workspace,'data'));
  t.after(()=>rmSync(workspace,{recursive:true,force:true}));
  const plan={planHash:'a'.repeat(64),host:'fixture-host',preparedAt:new Date(Date.now()-60000).toISOString(),
    disposition:'historical_outcome_unknown',targets:Array.from({length:8},(_,i)=>({sendId:`send-${i}`}))};
  const scope={workspace,retainedReview:{sha256:'b'.repeat(64)}};
  const inspection={planHash:plan.planHash,targetCount:8,status:'ready_for_operator_review',
    controls:{status:'verified'},retainedReview:{status:'matched_review_only'}};
  let calls=0,prompts=0;
  const options={scope,plan,inspect:async()=>inspection,
    observe:async()=>({host:plan.host,bootedAt:new Date(Date.now()-30000).toISOString()}),
    confirm:async({phrase})=>{prompts++;return phrase;},apply:async args=>{
      calls++;
      const record=JSON.parse(readFileSync(args.authorizationPath,'utf8'));
      const reader=await createLegacyAuthorizationReader({recordPath:args.authorizationPath,
        expectedSha256:args.authorizationSha256,planHash:plan.planHash,host:plan.host,bootedAt:record.bootedAt});
      assert.equal((await reader(plan.planHash)).decision,'apply_exact_eight');
      assert.equal(record.quietWorkspaceConfirmed,true);assert.equal(record.retainedReviewSha256,scope.retainedReview.sha256);
      return {dispatchRemainsPaused:true,status:'fixture_committed'};
    }};
  return {options,inspection,get calls(){return calls;},get prompts(){return prompts;},workspace};
}

test('explicit console confirmation produces a current exact approval and retained result',async t=>{
  const f=fixture(t);const result=await runLegacyRecoveryConsole(f.options);
  assert.equal(f.calls,1);assert.equal(f.prompts,1);assert.equal(result.status,'operator_returned');
  assert.equal(JSON.parse(readFileSync(join(result.receiptDirectory,'result.json'),'utf8')).result.dispatchRemainsPaused,true);
  await assert.rejects(runLegacyRecoveryConsole(f.options),/prior apply attempt/i);
  assert.equal(f.calls,1);
});

test('opening a blocked plan never prompts, writes approval or applies',async t=>{
  const f=fixture(t);f.inspection.controls.status='blocked';
  const result=await runLegacyRecoveryConsole(f.options);
  assert.equal(result.status,'blocked');assert.equal(f.prompts,0);assert.equal(f.calls,0);
  assert.equal(readdirSync(result.receiptDirectory).includes('authorization.json'),false);
});

test('the pinned window deadline caps the postboot approval instead of granting another ten minutes',async t=>{
  const f=fixture(t);const deadline=new Date(Date.now()+60000).toISOString();f.options.authorizationExpiresAt=deadline;
  const apply=f.options.apply;
  f.options.apply=async args=>{
    assert.equal(JSON.parse(readFileSync(args.authorizationPath,'utf8')).expiresAt,deadline);
    return apply(args);
  };
  assert.equal((await runLegacyRecoveryConsole(f.options)).status,'operator_returned');assert.equal(f.calls,1);
});

test('a window expiring while confirmation is open creates no approval or apply attempt',async t=>{
  const f=fixture(t);f.options.authorizationExpiresAt=new Date(Date.now()+500).toISOString();
  f.options.confirm=async({phrase})=>{await new Promise(resolve=>setTimeout(resolve,600));return phrase;};
  const result=await runLegacyRecoveryConsole(f.options);
  assert.equal(result.status,'blocked_expired_window');assert.equal(f.calls,0);
  assert.equal(readdirSync(result.receiptDirectory).includes('authorization.json'),false);
  assert.equal(readdirSync(join(f.workspace,'data','maintenance-console')).includes(f.options.plan.planHash+'.attempt.json'),false);
});

test('canceling or mistyping confirmation sends no apply and creates no approval',async t=>{
  const f=fixture(t);f.options.confirm=async()=> 'no';
  const result=await runLegacyRecoveryConsole(f.options);
  assert.equal(result.status,'cancelled');assert.equal(f.calls,0);
  assert.equal(readdirSync(result.receiptDirectory).includes('authorization.json'),false);
});

test('a state change while the confirmation is open blocks apply',async t=>{
  const f=fixture(t);f.options.confirm=async({phrase})=>{f.inspection.retainedReview.status='blocked';return phrase;};
  const result=await runLegacyRecoveryConsole(f.options);
  assert.equal(result.status,'blocked_after_confirmation');assert.equal(f.calls,0);
});

test('same boot cannot mint a postboot owner approval',async t=>{
  const f=fixture(t);f.options.observe=async()=>({host:f.options.plan.host,bootedAt:f.options.plan.preparedAt});
  await assert.rejects(runLegacyRecoveryConsole(f.options),/later boot/i);assert.equal(f.calls,0);
});

test('uncertain apply remains durable and cannot be blindly retried from a new console',async t=>{
  const f=fixture(t);f.options.apply=async()=>{throw Error('fixture: response lost after possible commit');};
  const result=await runLegacyRecoveryConsole(f.options);
  assert.equal(result.status,'outcome_unknown_inspect_same_plan');
  assert.equal(JSON.parse(readFileSync(join(result.receiptDirectory,'result.json'),'utf8')).status,result.status);
  await assert.rejects(runLegacyRecoveryConsole(f.options),/prior apply attempt/i);
});

test('abrupt process exit after the apply intent preserves the no-retry boundary',async t=>{
  const f=fixture(t);
  const helper=new URL('../lib/workroom-legacy-console.mjs',import.meta.url).href;
  const code=`import {runLegacyRecoveryConsole} from ${JSON.stringify(helper)};
    await runLegacyRecoveryConsole({scope:${JSON.stringify(f.options.scope)},plan:${JSON.stringify(f.options.plan)},
      inspect:async()=>(${JSON.stringify(f.inspection)}),
      observe:async()=>({host:'fixture-host',bootedAt:new Date(Date.now()-30000).toISOString()}),
      confirm:async({phrase})=>phrase,apply:async()=>process.exit(23)});`;
  const child=spawnSync(process.execPath,['--input-type=module','-e',code],{encoding:'utf8',timeout:10000,windowsHide:true});
  assert.equal(child.status,23,child.stderr);
  const base=join(f.workspace,'data','maintenance-console');
  const attempt=JSON.parse(readFileSync(join(base,f.options.plan.planHash+'.attempt.json'),'utf8'));
  assert.equal(readdirSync(attempt.receiptDirectory).includes('result.json'),false);
  await assert.rejects(runLegacyRecoveryConsole(f.options),/prior apply attempt/i);
  assert.equal(f.calls,0);
});

test('the real console CLI refuses a noninteractive invocation before touching a scope',()=>{
  const child=spawnSync(process.execPath,['integrations/legacy-recovery-operator.mjs','console',
    'missing-scope.json','a'.repeat(64),'missing-plan.json'],{encoding:'utf8',timeout:10000,windowsHide:true});
  assert.equal(child.status,1);assert.match(child.stderr,/interactive local terminal/);
});
