export function validatePcSnapshot(value){
  if(value?.schema!=='mesh-pc-recovery/v1'||!Number.isInteger(value.taskCount)||value.taskCount<0
    ||typeof value.bootTime!=='string'||!Number.isFinite(Date.parse(value.bootTime))
    ||!['machineSha256','boardSha256','holdsSha256','sourceSha256'].every(key=>/^[a-f0-9]{64}$/.test(value[key]||'')))
   throw Error('Invalid PC recovery evidence. No recovery qualified.');
}

export function assertPcRecovery(before,after){
 validatePcSnapshot(before);validatePcSnapshot(after);
 if(before.machineSha256!==after.machineSha256)throw Error('Different PC. No recovery qualified.');
 if(Date.parse(after.bootTime)<=Date.parse(before.bootTime))throw Error('No newer Windows boot observed. An app restart is insufficient.');
 if(before.taskCount!==after.taskCount||before.boardSha256!==after.boardSha256)throw Error('Saved board changed. Inspect before claiming preservation.');
 if(before.sourceSha256!==after.sourceSha256)throw Error('App source changed. Review the release before qualification.');
 if(before.holdsSha256!==after.holdsSha256)throw Error('Assignment holds changed. No clearance is granted.');
 return {pcBootChanged:true,boardPreserved:true,holdsPreserved:true,workerRetirementEstablished:false,scope:'PC bootstrap/data custody only; no hold release'};
}

