import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, readdirSync, realpathSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { runLegacyRecoveryConsole, formatLegacyRecoveryPrompt, formatLegacyRecoveryResult } from '../lib/workroom-legacy-console.mjs';
import { createLegacyAuthorizationReader } from '../lib/workroom-legacy-authorization.mjs';

function fixture(t) {
  const workspace=realpathSync.native(mkdtempSync(join(tmpdir(),'mesh-console-')));mkdirSync(join(workspace,'data'));
  t.after(()=>rmSync(workspace,{recursive:true,force:true}));
  const plan={schema:'mesh/legacy-recovery-plan/v2',planHash:'a'.repeat(64),host:'fixture-host',preparedAt:new Date(Date.now()-60000).toISOString(),
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

test('a failed safety read saves a definitive pre-apply receipt without exposing the exception',async t=>{
  const privateError='fixture-only process details';
  for(const phase of ['initial inspection','reconfirmation inspection','final inspection','host observation']) {
    const f=fixture(t);
    const inspect=f.options.inspect;
    const failedRead={'initial inspection':1,'reconfirmation inspection':2,'final inspection':2}[phase];
    let reads=0;
    f.options.inspect=async()=>{
      if(++reads===failedRead)throw Error(privateError);
      return inspect();
    };
    if(phase==='reconfirmation inspection')f.options.confirm=async()=> 'typo';
    if(phase==='host observation')f.options.observe=async()=>{throw Error(privateError);};
    const receipt=await runLegacyRecoveryConsole(f.options);
    const reason=phase==='host observation'?'host_observation_unavailable':'inspection_unavailable';
    const status=phase==='final inspection'||phase==='host observation'?'blocked_after_confirmation':'blocked';
    assert.equal(receipt.status,status,phase);
    assert.equal(receipt.reason,reason,phase);
    assert.equal(receipt.recoveryApplied,false,phase);
    const bytes=readFileSync(join(receipt.receiptDirectory,'result.json'),'utf8');
    assert.deepEqual(JSON.parse(bytes),receipt);
    assert.doesNotMatch(bytes,new RegExp(privateError));
    assert.match(formatLegacyRecoveryResult(receipt),/RECOVERY NOT APPLIED/);
    assert.match(formatLegacyRecoveryResult(receipt),/could not be completed/);
    assert.equal(existsSync(join(receipt.receiptDirectory,'authorization.json')),false);
    assert.equal(existsSync(join(f.workspace,'data','maintenance-console',f.options.plan.planHash+'.attempt.json')),false);
    assert.equal(f.calls,0);
  }
});

test('same boot cannot mint a postboot owner approval',async t=>{
  const f=fixture(t);f.options.observe=async()=>({host:f.options.plan.host,bootedAt:f.options.plan.preparedAt});
  const result=await runLegacyRecoveryConsole(f.options);
  assert.equal(result.status,'blocked_after_confirmation');
  assert.equal(result.reason,'host_or_boot_changed');
  assert.equal(f.calls,0);
  assert.equal(existsSync(join(result.receiptDirectory,'authorization.json')),false);
});

test('the current-boot console accepts only the boot and machine frozen in the plan',async t=>{
  for (const change of ['different boot','different machine','none']) {
    const f=fixture(t);
    const plan=f.options.plan;
    plan.schema='mesh/legacy-recovery-plan/v3';
    plan.baselineBoot=new Date(Date.parse(plan.preparedAt)-60000).toISOString();
    plan.machineIdentity='1'.repeat(64);
    f.options.observe=async()=>({host:plan.host,
      bootedAt:change==='different boot'?plan.preparedAt:plan.baselineBoot,
      machineIdentity:change==='different machine'?'2'.repeat(64):plan.machineIdentity});
    const result=await runLegacyRecoveryConsole(f.options);
    assert.equal(result.status,change==='none'?'operator_returned':'blocked_after_confirmation');
    assert.equal(f.calls,change==='none'?1:0);
    assert.equal(existsSync(join(result.receiptDirectory,'authorization.json')),change==='none');
  }
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


function feedbackFixture() {
  const workspace=realpathSync.native(mkdtempSync(join(tmpdir(),'mesh-confirmation-feedback-')));
  mkdirSync(join(workspace,'data'));
  const plan={schema:'mesh/legacy-recovery-plan/v2',planHash:'a'.repeat(64),host:'synthetic-host',preparedAt:'2020-01-01T00:00:00.000Z',
    disposition:'historical_outcome_unknown',targets:Array.from({length:8},(_,i)=>({sendId:`synthetic-${i}`}))};
  const scope={workspace,retainedReview:{sha256:'b'.repeat(64)}};
  const calls={inspect:0,observe:0,apply:0,confirm:0};
  const ready=()=>({planHash:plan.planHash,targetCount:8,status:'ready_for_operator_review',
    controls:{status:'verified'},retainedReview:{status:'matched_review_only'}});
  const options={scope,plan,inspect:async()=>{calls.inspect++;return ready();},
    observe:async()=>{calls.observe++;return {host:plan.host,bootedAt:'2025-01-01T00:00:00.000Z'};},
    apply:async()=>{calls.apply++;return {planHash:plan.planHash,disposition:plan.disposition,
      dispatchRemainsPaused:true,recoveryId:'synthetic-recovery'};},
    confirm:async prompt=>{calls.confirm++;return prompt.phrase;}};
  const attempt=join(workspace,'data/maintenance-console',plan.planHash+'.attempt.json');
  return {options,calls,ready,attempt,plan};
}

test('blank confirmation cancels once and explains that recovery was not applied',async()=>{
  const f=feedbackFixture();f.options.confirm=async()=>{f.calls.confirm++;return '';};
  const r=await runLegacyRecoveryConsole(f.options);
  assert.equal(r.status,'cancelled');assert.equal(r.reason,'operator_cancelled');
  assert.equal(f.calls.confirm,1);assert.equal(f.calls.apply,0);assert.equal(f.calls.observe,0);
  assert.equal(existsSync(f.attempt),false);assert.match(formatLegacyRecoveryResult(r),/RECOVERY NOT APPLIED/);
});

test('mismatch retries are bounded and never retain a pasted private value',async()=>{
  const f=feedbackFixture(),privateValue='private-value-that-must-not-be-saved';
  f.options.confirm=async p=>{assert.equal(p.attempt,++f.calls.confirm);assert.equal(p.maxAttempts,3);return privateValue;};
  const r=await runLegacyRecoveryConsole(f.options);
  assert.equal(r.status,'cancelled');assert.equal(r.reason,'confirmation_mismatch');
  assert.equal(f.calls.confirm,3);assert.equal(f.calls.inspect,3);assert.equal(f.calls.apply,0);
  assert.equal(existsSync(f.attempt),false);
  for(const name of readdirSync(r.receiptDirectory))assert.equal(readFileSync(join(r.receiptDirectory,name),'utf8').includes(privateValue),false);
  assert.match(formatLegacyRecoveryResult(r),/did not match after three attempts/);
});

test('exact confirmation after a typo rechecks state and creates only one apply intent',async()=>{
  const f=feedbackFixture();f.options.confirm=async p=>++f.calls.confirm===1?'RECOVER typo':p.phrase;
  const r=await runLegacyRecoveryConsole(f.options);
  assert.equal(r.status,'operator_returned');assert.equal(f.calls.confirm,2);
  assert.equal(f.calls.inspect,3);assert.equal(f.calls.observe,1);assert.equal(f.calls.apply,1);
  assert.equal(existsSync(f.attempt),true);assert.match(formatLegacyRecoveryResult(r),/RECOVERY RECORDED/);
  await assert.rejects(()=>runLegacyRecoveryConsole(f.options),/prior apply attempt/);
  assert.equal(f.calls.apply,1);
});

test('a changed preflight blocks reconfirmation before another prompt or apply',async()=>{
  const f=feedbackFixture();f.options.inspect=async()=>++f.calls.inspect===1?f.ready():{...f.ready(),controls:{status:'blocked'}};
  f.options.confirm=async()=>{f.calls.confirm++;return 'not exact';};
  const r=await runLegacyRecoveryConsole(f.options);
  assert.equal(r.status,'blocked');assert.equal(r.reason,'preconfirmation_state_changed');
  assert.equal(f.calls.confirm,1);assert.equal(f.calls.observe,0);assert.equal(f.calls.apply,0);
  assert.equal(existsSync(f.attempt),false);
});

test('approval expiry during a typo correction stops before another prompt',async t=>{
  const f=feedbackFixture();let now=Date.now();t.mock.method(Date,'now',()=>now);
  f.options.authorizationExpiresAt=new Date(now+1000).toISOString();
  f.options.confirm=async()=>{f.calls.confirm++;now+=1001;return 'wrong';};
  const r=await runLegacyRecoveryConsole(f.options);
  assert.equal(r.status,'blocked_expired_window');assert.equal(f.calls.confirm,1);
  assert.equal(f.calls.apply,0);assert.equal(existsSync(f.attempt),false);
});

test('plain prompt highlights the exact short phrase without raw JSON',()=>{
  const text=formatLegacyRecoveryPrompt({message:'Keep other editors closed.',planHash:'a'.repeat(64),
    targetCount:8,attempt:2,maxAttempts:3,phrase:'RECOVER '+ 'a'.repeat(12),receiptDirectory:'synthetic-evidence'});
  assert.match(text,/No recovery has been applied/);assert.match(text,/attempt 2 of 3/);
  assert.match(text,/\nRECOVER a{12}\n/);assert.match(text,/Enter without typing to cancel/);
  assert.equal(text.includes('a'.repeat(64)),false);assert.equal(text.includes('"targetCount"'),false);
});

test('uncertain and malformed success receipts never display recorded or permit restoration',()=>{
  for(const r of [{status:'outcome_unknown_inspect_same_plan'},{status:'unrecognized_status'},{},
    {status:'operator_returned',planHash:'a'.repeat(64),result:{dispatchRemainsPaused:true}},
    {status:'operator_returned',planHash:'a'.repeat(64),result:{planHash:'b'.repeat(64),
      disposition:'historical_outcome_unknown',dispatchRemainsPaused:true,recoveryId:'synthetic'}}]){
    const text=formatLegacyRecoveryResult({...r,receiptDirectory:'synthetic-evidence'});
    assert.match(text,/RECOVERY OUTCOME UNCERTAIN/);assert.match(text,/Do not retry recovery or restore startup/);
    assert.equal(text.includes('RECOVERY RECORDED'),false);
  }
});
