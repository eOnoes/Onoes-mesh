import path from 'node:path';
import {createHash} from 'node:crypto';
import {openCodexRequestStore} from './codex-request-store.mjs';
import {createCodexMessaging} from './codex-messaging.mjs';
import {createCodexAppTransport,validateCodexAppBinding} from './codex-app-transport.mjs';

const uuid=value=>typeof value==='string'&&/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value);
const normalized=value=>path.win32.normalize(String(value).replace(/^\\\\\?\\/,'')).replace(/[\\/]+$/,'').toLowerCase();
const cursor=value=>value===undefined||value===null?undefined:typeof value==='string'&&value.length>0&&value.length<=4096?value:(()=>{throw Error('Invalid history cursor.');})();
const allowed=(object,keys)=>object&&typeof object==='object'&&!Array.isArray(object)&&Object.keys(object).every(key=>keys.includes(key));

export function validateCodexDesktopOptions(options){
  if(!allowed(options,['source','projectDirectory','transport'])||Object.keys(options).length!==3||
    !['native_codex_desktop_readonly','native_codex_desktop_messaging'].includes(options.source)||
    typeof options.projectDirectory!=='string'||options.projectDirectory.length>1024||!(/^[A-Za-z]:[\\/]/).test(options.projectDirectory)||/[\0\r\n]/.test(options.projectDirectory))throw Error('Invalid native Codex project binding.');
  return {...options,transport:validateCodexAppBinding(options.transport)};
}

export async function configureCodexConversations(options,{standalone=false,receiptFilename}={}){
  if(options===undefined)return null;
  if(standalone||!allowed(options,['source','projectDirectory','transport'])||!['native_codex_desktop_readonly','native_codex_desktop_messaging'].includes(options.source))throw Error('Native Codex access requires its trusted connected profile.');
  options=validateCodexDesktopOptions(options);
  const messaging=options.source==='native_codex_desktop_messaging';
  if(messaging&&!path.isAbsolute(receiptFilename??''))throw Error('Native messaging requires its owned receipt store.');
  const reader=await createCodexAppTransport(options.transport,{allowMessaging:messaging});
  let requestStore;
  try{
    if(messaging)requestStore=openCodexRequestStore(receiptFilename);
    return createCodexConversations({reader,projectDirectory:options.projectDirectory,callerThreadId:options.transport.callerThreadId,requestStore});
  }catch(error){await reader.close();requestStore?.close();throw error;}
}

// Native Codex owns conversations/history. Mind receives deliberate handoffs only.
export function createCodexConversations({reader,projectDirectory,callerThreadId,requestStore=null}){
  if(!reader||typeof reader.read!=='function'||!(/^[A-Za-z]:[\\/]/).test(projectDirectory??'')||!uuid(callerThreadId))throw Error('Invalid Codex conversation scope.');
  const scope=normalized(projectDirectory);
  const scopeKey=createHash('sha256').update(scope).digest('hex');
  const same=thread=>thread?.kind==='codex'&&thread.hostId==='local'&&normalized(thread.cwd)===scope;
  async function inspect(threadId){
    if(!uuid(threadId))throw Error('Choose a valid Codex conversation.');
    const reply=await reader.read('read_thread',{threadId,hostId:'local',includeTurns:false});
    if(!same(reply.thread)||reply.thread.id!==threadId)throw Error('Conversation is outside the approved native project.');
    return reply.thread;
  }
  async function verifyCaller(){await inspect(callerThreadId);}
  async function project(){
    const reply=await reader.read('list_projects',{});
    const selected=reply.projects?.filter(p=>p.projectKind==='local'&&p.hostId==='local'&&normalized(p.path)===scope);
    if(selected?.length!==1)throw Error('Native project identity is unavailable or ambiguous.');
    return selected[0];
  }
  const messaging=requestStore?createCodexMessaging({transport:reader,store:requestStore,
    scopeKey,verifyCaller,inspect,project}):null;
  function identity(thread){return {id:thread.id,title:thread.title||'Untitled chat',status:typeof thread.status==='string'?thread.status:thread.status?.type||'unknown',projectId:thread.projectId??null};}
  return {
    readOnly:!messaging,
    send:messaging?.send,create:messaging?.create,receipt:messaging?.receipt,
    async catalog(input={}){
      if(!allowed(input,['cursor']))throw Error('Catalog accepts only its next-page cursor.');
      await verifyCaller();
      const selected=await project();
      const params={mode:'history',source:'codex',hostId:'local',archived:false,limit:50};
      const next=cursor(input.cursor);if(next)params.cursor=next;
      const result=await reader.read('list_threads',params);
      if(!Array.isArray(result.threads))throw Error('Native conversation list is unavailable.');
      return {source:'codex_desktop',readOnly:!messaging,project:{id:selected.projectId,label:selected.label},
        conversations:result.threads.filter(t=>same(t)&&t.projectId===selected.projectId).map(identity),
        nextCursor:cursor(result.nextCursor)??null};
    },
    async history(input){
      if(!allowed(input,['threadId','cursor','itemCursor'])||!uuid(input.threadId)||input.cursor&&input.itemCursor)throw Error('Choose one conversation and one history page.');
      await verifyCaller();const metadata=await inspect(input.threadId);
      const params={threadId:input.threadId,hostId:'local',includeTurns:true,includeOutputs:Boolean(requestStore),...input.itemCursor?{}:{turnLimit:3},itemLimit:50,maxOutputCharsPerItem:20000};
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
          // App-tools messages are native delegation envelopes rather than userMessage.
          // Expose only an exact native wrapper, this verified caller, and a matching
          // own delivery receipt. Arbitrary tool output/reasoning stays excluded.
          if(requestStore&&item.type==='functionCallOutput'&&item.namespace==='codex_app'&&
            ['create_thread','send_message_to_thread'].includes(item.name)&&item.output?.truncated===false&&typeof item.output.text==='string'){
            const envelope=/^<codex_delegation>\n  <source_thread_id>([a-f0-9-]{36})<\/source_thread_id>\n  <input>([\s\S]*)<\/input>\n<\/codex_delegation>$/.exec(item.output.text);
            if(envelope&&envelope[1]===callerThreadId&&requestStore.knowsNativePrompt(scopeKey,input.threadId,item.name,envelope[2]))
              add({id:turn.id+'/'+item.id,role:'user',text:envelope[2],viaRelay:true,truncated:false,at:turn.startedAt??null});
          }
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
      return {source:'codex_desktop',readOnly:!messaging,conversation:identity({...metadata,status:result.thread.status}),messages,groups,
        olderTurnCursor:cursor(result.page?.nextCursor)??null,
        olderItemCursors:result.turns.filter(t=>t.nextItemCursor).map(t=>({turnId:t.id,cursor:cursor(t.nextItemCursor)})),
        observedAt:new Date().toISOString()};
    },
    async close(){await reader.close?.();await messaging?.close();requestStore?.close();}
  };
}
