import {readFileSync,writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
const origin='http://127.0.0.1:4320';
const action=process.argv[2];
if(!['capture','verify'].includes(action))throw Error('Use capture before restart, verify after.');
const headers={Origin:origin,'Content-Type':'application/json'};
const bootstrap=await fetch(origin+'/api/trial-session/bootstrap',{method:'POST',headers,body:'{}'});
if(bootstrap.status!==201)throw Error('Cannot establish admitted read.');
const session=await bootstrap.json();
headers.Cookie=bootstrap.headers.get('set-cookie').split(';')[0];headers['X-Trial-CSRF']=session.csrfToken;
try{
 const response=await fetch(origin+'/api/workroom',{headers});if(response.status!==200)throw Error('Board read failed');
 const board=await response.json();
 const digest=createHash('sha256').update(JSON.stringify(board)).digest('hex');
 const evidence={at:new Date().toISOString(),taskCount:board.tasks.length,boardSha256:digest};
 if(action==='capture')writeFileSync('../mesh-release-before.json',JSON.stringify(evidence,null,2));
 else{
  const before=JSON.parse(readFileSync('../mesh-release-before.json','utf8'));
  if(before.boardSha256!==digest)throw Error('Saved board changed across restart; inspect before claiming preservation.');
  const r=await fetch(origin+'/api/release',{headers});if(r.status!==200)throw Error('Release read failed');
  evidence.release=await r.json();evidence.boardPreserved=true;
  writeFileSync('../mesh-release-live.json',JSON.stringify(evidence,null,2));
 }
 console.log(JSON.stringify(evidence,null,2));
}finally{await fetch(origin+'/api/trial-session/logout',{method:'POST',headers,body:'{}'});}
