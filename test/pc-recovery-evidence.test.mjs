import test from 'node:test';
import assert from 'node:assert/strict';
import {assertPcRecovery} from '../integrations/verify-live-release.mjs';
const snapshot=()=>({schema:'mesh-pc-recovery/v1',taskCount:14,bootTime:'2026-01-01T00:00:00Z',machineSha256:'a'.repeat(64),boardSha256:'b'.repeat(64),holdsSha256:'c'.repeat(64),sourceSha256:'d'.repeat(64)});
const later=before=>({...before,bootTime:'2026-01-02T00:00:00Z'});

test('new boot with preserved records proves custody without granting worker retirement',()=>{
 const before=snapshot();assert.deepEqual(assertPcRecovery(before,later(before)),{pcBootChanged:true,boardPreserved:true,holdsPreserved:true,workerRetirementEstablished:false,scope:'PC bootstrap/data custody only; no hold release'});
});
test('same/older boot and wrong machine cannot impersonate recovery',()=>{
 const before=snapshot();assert.throws(()=>assertPcRecovery(before,{...before}),/No newer Windows boot/);
 assert.throws(()=>assertPcRecovery(before,{...before,bootTime:'2025-01-01T00:00:00Z'}),/No newer Windows boot/);
 assert.throws(()=>assertPcRecovery(before,{...later(before),machineSha256:'f'.repeat(64)}),/Different PC/);
});
test('changed board, count, app source or assignment holds refuse qualification',()=>{
 const before=snapshot();for(const changed of [{taskCount:13},{boardSha256:'f'.repeat(64)},{sourceSha256:'f'.repeat(64)},{holdsSha256:'f'.repeat(64)}])assert.throws(()=>assertPcRecovery(before,{...later(before),...changed}));
});
test('missing or malformed baseline and observation cannot pass equal undefined fields',()=>{
 const before=snapshot();for(const bad of [null,{}, {...before,bootTime:'not-a-date'},{...before,taskCount:1.5},{...before,holdsSha256:undefined},{...before,machineSha256:'not-a-hash'}]){
  assert.throws(()=>assertPcRecovery(bad,later(before)),/Invalid PC recovery evidence/);
  assert.throws(()=>assertPcRecovery(before,bad),/Invalid PC recovery evidence/);
 }
});
