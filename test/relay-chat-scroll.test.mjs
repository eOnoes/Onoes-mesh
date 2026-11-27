import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {mockUI,flush} from './app-ui-fixture.mjs';

test('Relay keeps both speakers and preserves reading position when a reply arrives',async()=>{
 const ui=mockUI();await flush();
 let messages=[{id:1,k:'you',t:'Test'}];
 ui.context.chatRequest=async route=>route==='/api/relay/native/api/agents'?[{id:'echo',name:'Echo',conversation_id:'session-1'}]:{messages};
 vm.runInContext('var scrollChat=createRelayChat({request:chatRequest});scrollChat.setAvailable(true)',ui.context);await flush();
 const transcript=ui.ids.get('relay-chat');transcript.clientHeight=300;transcript.scrollHeight=1500;
 ui.ids.get('relay-chat-agent').value='echo';await ui.ids.get('relay-chat-agent').events.change();await flush();
 assert.equal(transcript.scrollTop,1500,'first selection opens at latest message');
 transcript.scrollTop=200;
 messages=[...messages,{id:2,k:'ag',t:'Received.'}];
 await vm.runInContext('scrollChat.refresh()',ui.context);
 assert.equal(transcript.scrollTop,200,'reading earlier history must not jump to latest');
 const nodes=transcript.children[0].children;
 assert.equal(nodes.length,2);assert.equal(nodes[0].children[0].textContent,'You');assert.equal(nodes[1].children[0].textContent,'Echo');
 assert.equal(nodes[0].children[1].children[0].textContent,'Test');assert.equal(nodes[1].children[1].children[0].textContent,'Received.');
 transcript.scrollTop=1190;
 messages=[...messages,{id:3,k:'ag',t:'Another reply'}];
 await vm.runInContext('scrollChat.refresh()',ui.context);
 assert.equal(transcript.scrollTop,1500,'a reader near the bottom follows replies');
 scrollChatCleanup();
 function scrollChatCleanup(){vm.runInContext('scrollChat.clear()',ui.context);}
});


test('Load older messages keeps the same passage under the reader and clears the control on lock',async()=>{
 const ui=mockUI();await flush();
 const page=(first,last)=>({messages:Array.from({length:last-first+1},(_,i)=>({id:first+i,k:'ag',t:'Message '+(first+i)})),oldest_id:first,newest_id:last,has_more:first>1});
 ui.context.chatRequest=async route=>route==='/api/relay/native/api/agents'?[{id:'echo',name:'Echo',conversation_id:'session-1'}]:route.includes('&before=')?page(1,10):page(11,20);
 vm.runInContext('var pagingChat=createRelayChat({request:chatRequest});pagingChat.setAvailable(true)',ui.context);await flush();
 const transcript=ui.ids.get('relay-chat');transcript.clientHeight=300;
 Object.defineProperty(transcript,'scrollHeight',{get(){return (this.children[0]?.children.length||0)*100;}});
 ui.ids.get('relay-chat-agent').value='echo';await ui.ids.get('relay-chat-agent').events.change();await flush();
 const older=ui.ids.get('relay-chat-older');assert.equal(older.hidden,false);transcript.scrollTop=200;
 older.events.click();await flush();assert.equal(transcript.children[0].children.length,20);
 assert.equal(transcript.scrollTop,1200,'prepending one thousand pixels preserves the same visible passage');assert.equal(older.hidden,true);
 vm.runInContext('pagingChat.clear()',ui.context);assert.equal(older.hidden,true);assert.equal(transcript.children[0].children.length,0);assert.ok(!transcript.children[0].textContent.includes('Message '));
});

test('Long Relay paste remains visible with send disabled until shortened', async () => {
 const ui=mockUI(); await flush();
 ui.context.chatRequest=async route=>route==='/api/relay/native/api/agents'
   ? [{id:'echo',name:'Echo',conversation_id:'session-1'}]
   : route==='/relay/api/mesh-capabilities' ? {taskSessionBinding:1} : {messages:[]};
 vm.runInContext('var lengthChat=createRelayChat({request:chatRequest});lengthChat.setAvailable(true)',ui.context);
 await flush(); ui.ids.get('relay-chat-agent').value='echo';
 await ui.ids.get('relay-chat-agent').events.change(); await flush();
 const composer=ui.ids.get('relay-text'), send=ui.ids.get('relay-send'), status=ui.ids.get('relay-chat-status');
 const oversized='p'.repeat(4000)+'KEEP THIS SUFFIX';
 try {
   composer.value=oversized; composer.events.input();
   assert.equal(composer.value,oversized); assert.equal(send.disabled,true);
   assert.match(status.textContent,/4016\/4000.*shorten/i);
   await vm.runInContext('lengthChat.refresh()',ui.context);
   assert.equal(composer.value,oversized); assert.match(status.textContent,/4016\/4000/);
   composer.value='shortened complete message'; composer.events.input();
   assert.equal(send.disabled,false); assert.doesNotMatch(status.textContent,/4016\/4000|shorten/i);
 } finally {vm.runInContext('lengthChat.clear()',ui.context);}
});

test('Only ordinary Relay composer removes the browser truncation limit and describes its status', async () => {
 const {readFile}=await import('node:fs/promises');
 const markup=await readFile(new URL('../public/index.html',import.meta.url),'utf8');
 const composer=markup.match(/<textarea\b[^>]*\bid="relay-text"[^>]*>/)?.[0];
 assert.ok(composer); assert.doesNotMatch(composer,/\bmaxlength\s*=/i);
 assert.match(composer,/aria-describedby="relay-chat-status"/);
 assert.match(markup,/<textarea\b[^>]*\bid="nims-message"[^>]*maxlength="4000"/);
 assert.match(markup,/<textarea\b[^>]*\bid="create-description"[^>]*maxlength="4000"/);
});
