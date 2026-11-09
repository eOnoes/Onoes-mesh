// Verify the positive review against exact saved native tool output; never starts a turn.
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {createHash} from 'node:crypto';
import {DatabaseSync} from 'node:sqlite';
import {createCodexClient} from '../lib/codex-client.mjs';
const root=resolve(process.argv[2]??'');assert.ok(process.argv[2],'Supply a completed disposable native qualification directory');
const base=JSON.parse(readFileSync(join(root,'local-session-verified.json'),'utf8'));assert.equal(base.qualification,'PASS');assert.equal(base.realNimsReviewCompleted,true);
const review=JSON.parse(readFileSync(join(root,'nims-review-evidence.json'),'utf8')),db=new DatabaseSync(join(root,'mesh-local-binding.sqlite'),{readOnly:true});
const client=createCodexClient({root:join(root,'workspace')});
try{
 const run=db.prepare('SELECT * FROM nims_runs WHERE sendId=? AND taskId=?').get(review.sendId,review.taskId);assert.equal(run.state,'completed');assert.equal(run.threadId,review.threadId);assert.equal(run.turnId,review.turnId);
 const native=await client.readThread(run.threadId);assert.equal(native.thread.id,run.threadId);const turns=native.thread.turns.filter(t=>t.id===run.turnId);assert.equal(turns.length,1);const turn=turns[0];assert.equal(turn.status,'completed');
 const final=turn.items.filter(i=>i.type==='agentMessage').at(-1).text;assert.equal(final.trim(),run.text.trim());
 const blocks=[...final.matchAll(/```workroom-review\s*([\s\S]*?)```/g)];assert.equal(blocks.length,1);const verdict=JSON.parse(blocks[0][1]);assert.equal(verdict.verdict,'approved');assert.equal(verdict.taskId,run.taskId);assert.equal(verdict.sendId,run.sendId);
 const commands=turn.items.filter(i=>i.type==='commandExecution'&&i.status==='completed'&&i.exitCode===0&&i.command.includes('proofMatches'));
 assert.equal(commands.length,1);const check=JSON.parse(commands[0].aggregatedOutput.trim());
 // Both saved proof formats carry the same facts; conflicting aliases are refused.
 const fact=(...values)=>{const present=values.filter(value=>value!==undefined);assert.ok(present.length);assert.ok(present.every(value=>value===present[0]));return present[0];};
 const proofHex=fact(check.actualHex,check.proofHex),validExit=fact(check.valid?.status,check.validSyntaxExit),invalidExit=fact(check.invalid?.status,check.invalidSyntaxExit),unchanged=fact(check.unchanged,check.artifactsUnchanged);
 assert.equal(proofHex,'4d657368206c6f63616c2073657373696f6e2070726f6f662e0a');assert.equal(check.proofMatches,true);assert.equal(validExit,0);assert.equal(invalidExit,1);assert.equal(check.localProof,true);assert.equal(unchanged,true);
 const files=['local-session-proof.md','local-build-proof.mjs','verify-local-build.mjs','local-build-check.json','assignment-child-ready.json'];assert.deepEqual(Object.keys(check.sha256).sort(),[...files].sort());
 for(const file of files)assert.equal(createHash('sha256').update(readFileSync(join(root,'workspace',file))).digest('hex'),check.sha256[file]);
 assert.equal(db.prepare('SELECT state FROM workroom_automation WHERE taskId=?').get(run.taskId).state,'needs_review');assert.equal(db.prepare('SELECT decision FROM workroom_progress WHERE taskId=?').get(run.taskId).decision,'pending');
 const result={qualification:'PASS',check:'native_approved_review_matches_actual_readonly_tool_output',directory:root,taskId:run.taskId,sendId:run.sendId,threadId:run.threadId,turnId:run.turnId,verdict:verdict.verdict,artifactCount:files.length,proofHex,validSyntaxExit:validExit,invalidSyntaxExit:invalidExit,exportValue:check.localProof,allFiveHashesMatch:true,teamState:'needs_review',decision:'pending',modelTurnsStarted:0};
 writeFileSync(join(root,'positive-review-verified.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}finally{await client.close();db.close();}
