import test from 'node:test';
import assert from 'node:assert/strict';
import {createSupervisorObservation} from '../lib/supervisor-observation.mjs';
const ids=new Map([[18090,'qwen3.8-flash-next-iq3-s'],[18091,'qwen3.6-35b-a3b-ud-q6_k_xl'],[8098,'qwen3.8-27b'],[8099,'nemotron-3.5-bolt-74b-a9b']]);
function fixture(change=()=>{}) {
  const calls=[];
  const fetchImpl=async(url,options)=>{
    calls.push({url,options});const u=new URL(url),port=Number(u.port),id=ids.get(port);
    assert.equal(u.hostname,'127.0.0.1');assert.ok(ids.has(port));
    assert.ok(['/health','/v1/models'].includes(u.pathname));assert.equal(options.method,'GET');
    assert.equal(options.redirect,'manual');assert.equal(options.credentials,'omit');assert.equal(options.cache,'no-store');
    const body=u.pathname==='/health'?{port,model:id,loaded:port===8099,loading:false,servable:port!==8098,detail:port===8098?'missing file(s): private/path':'ok'}
      :{data:[{id,owned_by:'dsh-local-supervisor',loaded:port===8099}]};
    const override=change(body,u,options);
    return override ?? Response.json(body);
  };
  return {calls,read:createSupervisorObservation({enabled:true,fetchImpl,now:()=>1700000000000})};
}
test('disabled observer does not call native services; enabled observer uses only eight fixed read-only routes',async()=>{
  const disabled=createSupervisorObservation({fetchImpl:()=>{throw Error('must not call');}});
  assert.equal((await disabled()).state,'not_configured');
  const f=fixture(),s=await f.read();assert.equal(f.calls.length,8);assert.equal(s.state,'fresh');
  assert.equal(s.models[3].state,'reported_loaded');assert.equal(s.models[0].state,'ready');
  assert.equal(s.models[2].reason,'model_files_missing');assert.equal(s.controls,false);
  assert.equal(s.custody,'unverified');assert.equal(s.gpuMapping,'unverified');
  assert.equal(s.expiresAt,1700000005000);assert.ok(!JSON.stringify(s).includes('private/path'));
});
test('wrong alias, owner, loaded agreement or health shape becomes unknown rather than a resident model',async()=>{
  for(const mutate of [b=>{if(b.model)b.model='different';},b=>{if(b.data)b.data[0].owned_by='other';},
    b=>{if(b.data)b.data[0].loaded=true;},b=>{if(b.model)delete b.loading;}]) {
    const f=fixture((b,u)=>{if(u.port==='18090')mutate(b);}),s=await f.read();
    assert.equal(s.models[0].state,'unknown');assert.equal(s.models[0].loaded,null);assert.equal(s.state,'partial');
  }
});
test('redirects, large bodies, non-JSON and failed requests never leak remote text or retain old observations',async()=>{
  for(const response of [()=>new Response('secret',{status:302,headers:{location:'https://other.invalid'}}),
    ()=>new Response('x'.repeat(17000),{headers:{'content-type':'application/json'}}),()=>new Response('private text'),
    ()=>{throw Error('private error');}]) {
    const f=fixture(()=>response()),s=await f.read();assert.equal(s.state,'unavailable');
    assert.ok(s.models.every(m=>m.state==='unknown'&&m.loaded===null));assert.ok(!JSON.stringify(s).includes('private'));
  }
});
test('concurrent status reads share one probe set; later reads refresh without replaying model work',async()=>{
  const f=fixture();const [a,b]=await Promise.all([f.read(),f.read()]);assert.equal(f.calls.length,8);assert.deepEqual(a,b);
  await f.read();assert.equal(f.calls.length,16);
});
test('global supervisor loading is not mistaken for a ready or verified resident model',async()=>{
  const f=fixture(b=>{if(b.model)b.loading=true;}),s=await f.read();
  assert.ok(s.models.every(m=>m.state==='loading_unconfirmed'&&m.loaded===null));assert.equal(s.controls,false);
});
test('native read deadlines fail closed without probing generation or admin routes',async()=>{
  const calls=[];const read=createSupervisorObservation({enabled:true,timeoutMs:15,fetchImpl:(url,{signal,method})=>{
    calls.push({url,method});return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(Error('timeout')),{once:true}));
  }});
  // Keep the test's event loop live; production HTTP sockets already do that.
  const hold=setTimeout(()=>{},1000);
  try{assert.equal((await read()).state,'unavailable');assert.equal(calls.length,8);assert.ok(calls.every(c=>c.method==='GET'));}
  finally{clearTimeout(hold);}
});
