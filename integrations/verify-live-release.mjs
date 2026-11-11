import {readFileSync,writeFileSync,realpathSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {hostname} from 'node:os';
import {dirname,resolve,relative,isAbsolute,sep} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
const origin='http://127.0.0.1:4320';
const hash=value=>createHash('sha256').update(value).digest('hex');

function validatePcSnapshot(value){
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

function pcFile(argument){
 if(!argument)throw Error('Choose an explicit JSON capture file under this checkout data folder.');
 const data=realpathSync(resolve(dirname(fileURLToPath(import.meta.url)),'../data'));
 const file=resolve(argument),parent=realpathSync(dirname(file)),part=relative(data,parent);
 if(isAbsolute(part)||part==='..'||part.startsWith('..'+sep)||!file.endsWith('.json'))throw Error('PC evidence must stay under this checkout data folder.');
 return file;
}

async function main(){
const action=process.argv[2],pc=['capture-pc','verify-pc'].includes(action);
if(!['capture','verify','capture-pc','verify-pc'].includes(action))throw Error('Use capture/verify for Mesh restart, or capture-pc/verify-pc with a data JSON path. This tool never restarts anything.');
const pcPath=pc?pcFile(process.argv[3]):null;
const identity=pc?{machineSha256:hash(hostname().toLowerCase()),bootTime:execFileSync('powershell.exe',['-NoProfile','-Command',"(Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')"],{encoding:'utf8',windowsHide:true,timeout:8000}).trim()}:null;
const headers={Origin:origin,'Content-Type':'application/json'};
const bootstrap=await fetch(origin+'/api/trial-session/bootstrap',{method:'POST',headers,body:'{}'});
if(bootstrap.status!==201)throw Error('Cannot establish admitted read.');
const session=await bootstrap.json();
headers.Cookie=bootstrap.headers.get('set-cookie').split(';')[0];headers['X-Trial-CSRF']=session.csrfToken;
try{
 const response=await fetch(origin+'/api/workroom',{headers});if(response.status!==200)throw Error('Board read failed');
 const board=await response.json();
 const digest=hash(JSON.stringify({tasks:board.tasks}));
 const evidence={at:new Date().toISOString(),taskCount:board.tasks.length,boardSha256:digest};
 if(pc){
  const r=await fetch(origin+'/api/release',{headers});if(r.status!==200)throw Error('Release read failed');
  const release=await r.json();
  const h=await fetch(origin+'/api/workroom/rook',{headers});if(h.status!==200)throw Error('Assignment hold read failed');
  const rook=await h.json();if(!Array.isArray(rook.assignmentHolds)||!rook.assignmentHolds.every(value=>['taskId','sendId','state','reason'].every(key=>typeof value[key]==='string')))throw Error('Assignment hold evidence missing');
  Object.assign(evidence,{schema:'mesh-pc-recovery/v1',...identity,sourceSha256:release.sourceSha256,
   holdsSha256:hash(JSON.stringify(rook.assignmentHolds.map(({taskId,sendId,state,reason})=>({taskId,sendId,state,reason})).sort((a,b)=>(a.taskId+a.sendId).localeCompare(b.taskId+b.sendId)))),workerRetirementEstablished:false});
  validatePcSnapshot(evidence);
  if(action==='capture-pc')writeFileSync(pcPath,JSON.stringify(evidence,null,2),{flag:'wx'});
  else{
   const before=JSON.parse(readFileSync(pcPath,'utf8'));
   Object.assign(evidence,assertPcRecovery(before,evidence));
   writeFileSync(pcPath+'.verified.json',JSON.stringify(evidence,null,2),{flag:'wx'});
  }
 }
 else if(action==='capture')writeFileSync('../mesh-release-before.json',JSON.stringify(evidence,null,2));
 else{
  const before=JSON.parse(readFileSync('../mesh-release-before.json','utf8'));
  if(before.boardSha256!==digest)throw Error('Saved board changed across restart; inspect before claiming preservation.');
  const r=await fetch(origin+'/api/release',{headers});if(r.status!==200)throw Error('Release read failed');
  evidence.release=await r.json();evidence.boardPreserved=true;
  writeFileSync('../mesh-release-live.json',JSON.stringify(evidence,null,2));
 }
 console.log(JSON.stringify(evidence,null,2));
}finally{await fetch(origin+'/api/trial-session/logout',{method:'POST',headers,body:'{}'});}
}

if(process.argv[1]&&import.meta.url===pathToFileURL(resolve(process.argv[1])).href)await main();
