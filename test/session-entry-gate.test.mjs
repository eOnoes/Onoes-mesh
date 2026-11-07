import test from 'node:test';import assert from 'node:assert/strict';import http from 'node:http';import {spawn}from'node:child_process';import{once}from'node:events';import{randomUUID}from'node:crypto';
test('real serving adapter only advertises automatic entry for its authorized Tailscale identity',async t=>{
 const child=spawn(process.execPath,['serve.mjs'],{windowsHide:true,env:{...process.env,MESH_PREVIEW_PORT:'0',MESH_DATA_DIR:'data/session-entry-gate-'+randomUUID(),MESH_RELAY:'0',MESH_GATE_TOKEN:'fixture-gate-only',MESH_TAILSCALE_HOST:'fixture.ts.net:8453',MESH_TAILSCALE_LOGIN:'owner@example.test'},stdio:['ignore','pipe','pipe']});
 t.after(async()=>{if(child.exitCode===null){const end=once(child,'exit');child.kill();await end;}});
 let output='',errors='';child.stderr.on('data',x=>errors+=x);
 const info=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('Startup deadline '+errors)),10000);child.on('error',reject);child.stdout.on('data',x=>{output+=x;for(const line of output.split('\n')){try{const value=JSON.parse(line);if(value.event==='mesh_listening'){clearTimeout(timer);resolve(value);}}catch{}}});});
 async function request(headers={},method='GET'){return new Promise((resolve,reject)=>{const req=http.request(info.previewUrl+'/gate/status',{method,headers:{Accept:'application/json',...headers}},res=>{let raw='';res.on('data',x=>raw+=x);res.on('end',()=>{let body;try{body=JSON.parse(raw);}catch{}resolve({status:res.statusCode,body});});});req.on('error',reject);req.end();});}
 assert.equal((await request()).body.automaticSession,false);
 const trusted={Host:'fixture.ts.net:8453','Tailscale-User-Login':'owner@example.test'};
 assert.equal((await request(trusted)).body.automaticSession,true);
 assert.equal((await request({...trusted,'Tailscale-User-Login':'other@example.test'})).status,401);
 assert.equal((await request({Host:'fixture.ts.net:8453',Authorization:'Bearer fixture-gate-only'})).body.automaticSession,false);
 assert.equal((await request({...trusted,Host:'wrong.ts.net:8453'})).status,401);
 assert.equal((await request({...trusted,'Sec-Fetch-Site':'cross-site'})).status,403);
 assert.equal((await request(trusted,'POST')).status,405);
});
