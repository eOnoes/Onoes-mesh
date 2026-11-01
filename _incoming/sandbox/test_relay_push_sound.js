'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const stored=new Map();
function worker(){
 const handlers={},shown=[];
 const indexedDB={open(){const req={};queueMicrotask(()=>{
  req.result={createObjectStore(){},close(){},transaction(){const tx={};tx.objectStore=()=>({get(k){const r={};queueMicrotask(()=>{r.result=stored.get(k);r.onsuccess();tx.oncomplete();});return r;},put(v,k){const r={};queueMicrotask(()=>{stored.set(k,v);r.onsuccess();tx.oncomplete();});return r;}});return tx;}};
  req.onsuccess();
 });return req;}};
 const c={indexedDB,URL,Response,fetch,console,self:{location:{origin:'https://private.test'},addEventListener:(n,f)=>handlers[n]=f,registration:{showNotification:async(t,o)=>shown.push(o)},clients:{}}};
 vm.createContext(c);vm.runInContext(fs.readFileSync('mesh-sw.js','utf8'),c);
 return{handlers,shown};
}
(async()=>{
 let w=worker(),pending,ack;
 w.handlers.message({data:{type:'relay-push-sound',silent:true},ports:[{postMessage:d=>ack=d}],waitUntil:p=>pending=p});await pending;assert(ack.ok);
 // A fresh worker simulates termination/restart; preference must survive.
 w=worker();w.handlers.push({data:{json:()=>({body:'private text must never render'})},waitUntil:p=>pending=p});await pending;
 assert.strictEqual(w.shown[0].silent,true);assert.strictEqual(w.shown[0].body,'New Relay message');
 w.handlers.message({data:{type:'relay-push-sound',silent:false},ports:[{postMessage:d=>ack=d}],waitUntil:p=>pending=p});await pending;
 w=worker();w.handlers.push({waitUntil:p=>pending=p});await pending;assert(!('silent' in w.shown[0]));
 assert.deepStrictEqual([...stored.keys()],['silent']);console.log('PASS persisted boolean sound preference across worker restarts; generic alert and device-default fallback');
})().catch(e=>{console.error(e);process.exit(1);});
