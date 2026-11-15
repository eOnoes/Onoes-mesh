// Local interactive orchestration only. The production caller supplies the existing
// guarded operator; this module cannot stop apps, restart Windows or dispatch work.
import { createHash, randomUUID } from 'node:crypto';
import { closeSync, existsSync, fsyncSync, lstatSync, mkdirSync, openSync, realpathSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { createLegacyAuthorizationReader } from './workroom-legacy-authorization.mjs';

const key=p=>process.platform==='win32'?p.toLowerCase():p;
const digest=v=>typeof v==='string'&&/^[a-f0-9]{64}$/.test(v);
const requireValue=(value,message)=>{if(!value)throw Error(message);};
function directory(path) {
  const stat=lstatSync(path);
  requireValue(stat.isDirectory()&&!stat.isSymbolicLink()&&key(realpathSync.native(path))===key(resolve(path)),
    'Console receipt directories must be canonical local directories.');
}
function save(path,value) {
  const bytes=JSON.stringify(value,null,2)+'\n';
  const handle=openSync(path,'wx',0o600);
  try {writeFileSync(handle,bytes,'utf8');fsyncSync(handle);} finally {closeSync(handle);}
  return createHash('sha256').update(bytes).digest('hex');
}
const ready=(value,plan)=>value?.planHash===plan.planHash&&value.targetCount===8&&
  value.status==='ready_for_operator_review'&&value.controls?.status==='verified'&&
  value.retainedReview?.status==='matched_review_only';

export function formatLegacyRecoveryPrompt(prompt) {
  return [
    '\nMESH RECOVERY — CONFIRMATION',
    prompt.message,
    `Plan ${prompt.planHash.slice(0,12)} · ${prompt.targetCount} historical jobs`,
    ...(prompt.attempt>1?['That answer did not match. No recovery has been applied.']:[]),
    `Type this exact line (attempt ${prompt.attempt} of ${prompt.maxAttempts}):`,
    '',prompt.phrase,'',
    'Press Enter without typing to cancel.',
    `Evidence folder: ${prompt.receiptDirectory}`,
  ].join('\n')+'\n';
}

export function formatLegacyRecoveryResult(receipt) {
  const result=receipt.result;
  const recorded=receipt.status==='operator_returned'&&
    result?.planHash===receipt.planHash&&result.disposition==='historical_outcome_unknown'&&
    result.dispatchRemainsPaused===true&&typeof result.recoveryId==='string'&&result.recoveryId.length>0;
  let lines;
  if(recorded)lines=['RECOVERY RECORDED','The 8 historical outcomes are recorded as unknown. Dispatch remains paused.',
    'Next: open the separate Restore startup launcher.'];
  else if(!['blocked','cancelled','blocked_after_confirmation','blocked_expired_window'].includes(receipt.status))
    lines=['RECOVERY OUTCOME UNCERTAIN','Do not retry recovery or restore startup. Keep this window open and share the result with Nims.'];
  else {
    const reason=receipt.reason==='confirmation_mismatch'?'The exact confirmation did not match after three attempts.':
      receipt.reason==='operator_cancelled'?'You cancelled at the confirmation prompt.':
      receipt.status==='blocked_expired_window'?'The maintenance approval expired.':
      receipt.reason==='preconfirmation_state_changed'?'The safety checks changed before confirmation.':
      receipt.status==='cancelled'?'Confirmation was cancelled.':'The safety checks did not permit recovery.';
    lines=['RECOVERY NOT APPLIED',reason,'No historical jobs were changed by this console attempt.',
      'Keep this result. Follow the reviewed startup-restoration instructions; do not start another recovery attempt.'];
  }
  return ['\n'+lines[0],...lines.slice(1),`Evidence folder: ${receipt.receiptDirectory}`].join('\n')+'\n';
}

export async function runLegacyRecoveryConsole({scope,plan,inspect,observe,confirm,apply,authorizationExpiresAt}) {
  const deadline=authorizationExpiresAt===undefined?Infinity:Date.parse(authorizationExpiresAt);
  requireValue(deadline===Infinity||Number.isFinite(deadline),'A valid maintenance-window deadline is required.');
  requireValue(digest(plan?.planHash)&&plan.disposition==='historical_outcome_unknown'&&
    plan.targets?.length===8&&new Set(plan.targets.map(t=>t.sendId)).size===8&&
    digest(scope?.retainedReview?.sha256)&&[inspect,observe,confirm,apply].every(f=>typeof f==='function'),
  'An exact eight-send plan, retained review and guarded console callbacks are required.');
  const data=join(scope.workspace,'data');directory(data);
  const base=join(data,'maintenance-console');
  if(!existsSync(base))mkdirSync(base);
  directory(base);
  const attemptPath=join(base,plan.planHash+'.attempt.json');
  requireValue(!existsSync(attemptPath),'A prior apply attempt exists. Inspect the same plan and receipts; do not retry.');
  const receiptDirectory=join(base,randomUUID());mkdirSync(receiptDirectory);
  const finish=(status,extra={})=>{
    const result={status,planHash:plan.planHash,receiptDirectory,...extra};
    save(join(receiptDirectory,'result.json'),result);return result;
  };
  if(Date.now()>=deadline)return finish('blocked_expired_window');
  const first=await inspect();save(join(receiptDirectory,'inspection-before.json'),first);
  if(!ready(first,plan))return finish('blocked');
  const phrase='RECOVER '+plan.planHash.slice(0,12);
  const prompt={planHash:plan.planHash,phrase,targetCount:8,
    disposition:plan.disposition,receiptDirectory,workspace:scope.workspace,
    targetSendIds:plan.targets.map(target=>target.sendId),
    message:'Keep every other Mesh editor and agent closed. Record UNKNOWN historical outcomes for these eight sends; keep dispatch paused. This does not approve old jobs or start workers.'};
  save(join(receiptDirectory,'confirmation-request.json'),prompt);
  let answer;
  for(let attempt=1;attempt<=3;attempt++) {
    if(Date.now()>=deadline)return finish('blocked_expired_window');
    if(attempt>1) {
      const fresh=await inspect();save(join(receiptDirectory,`inspection-before-reconfirmation-${attempt}.json`),fresh);
      if(!ready(fresh,plan))return finish('blocked',{reason:'preconfirmation_state_changed'});
      if(Date.now()>=deadline)return finish('blocked_expired_window');
    }
    answer=await confirm({...prompt,attempt,maxAttempts:3});
    if(answer===phrase)break;
    if(answer==='')return finish('cancelled',{reason:'operator_cancelled',recoveryApplied:false});
    // Never retain mismatched input: a pasted value could contain private data.
    save(join(receiptDirectory,`confirmation-mismatch-${attempt}.json`),{attempt,reason:'confirmation_mismatch'});
    if(attempt===3)return finish('cancelled',{reason:'confirmation_mismatch',recoveryApplied:false});
  }
  save(join(receiptDirectory,'confirmation.json'),{owner:'Eddie',planHash:plan.planHash,answer,at:new Date().toISOString()});
  const second=await inspect();save(join(receiptDirectory,'inspection-after.json'),second);
  if(!ready(second,plan))return finish('blocked_after_confirmation');
  const current=await observe();
  requireValue(current.host===plan.host&&Number.isFinite(Date.parse(current.bootedAt))&&
    Date.parse(current.bootedAt)>Date.parse(plan.preparedAt),
  'The exact host and later boot must be verified before owner approval.');
  const now=Date.now(),authorizationPath=join(receiptDirectory,'authorization.json');
  if(now>=deadline)return finish('blocked_expired_window');
  const authorizationSha256=save(authorizationPath,{
    schema:'mesh/legacy-recovery-authorization/v1',owner:'Eddie',decision:'apply_exact_eight',
    planHash:plan.planHash,host:current.host,bootedAt:current.bootedAt,
    authorizedAt:new Date(now).toISOString(),expiresAt:new Date(Math.min(now+10*60000,deadline)).toISOString(),
    maintenanceMode:'worker_services_offline',quietWorkspaceConfirmed:true,
    retainedReviewSha256:scope.retainedReview.sha256,
  });
  // Use the existing approval reader, then let the operator repeat all checks at COMMIT.
  await createLegacyAuthorizationReader({recordPath:authorizationPath,expectedSha256:authorizationSha256,
    planHash:plan.planHash,host:current.host,bootedAt:current.bootedAt});
  // One exclusive, flushed intent per plan, across every console receipt directory.
  save(attemptPath,{schema:'mesh/legacy-console-attempt/v1',planHash:plan.planHash,
    receiptDirectory,authorizationPath,authorizationSha256,at:new Date().toISOString()});
  try {
    const result=await apply({authorizationPath,authorizationSha256});
    requireValue(result?.dispatchRemainsPaused===true,'Operator did not confirm dispatch remains paused.');
    return finish('operator_returned',{result});
  } catch(error) {
    return finish('outcome_unknown_inspect_same_plan',{error:String(error.message),canRetry:false});
  }
}
