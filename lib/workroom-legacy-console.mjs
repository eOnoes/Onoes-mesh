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

export async function runLegacyRecoveryConsole({scope,plan,inspect,observe,confirm,apply}) {
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
  const first=await inspect();save(join(receiptDirectory,'inspection-before.json'),first);
  if(!ready(first,plan))return finish('blocked');
  const phrase='RECOVER '+plan.planHash.slice(0,12);
  const answer=await confirm({planHash:plan.planHash,phrase,targetCount:8,
    disposition:plan.disposition,receiptDirectory,workspace:scope.workspace,
    targetSendIds:plan.targets.map(target=>target.sendId),
    message:'Confirm every other Mesh editor/agent stays closed. Record UNKNOWN historical outcomes for these eight sends; keep dispatch paused. This does not approve old jobs or start workers.'});
  if(answer!==phrase)return finish('cancelled');
  save(join(receiptDirectory,'confirmation.json'),{owner:'Eddie',planHash:plan.planHash,answer,at:new Date().toISOString()});
  const second=await inspect();save(join(receiptDirectory,'inspection-after.json'),second);
  if(!ready(second,plan))return finish('blocked_after_confirmation');
  const current=await observe();
  requireValue(current.host===plan.host&&Number.isFinite(Date.parse(current.bootedAt))&&
    Date.parse(current.bootedAt)>Date.parse(plan.preparedAt),
  'The exact host and later boot must be verified before owner approval.');
  const now=Date.now(),authorizationPath=join(receiptDirectory,'authorization.json');
  const authorizationSha256=save(authorizationPath,{
    schema:'mesh/legacy-recovery-authorization/v1',owner:'Eddie',decision:'apply_exact_eight',
    planHash:plan.planHash,host:current.host,bootedAt:current.bootedAt,
    authorizedAt:new Date(now).toISOString(),expiresAt:new Date(now+10*60000).toISOString(),
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
