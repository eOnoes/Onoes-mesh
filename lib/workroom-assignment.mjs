import {createHash} from 'node:crypto';
export function parseAssignment(text,taskId,sendId){
 const blocks=[...String(text).matchAll(/```workroom-assignment\s*\n([\s\S]*?)```/g)];if(blocks.length!==1)return null;
 try{const p=JSON.parse(blocks[0][1]);const fields=['schema','taskId','sendId','spec','workspace','allowedFiles','checks','boundaries','workerId','reviewerId'];if(Object.keys(p).sort().join(',')!==fields.sort().join(',')||p.schema!=='workroom-assignment/v1'||p.taskId!==taskId||p.sendId!==sendId)return null;
  if(['spec','workspace','allowedFiles','checks','boundaries'].some(k=>typeof p[k]!=='string'||!p[k].trim()||p[k].length>4000||p[k].includes('\0'))||['workerId','reviewerId'].some(k=>typeof p[k]!=='string'||!/^[A-Za-z0-9_-]{1,100}$/.test(p[k]))||p.workerId===p.reviewerId)return null;
  const canonical=JSON.stringify(fields.map(k=>[k,p[k]]));return {proposal:p,hash:createHash('sha256').update(canonical).digest('hex')};
 }catch{return null;}
}
export function assignmentInstruction(taskId,sendId,agents){
 const roster=agents.map(a=>({id:a.id,name:a.name||a.id,backend:a.backend,connected:Boolean(a.conversation_id),automaticBuilder:a.id==='echo',automaticReviewer:['dsh','nims'].includes(a.id)}));
 return '\nAutomatic workspace qualified: '+process.cwd()+'. Choose roles from this actual connected roster; local inference is not qualified. Automatic coding is currently qualified only for Echo on the Mesh checkout; Deep or Nims can independently review. If scope or capabilities are missing, ask and omit a ready proposal. Roster: '+JSON.stringify(roster)+'\nWhen ready, also return one ```workroom-assignment fenced JSON block with exactly '+JSON.stringify({schema:'workroom-assignment/v1',taskId,sendId,spec:'bounded spec',workspace:'exact absolute project root',allowedFiles:'named allowed files',checks:'local verification commands',boundaries:'non-goals and permissions',workerId:'echo',reviewerId:'nims'})+'. This only proposes assignments. Do not lock scope, dispatch workers or approve work.\n';
}
