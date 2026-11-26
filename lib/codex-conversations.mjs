import path from 'node:path';
import {createCodexAppTransport} from './codex-app-transport.mjs';

const uuid=value=>typeof value==='string'&&/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value);
const normalized=value=>path.win32.normalize(String(value).replace(/^\\\\\?\\/,'')).replace(/[\\/]+$/,'').toLowerCase();
const cursor=value=>value===undefined||value===null?undefined:typeof value==='string'&&value.length>0&&value.length<=4096?value:(()=>{throw Error('Invalid history cursor.');})();
const allowed=(object,keys)=>object&&typeof object==='object'&&!Array.isArray(object)&&Object.keys(object).every(key=>keys.includes(key));

export async function configureCodexConversations(options,{standalone=false}={}){
  if(options===undefined)return null;
  if(standalone||!allowed(options,['source','projectDirectory','transport'])||options.source!=='native_codex_desktop_readonly')throw Error('Native Codex access requires its trusted connected profile.');
  const reader=await createCodexAppTransport(options.transport);
  try{return createCodexConversations({reader,projectDirectory:options.projectDirectory,callerThreadId:options.transport.callerThreadId});}
  catch(error){await reader.close();throw error;}
}

// Native Codex owns conversations/history. Mind receives deliberate handoffs only.
export function createCodexConversations({reader,projectDirectory,callerThreadId}){
  if(!reader||typeof reader.read!=='function'||!(/^[A-Za-z]:[\\/]/).test(projectDirectory??'')||!uuid(callerThreadId))throw Error('Invalid Codex conversation scope.');
  const scope=normalized(projectDirectory);
  const same=thread=>thread?.kind==='codex'&&thread.hostId==='local'&&normalized(thread.cwd)===scope;
  async function inspect(threadId){
    if(!uuid(threadId))throw Error('Choose a valid Codex conversation.');
    const reply=await reader.read('read_thread',{threadId,hostId:'local',includeTurns:false});
    if(!same(reply.thread)||reply.thread.id!==threadId)throw Error('Conversation is outside the approved native project.');
    return reply.thread;
  }
  async function verifyCaller(){await inspect(callerThreadId);}
  function identity(thread){return {id:thread.id,title:thread.title||'Untitled chat',status:typeof thread.status==='string'?thread.status:thread.status?.type||'unknown',projectId:thread.projectId??null};}
  return {
    async catalog(input={}){
      if(!allowed(input,['cursor']))throw Error('Catalog accepts only its next-page cursor.');
      await verifyCaller();
      const projects=await reader.read('list_projects',{});
      const selected=projects.projects?.filter(p=>p.projectKind==='local'&&p.hostId==='local'&&normalized(p.path)===scope);
      if(selected?.length!==1)throw Error('Native project identity is unavailable or ambiguous.');
      const params={mode:'history',source:'codex',hostId:'local',archived:false,limit:50};
      const next=cursor(input.cursor);if(next)params.cursor=next;
      const result=await reader.read('list_threads',params);
      if(!Array.isArray(result.threads))throw Error('Native conversation list is unavailable.');
      return {source:'codex_desktop',readOnly:true,project:{id:selected[0].projectId,label:selected[0].label},
        conversations:result.threads.filter(t=>same(t)&&t.projectId===selected[0].projectId).map(identity),
        nextCursor:cursor(result.nextCursor)??null};
    },
    async history(input){
      if(!allowed(input,['threadId','cursor','itemCursor'])||!uuid(input.threadId)||input.cursor&&input.itemCursor)throw Error('Choose one conversation and one history page.');
      await verifyCaller();const metadata=await inspect(input.threadId);
      const params={threadId:input.threadId,hostId:'local',includeTurns:true,includeOutputs:false,...input.itemCursor?{}:{turnLimit:3},itemLimit:50,maxOutputCharsPerItem:20000};
      for(const name of ['cursor','itemCursor']){const value=cursor(input[name]);if(value)params[name]=value;}
      let result=await reader.read('read_thread',params);
      if(input.itemCursor){
        // The first-party item cursor returns an item page, not a thread page.
        if(result.threadId!==input.threadId||typeof result.turnId!=='string'||!Array.isArray(result.items))throw Error('Native item-page identity changed.');
        const currentMetadata=await inspect(input.threadId);
        result={thread:currentMetadata,turns:[{id:result.turnId,items:result.items,nextItemCursor:result.nextItemCursor}],page:{nextCursor:null}};
      }
      if(!same(result.thread)||result.thread.id!==input.threadId||!Array.isArray(result.turns))throw Error('Native history identity changed.');
      const messages=[],groups=[];
      for(const turn of [...result.turns].reverse()){
        const group={id:turn.id,messages:[],olderItemCursor:cursor(turn.nextItemCursor)??null};
        const add=message=>{messages.push(message);group.messages.push(message);};
        for(const item of turn.items??[]){
          if(item.type==='agentMessage'&&typeof item.text==='string')add({id:turn.id+'/'+item.id,role:'assistant',text:item.phase==='commentary'&&/^::browser-complete\{title="[^"\r\n]*"\}\s*$/.test(item.text)?'Browser activity: '+item.text.match(/title="([^"]*)"/)[1]:item.text,truncated:item.textTruncated===true||item.truncated===true,at:turn.completedAt??turn.startedAt??null});
          if(item.type==='userMessage'){
            const parts=Array.isArray(item.content)?item.content.filter(c=>c.type==='text'&&typeof c.text==='string'):[];
            if(parts.length)add({id:turn.id+'/'+item.id,role:'user',text:parts.map(c=>c.text).join('\n'),truncated:item.textTruncated===true||item.truncated===true,at:turn.startedAt??null});
          }
        }
        groups.push(group);
      }
      // A native turn can have many tool items. Preserve its item cursor instead
      // of pretending a page with no chat messages is the end of history.
      return {source:'codex_desktop',readOnly:true,conversation:identity({...metadata,status:result.thread.status}),messages,groups,
        olderTurnCursor:cursor(result.page?.nextCursor)??null,
        olderItemCursors:result.turns.filter(t=>t.nextItemCursor).map(t=>({turnId:t.id,cursor:cursor(t.nextItemCursor)})),
        observedAt:new Date().toISOString()};
    },
    close:()=>reader.close?.()
  };
}
