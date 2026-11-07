import {test} from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {mockUI,flush} from './app-ui-fixture.mjs';

test('Relay keeps both speakers and preserves reading position when a reply arrives',async()=>{
 const ui=mockUI();await flush();
 let messages=[{id:1,k:'you',t:'Test'}];
 ui.context.chatRequest=async route=>route==='/relay/api/agents'?[{id:'echo',name:'Echo',conversation_id:'session-1'}]:{messages};
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
