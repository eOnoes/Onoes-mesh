import test from 'node:test';
import assert from 'node:assert/strict';
import {createCodexConversations} from '../lib/codex-conversations.mjs';

const current='11111111-1111-4111-8111-111111111111',other='22222222-2222-4222-8222-222222222222';
const cwd='C:\\Owned\\Project';
const thread=id=>({id,kind:'codex',hostId:'local',cwd,title:'Native title',status:{type:'idle'}});
function fixture(handler){
  const calls=[];const reader={async read(name,args){calls.push({name,args});return handler(name,args,calls);},async close(){}};
  return {calls,api:createCodexConversations({reader,projectDirectory:cwd,callerThreadId:current})};
}
test('catalog filters other projects and hosts while retaining native title and cursor',async()=>{
  const {api,calls}=fixture((name,args)=>name==='read_thread'?{thread:thread(args.threadId)}:name==='list_projects'?{projects:[{projectKind:'local',hostId:'local',path:cwd,projectId:'p1',label:'Project'}]}:{threads:[
    {...thread(current),projectId:'p1'}, {...thread(other),cwd:'C:\\Other',projectId:'p2'}, {...thread(other),hostId:'remote',projectId:'p1'}],nextCursor:'native-next'});
  const result=await api.catalog();assert.equal(result.conversations.length,1);assert.equal(result.conversations[0].id,current);
  assert.equal(result.nextCursor,'native-next');assert.equal(result.readOnly,true);
  assert.equal(calls.at(-1).args.hostId,'local');assert.equal(calls.at(-1).args.archived,false);
});
test('out-of-project metadata prevents reading its history',async()=>{
  const {api,calls}=fixture((name,args)=>({thread:{...thread(args.threadId),cwd:args.threadId===current?cwd:'C:\\Other'}}));
  await assert.rejects(api.history({threadId:other}),/outside/);assert.equal(calls.length,2);
  assert.ok(calls.every(c=>c.args.includeTurns===false));
});
test('native chat items remain separate; tool and reasoning text never become messages',async()=>{
  const {api}=fixture((name,args)=>args.includeTurns?{thread:thread(current),page:{nextCursor:'older-turn'},turns:[{id:'t1',status:'completed',startedAt:1,completedAt:2,nextItemCursor:'older-items',items:[
    {id:'u',type:'userMessage',content:[{type:'text',text:'Hello'}]},
    {id:'r',type:'reasoning',summary:['private reasoning']},
    {id:'c',type:'commandExecution',command:'private command'},
    {id:'a',type:'agentMessage',text:'Reply',textTruncated:true}
  ]}]}:{thread:thread(args.threadId)});
  const result=await api.history({threadId:current});assert.deepEqual(result.messages.map(m=>[m.role,m.text]),[['user','Hello'],['assistant','Reply']]);
  assert.equal(result.messages[1].truncated,true);assert.equal(result.olderItemCursors[0].cursor,'older-items');assert.equal(result.olderTurnCursor,'older-turn');
});
test('selection changing during a read refuses the returned native history',async()=>{
  const {api}=fixture((name,args)=>args.includeTurns?{thread:{...thread(current),cwd:'C:\\Other'},turns:[]}:{thread:thread(args.threadId)});
  await assert.rejects(api.history({threadId:current}),/identity changed/);
});
test('browser cannot supply another host, project, source or caller context',async()=>{
  const {api,calls}=fixture(()=>{throw Error('must not read');});
  await assert.rejects(api.catalog({hostId:'remote'}));
  await assert.rejects(api.history({threadId:current,callerThreadId:other}));
  await assert.rejects(api.history({threadId:current,cursor:'a',itemCursor:'b'}));
  assert.equal(calls.length,0);
});
test('a native page containing only tools keeps its older item cursor',async()=>{
  const {api}=fixture((name,args)=>args.includeTurns?{thread:thread(current),page:{nextCursor:null},turns:[{id:'t',items:[{id:'tool',type:'commandExecution'}],nextItemCursor:'more'}]}:{thread:thread(args.threadId)});
  const result=await api.history({threadId:current});assert.deepEqual(result.messages,[]);assert.equal(result.olderItemCursors[0].cursor,'more');
});

test('native item-page requests do not ask for multiple turns',async()=>{
  const {api,calls}=fixture((name,args)=>args.itemCursor?{threadId:current,turnId:'native-turn',items:[],nextItemCursor:null}:{thread:thread(args.threadId)});
  await api.history({threadId:current,itemCursor:'native-item-cursor'});
  const pageCall=calls.find(c=>c.args.itemCursor);
  assert.equal(pageCall.args.itemCursor,'native-item-cursor');
  assert.equal(pageCall.args.turnLimit,undefined);
});

test('the actual native item-page shape retains its thread, turn, user text and next cursor',async()=>{
  const {api}=fixture((name,args)=>args.itemCursor?{threadId:current,turnId:'turn-native',items:[{id:'user-native',type:'userMessage',content:[{type:'text',text:'Earlier user message'}]}],nextItemCursor:'next-native-item'}:{thread:thread(args.threadId)});
  const result=await api.history({threadId:current,itemCursor:'cursor'});
  assert.equal(result.groups[0].id,'turn-native');assert.equal(result.messages[0].text,'Earlier user message');assert.equal(result.groups[0].olderItemCursor,'next-native-item');
});
test('a native item cursor returning another thread is refused before display',async()=>{
  const {api}=fixture((name,args)=>args.itemCursor?{threadId:other,turnId:'turn-native',items:[]}:{thread:thread(args.threadId)});
  await assert.rejects(api.history({threadId:current,itemCursor:'wrong-thread-cursor'}),/identity changed/);
});

test('native browser activity markers render as a label while user text remains literal',async()=>{
  const marker='::browser-complete{title="Checked the browser"}';
  const {api}=fixture((name,args)=>args.includeTurns?{thread:thread(current),page:{nextCursor:null},turns:[{id:'turn',items:[{id:'u',type:'userMessage',content:[{type:'text',text:marker}]},{id:'a',type:'agentMessage',phase:'commentary',text:marker}]}]}:{thread:thread(args.threadId)});
  const result=await api.history({threadId:current});assert.equal(result.messages[0].text,marker);assert.equal(result.messages[1].text,'Browser activity: Checked the browser');
});
