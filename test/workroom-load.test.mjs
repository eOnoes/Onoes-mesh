import test from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {createBoardLoader} from '../public/workroom-load.mjs';
import {startApp} from '../server.mjs';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};

test('saved cards finish loading while the agent read remains unresolved',async()=>{
 const peers=deferred(),boards=[],observations=[],calls=[];
 const saved={tasks:[{id:'saved-card',title:'Visible without searching'}]};
 const loader=createBoardLoader({request:async path=>{calls.push(path);return path==='/api/workroom'?saved:peers.promise;},onBoard:b=>boards.push(b),onAgents:a=>observations.push(a)});
 assert.equal(await loader.load(),saved);assert.deepEqual(boards,[saved]);assert.deepEqual(observations,[]);
 assert.deepEqual(calls,['/api/workroom','/api/relay/native/api/agents']);
 peers.resolve([{id:'echo'}]);await tick();assert.deepEqual(observations,[[{id:'echo'}]]);
});

test('repeated card refreshes share the slow peer read and apply only the latest observation',async()=>{
 const peers=deferred(),boards=[],observations=[];let reads=0,peerReads=0;
 const loader=createBoardLoader({request:async path=>path==='/api/workroom'?{tasks:[{id:String(++reads)}]}:(peerReads++,peers.promise),onBoard:b=>boards.push(b),onAgents:a=>observations.push(a)});
 for(let i=0;i<6;i++)await loader.load();
 assert.equal(boards.length,6);assert.equal(peerReads,1);assert.equal(boards.at(-1).tasks[0].id,'6');
 peers.resolve([{id:'echo'}]);await tick();assert.equal(observations.length,1);
});

test('private clearance rejects a late saved-card response',async()=>{
 const cards=deferred(),boards=[],observations=[];
 const loader=createBoardLoader({request:()=>cards.promise,onBoard:b=>boards.push(b),onAgents:a=>observations.push(a)});
 const reading=loader.load();loader.clear();cards.resolve({tasks:[{title:'Private old card'}]});await reading;
 assert.deepEqual(boards,[]);assert.deepEqual(observations,[]);
});

test('reconnect starts a fresh peer read without accepting the old admission result',async()=>{
 const old=deferred(),fresh=deferred(),observations=[];let peerReads=0;
 const loader=createBoardLoader({request:async path=>path==='/api/workroom'?{tasks:[]}:(++peerReads===1?old.promise:fresh.promise),onBoard:()=>{},onAgents:a=>observations.push(a)});
 await loader.load();loader.clear();await loader.load();assert.equal(peerReads,2);
 old.resolve([{id:'private-old-peer'}]);await tick();assert.deepEqual(observations,[]);
 fresh.resolve([{id:'new-peer'}]);await tick();assert.deepEqual(observations,[[{id:'new-peer'}]]);
});

test('peer failure leaves cards usable and a later refresh can recover',async()=>{
 let fail=true;const boards=[],observations=[];
 const loader=createBoardLoader({request:async path=>{if(path==='/api/workroom')return {tasks:[{id:'saved'}]};if(fail)throw Error('peer unavailable');return [{id:'echo'}];},onBoard:b=>boards.push(b),onAgents:(a,available)=>observations.push({a,available})});
 await loader.load();await tick();assert.equal(boards.length,1);assert.deepEqual(observations,[{a:[],available:false}]);
 fail=false;await loader.load();await tick();assert.equal(boards.length,2);assert.equal(observations.at(-1).available,true);
});

test('the actual app serves the board loader module unchanged',async()=>{
 const app=await startApp({dataDir:'data/board-loader-http-'+randomUUID(),relayEnabled:false});
 try{const r=await fetch(app.url+'/workroom-load.mjs');assert.equal(r.status,200);assert.equal(await r.text(),await readFile(new URL('../public/workroom-load.mjs',import.meta.url),'utf8'));}finally{await app.close();}
});
