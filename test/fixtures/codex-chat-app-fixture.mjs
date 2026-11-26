// Synthetic app-tools peer: never connects to Codex or invokes a model.
import {createInterface} from 'node:readline';import {randomUUID} from 'node:crypto';import {appendFileSync} from 'node:fs';
const caller='11111111-1111-4111-8111-111111111111',projectId='33333333-3333-4333-8333-333333333333',cwd='C:\\Owned\\Project';
const threads=new Map([[caller,{id:caller,title:'Fixture chat',messages:[]}]]);
const emit=(id,result)=>process.stdout.write(JSON.stringify({jsonrpc:'2.0',id,result})+'\n');
const metadata=t=>({id:t.id,kind:'codex',hostId:'local',cwd,title:t.title,status:{type:'idle'}});
createInterface({input:process.stdin}).on('line',line=>{
 const r=JSON.parse(line);
 if(r.method==='initialize')return emit(r.id,{protocolVersion:'2025-06-18',capabilities:{tools:{}},serverInfo:{name:'synthetic-app-only',version:'1'}});
 if(r.method==='tools/list')return emit(r.id,{tools:['read_thread','list_threads','list_projects','send_message_to_thread','create_thread'].map(name=>({name,inputSchema:{type:'object'}}))});
 if(r.method!=='tools/call')return;
 const {name,arguments:a,_meta:m}=r.params;
 const reply=(data,isError=false)=>emit(r.id,{content:[{type:'text',text:JSON.stringify(data)}],isError});
 if(m.codex_thread_id!==caller)return reply({error:'Wrong synthetic caller'},true);
 if(name==='list_projects')return reply({projects:[{projectKind:'local',hostId:'local',path:cwd,projectId,label:'Fixture project'}]});
 if(name==='list_threads')return reply({threads:[...threads.values()].map(t=>({...metadata(t),projectId})),nextCursor:null});
 if(name==='read_thread'){
  const t=threads.get(a.threadId);if(!t)return reply({error:'Unknown synthetic thread'},true);
  return reply({thread:metadata(t),page:{order:'newest_first',nextCursor:null},turns:a.includeTurns?[{id:'fixture-turn',startedAt:1,completedAt:2,items:t.messages.map(item=>item.type==='functionCallOutput'&&!a.includeOutputs?{type:item.type,id:item.id,name:item.name,namespace:item.namespace}:item)}]:[]});
 }
 if(name==='send_message_to_thread'||name==='create_thread'){
  if(a.model||a.thinking||a.approvalPolicy)return reply({error:'Overrides forbidden'},true);
  const t=name==='create_thread'?{id:randomUUID(),title:a.title||'New fixture chat',messages:[]}:threads.get(a.threadId);
  if(!t||name==='create_thread'&&(a.target.projectId!==projectId||a.target.environment.type!=='local'))return reply({error:'Wrong synthetic destination'},true);
  threads.set(t.id,t);t.messages.push({id:randomUUID(),type:'functionCallOutput',name,namespace:'codex_app',output:{text:'<codex_delegation>\n  <source_thread_id>'+caller+'</source_thread_id>\n  <input>'+a.prompt+'</input>\n</codex_delegation>',truncated:false}},{id:randomUUID(),type:'agentMessage',phase:'final',text:'Synthetic Nims reply'});
  if(process.env.MESH_CODEX_FIXTURE_AUDIT)appendFileSync(process.env.MESH_CODEX_FIXTURE_AUDIT,JSON.stringify({name,threadId:t.id})+'\n');
  if(a.prompt==='SYNTHETIC_LOST_ACK')return process.exit(7);
  return reply({threadId:t.id,hostId:'local'});
 }
 reply({error:'Unsupported synthetic tool'},true);
});
