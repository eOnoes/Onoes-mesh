import test from 'node:test';import assert from 'node:assert/strict';import {createRelayHttpLink} from '../lib/relay-http.mjs';
const agents=[{"id":"echo","name":"Echo","backend":"fixture","device":"pc","status":"idle","conversation_id":"conversation-echo","approval":null,"budget":null},{"id":"cyony","name":"Cyony","backend":"fixture","device":"pc","status":"idle","conversation_id":"conversation-cyony","approval":null,"budget":null},{"id":"tripp","name":"Tripp","backend":"fixture","device":"pc","status":"idle","conversation_id":"conversation-tripp","approval":null,"budget":null},{"id":"dsh","name":"Dsh","backend":"fixture","device":"pc","status":"idle","conversation_id":"conversation-dsh","approval":null,"budget":null}];
test('compact Python directory maps all synthetic fixture identities using authenticated metadata query',async()=>{
 const calls=[];const link=await createRelayHttpLink({baseUrl:'http://127.0.0.1:9',token:'synthetic-gate',fetchImpl:async(url,options)=>{calls.push({url,method:options.method,auth:options.headers.Authorization});return Response.json(agents);}});
 const result=await link.snapshot();assert.equal(result.status,'fresh');assert.deepEqual(result.agents.map(a=>a.id),agents.map(a=>a.id));assert.deepEqual(calls,[{url:'http://127.0.0.1:9/api/agents?view=directory',method:'GET',auth:'Bearer synthetic-gate'}]);assert.ok(result.agents.every(a=>!('msgs' in a)&&!('feed' in a)));
});
test('compact discovery retains exact conversation guard before an admitted synthetic send',async()=>{
 const calls=[];const link=await createRelayHttpLink({baseUrl:'http://127.0.0.1:9',token:'synthetic-gate',fetchImpl:async(url,options)=>{calls.push({url,options});return Response.json(options.method==='GET'?agents:{ok:true,queued:1});}});
 await link.taskMessage({agentId:'echo',conversationId:'conversation-echo',id:'fixture-only-send',text:'Synthetic fixture only'},()=>true);
 assert.equal(calls.length,2);assert.equal(calls[0].url,'http://127.0.0.1:9/api/agents?view=directory');assert.equal(JSON.parse(calls[1].options.body).expectedConversationId,'conversation-echo');assert.equal(calls[1].options.headers.Authorization,'Bearer synthetic-gate');
});
test('changed conversation after compact discovery blocks POST',async()=>{
 const calls=[];const link=await createRelayHttpLink({baseUrl:'http://127.0.0.1:9',token:'synthetic-gate',fetchImpl:async(url,options)=>{calls.push(options.method);return Response.json(agents);}});
 await assert.rejects(link.taskMessage({agentId:'echo',conversationId:'outdated',id:'fixture-only',text:'Synthetic'},()=>true),e=>e.status===409);assert.deepEqual(calls,['GET']);
});
test('compact query cannot bypass the existing 262144-byte consumer limit',async()=>{
 const methods=[];const link=await createRelayHttpLink({baseUrl:'http://127.0.0.1:9',token:'synthetic-gate',fetchImpl:async(url,options)=>{methods.push(options.method);return Response.json([{...agents[0],approval:'x'.repeat(300000)}]);}});
 await assert.rejects(link.agents(),e=>e.status===503&&!e.message.includes('synthetic-gate'));assert.deepEqual(methods,['GET']);
});
test('an unavailable compact endpoint never falls back to large history or sends',async()=>{
 const calls=[];const link=await createRelayHttpLink({baseUrl:'http://127.0.0.1:9',token:'synthetic-gate',fetchImpl:async(url,options)=>{calls.push(url);return Response.json({error:'unavailable'},{status:503});}});
 const result=await link.snapshot();assert.equal(result.status,'unavailable');assert.deepEqual(calls,['http://127.0.0.1:9/api/agents?view=directory']);
});
