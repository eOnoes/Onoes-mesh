// Read-only browser fixture. No execution/model endpoint is exposed.
import http from 'node:http';
import {randomUUID} from 'node:crypto';
import {startApp} from '../server.mjs';
process.env.MESH_STANDALONE='1';
const app=await startApp({dataDir:'data/host-browser-'+randomUUID(),relayEnabled:false});
const tasks=[];
const server=http.createServer(async(req,res)=>{
  const path=new URL(req.url,'http://localhost').pathname;
  const json=(status,body)=>{req.resume();res.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store'});res.end(JSON.stringify(body));};
  if(path==='/api/trial-session/bootstrap'&&req.method==='POST')return json(201,{csrfToken:'f'.repeat(43),expiresAt:Date.now()+600000});
  if(path==='/api/trial-session/logout'&&req.method==='POST')return json(200,{});
  if(!['GET','HEAD'].includes(req.method))return json(405,{error:'Read-only fixture; no work can be sent.'});
  if(path==='/api/tasks')return json(200,{tasks});
  if(path.startsWith('/api/tasks/'))return json(200,{task:tasks.find(t=>t.id===path.split('/').at(-1))});
  if(path==='/api/commands')return json(200,{commands:[]});
  if(path==='/api/health')return json(200,{state:'ok',persistence:'disposable_fixture',activity:{source:'none'}});
  if(path==='/api/workroom')return json(200,{tasks:[]});
  if(path.startsWith('/api/'))return json(200,{});
  if(path==='/inference/summary'&&process.argv.includes('--stall')){req.resume();return;}
  if(path==='/inference/summary')return json(200,{generatedAt:'2000-01-01T00:00:00.000Z',host:'STALE UI FIXTURE - no hardware probed',gpu:{name:'SHOULD NEVER DISPLAY',utilPct:99}});
  try{const upstream=await fetch(app.url+req.url);res.writeHead(upstream.status,{'Content-Type':upstream.headers.get('content-type')||'text/plain','Cache-Control':'no-store'});res.end(req.method==='HEAD'?undefined:Buffer.from(await upstream.arrayBuffer()));}
  catch{return json(503,{error:'Fixture asset unavailable'});}
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
console.log(JSON.stringify({url:'http://127.0.0.1:'+server.address().port+'/#control',pid:process.pid,scope:'Disposable synthetic UI only; no process or model execution'}));
let stopping=false;
async function stop(){if(stopping)return;stopping=true;await new Promise(resolve=>server.close(resolve));await app.close();process.stdin.pause();}
process.on('SIGINT',()=>void stop());process.on('SIGTERM',()=>void stop());

process.stdin.on('data',chunk=>{if(String(chunk).trim()==='stop')void stop();});
