import {spawn} from 'node:child_process';
import {join} from 'node:path';
import {existsSync} from 'node:fs';
import {TaskError} from './task-store.mjs';
export function createCodexClient({root,spawnImpl=spawn}={}){
 const executable=join(process.env.APPDATA||'','npm/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe');
 let proc,ready,sequence=0,buffer='',closed=false,authenticated=false;const pending=new Map(),turns=new Map();
 function rejectAll(){authenticated=false;for(const p of pending.values()){clearTimeout(p.timer);p.reject(new TaskError(503,'Nims connection ended. The request was not replayed.'));}pending.clear();for(const t of turns.values()){clearTimeout(t.timer);t.reject(new TaskError(503,'Nims turn interrupted. Inspect its saved receipt.'));}turns.clear();}
 function send(value){if(!proc?.stdin.writable)throw new TaskError(503,'Nims is disconnected.');proc.stdin.write(JSON.stringify(value)+'\n');}
 function rpc(method,params={},timeout=25000){return new Promise((resolve,reject)=>{const id=++sequence;const timer=setTimeout(()=>{pending.delete(id);reject(new TaskError(503,'Nims protocol request timed out; no automatic replay.'));},timeout);pending.set(id,{resolve,reject,timer});try{send({id,method,params});}catch(e){clearTimeout(timer);pending.delete(id);reject(e);}});}
 function receive(message){
  if(message.id!==undefined&&!message.method){const p=pending.get(message.id);if(!p)return;pending.delete(message.id);clearTimeout(p.timer);if(message.error)p.reject(new TaskError(503,'Nims rejected the protocol request.'));else p.resolve(message.result);return;}
  if(message.id!==undefined&&message.method){
   const t=turns.get(message.params?.threadId);if(t)t.blocked=true;
   if(['item/commandExecution/requestApproval','item/fileChange/requestApproval'].includes(message.method))send({id:message.id,result:{decision:'decline'}});
   else send({id:message.id,error:{code:-32601,message:'This Mesh read-only connector does not grant additional permissions or interactive tools.'}});
   return;
  }
  const p=message.params||{},t=turns.get(p.threadId);if(!t)return;
  if(message.method==='item/agentMessage/delta'){t.text+=(p.delta||'');if(t.text.length>262144)t.text=t.text.slice(0,262144);}
  if(message.method==='item/completed'&&p.item?.type==='agentMessage'&&typeof p.item.text==='string')t.finalText=p.item.text.slice(0,262144);
  if(message.method==='turn/completed'){clearTimeout(t.timer);turns.delete(p.threadId);t.resolve({threadId:p.threadId,turnId:p.turn.id,status:p.turn.status,text:t.finalText||t.text,permissionBlocked:t.blocked});}
 }
 async function connect(){
  if(closed)throw new TaskError(503,'Nims connector is closed.');
  if(ready)return ready;
  ready=(async()=>{
   if(!existsSync(executable))throw new TaskError(503,'Installed native Codex runtime not found.');
   const env={...process.env};delete env.OPENAI_API_KEY;delete env.CODEX_API_KEY;delete env.OPENAI_BASE_URL;
   proc=spawnImpl(executable,['app-server','--listen','stdio://','-c','model_provider="openai"','-c','approval_policy="on-request"','-c','sandbox_mode="read-only"'],{cwd:root,env,windowsHide:true,stdio:['pipe','pipe','pipe']});
   const child=proc;buffer='';child.stderr.on('data',()=>{});
   child.on('error',()=>{if(proc===child){ready=null;rejectAll();}});child.on('exit',()=>{if(proc===child){ready=null;rejectAll();}});
   proc.stdout.setEncoding('utf8');proc.stdout.on('data',chunk=>{buffer+=chunk;if(buffer.length>1048576){proc.kill();return;}let newline;while((newline=buffer.indexOf('\n'))>=0){const line=buffer.slice(0,newline);buffer=buffer.slice(newline+1);try{receive(JSON.parse(line));}catch{ /* malformed/diagnostic lines cannot authorize anything */ }}});
   await rpc('initialize',{clientInfo:{name:'onoes_mesh',title:'Nims for Mesh',version:'0.1.0'},capabilities:{experimentalApi:false}});send({method:'initialized',params:{}});
   const account=await rpc('account/read',{refreshToken:false});
   if(!['chatgpt','chatgptAuthTokens'].includes(account.account?.type))throw new TaskError(503,'Nims requires the existing ChatGPT Codex sign-in. API-key billing is not enabled here.');
   authenticated=true;return {connected:true,auth:'chatgpt',mode:'read-only'};
  })().catch(error=>{ready=null;authenticated=false;if(proc&&!proc.killed)proc.kill();throw error;});
  return ready;
 }
 async function run({threadId,text,onBinding=()=>{}}){
  await connect();
  if(!authenticated)throw new TaskError(503,'Nims is not signed in.');
  const policy={cwd:root,approvalPolicy:'on-request',sandbox:'read-only',developerInstructions:'You are Nims, Eddie’s Mesh project lead/reviewer. Follow applicable workspace AGENTS.md. This connector is read-only: plan or review the supplied scoped task. No edits, no worker spawning, no purchases, no credentials or external messages. Request missing scope instead of guessing. Do not use another tool to bypass denied permissions.',serviceName:'onoes_mesh'};
  const result=threadId?await rpc('thread/resume',{threadId,...Object.fromEntries(Object.entries(policy).filter(([k])=>k!=='serviceName'))}):await rpc('thread/start',policy);
  threadId=result.thread.id;await onBinding({threadId});
  if(turns.has(threadId))throw new TaskError(409,'That Nims task already has a turn.');
  let resolve,reject;const completion=new Promise((a,b)=>{resolve=a;reject=b;});
  const timer=setTimeout(()=>{turns.delete(threadId);rpc('turn/interrupt',{threadId,turnId:state.turnId}).catch(()=>{});reject(new TaskError(503,'Nims reached its bounded turn deadline; inspect before retrying.'));},180000);
  const state={resolve,reject,timer,text:'',blocked:false,turnId:null};turns.set(threadId,state);
  try{const turn=await rpc('turn/start',{threadId,input:[{type:'text',text}],sandboxPolicy:{type:'readOnly',networkAccess:false},approvalPolicy:'on-request'});state.turnId=turn.turn.id;await onBinding({threadId,turnId:state.turnId});return await completion;}
  catch(error){clearTimeout(timer);turns.delete(threadId);throw error;}
 }
 return {connect,run,async readThread(threadId){if(!/^[A-Za-z0-9_-]{1,100}$/.test(threadId))throw new TaskError(400,'Invalid native thread identity.');await connect();return rpc('thread/read',{threadId,includeTurns:true});},async close(){closed=true;rejectAll();if(proc){proc.stdin.end();setTimeout(()=>{if(proc&&!proc.killed)proc.kill();},1500).unref();}},get active(){return turns.size;}};
}
