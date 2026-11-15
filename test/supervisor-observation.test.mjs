import test from 'node:test';
import assert from 'node:assert/strict';
import {createSupervisorObservation} from '../lib/supervisor-observation.mjs';
import {isQualifiedSupervisorOwner,probeSupervisorOwner,SUPERVISOR_MODEL_PORTS} from '../lib/supervisor-port-owner.mjs';
import {readFileSync} from 'node:fs';
import {Script,createContext} from 'node:vm';
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
  return {calls,read:createSupervisorObservation({enabled:true,fetchImpl,now:()=>1700000000000,ownerProbe:async()=>true})};
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
  const calls=[];const read=createSupervisorObservation({enabled:true,ownerProbe:async()=>true,timeoutMs:15,fetchImpl:(url,{signal,method})=>{
    calls.push({url,method});return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(Error('timeout')),{once:true}));
  }});
  // Keep the test's event loop live; production HTTP sockets already do that.
  const hold=setTimeout(()=>{},1000);
  try{assert.equal((await read()).state,'unavailable');assert.equal(calls.length,8);assert.ok(calls.every(c=>c.method==='GET'));}
  finally{clearTimeout(hold);}
});

function ownerFixture() {
  return {pid:1234,executable:'C:\\Python314\\pythonw.exe',
    commandLine:'C:\\Python314\\pythonw.exe "D:\\DeepSeekHarness-TestingGrounds\\Qwen3.8-Flash Testing\\local-models\\local_supervisor.py"',
    createdAt:'2026-11-14T12:00:00Z',sourceModifiedAt:'2026-11-14T11:00:00Z',moduleModifiedAt:'2026-11-14T11:00:00Z',
    sourceSha256:'f824f638777db226c1d4f00cc37fc7849ae0ab3c1def5a234b4a639598b73786',
    moduleSha256:'7b823cd6a07fad21c7471142e999e3122d26c880cfbcd9c0f4acfe8cc6874116',
    listeners:SUPERVISOR_MODEL_PORTS.map(port=>({port,address:'127.0.0.1',pid:1234}))};
}

test('unknown, failed or nonboolean ownership prevents every model-port request',async()=>{
  for(const ownerProbe of [async()=>false,async()=>undefined,async()=>({verified:true}),async()=>{throw Error('private owner failure');}]) {
    let calls=0;const read=createSupervisorObservation({enabled:true,ownerProbe,fetchImpl:()=>{calls++;throw Error('must not reach model');}});
    const result=await read();assert.equal(calls,0);assert.equal(result.state,'unavailable');assert.equal(result.source,'none');
    assert.ok(result.models.every(m=>m.loaded===null&&m.reason==='supervisor_identity_unverified'));assert.equal(result.controls,false);
    assert.equal(JSON.stringify(result).includes('private owner failure'),false);
  }
});

test('Windows owner proof requires one qualified process across all four ports',()=>{
  assert.equal(isQualifiedSupervisorOwner(ownerFixture()),true);
  for(const mutate of [p=>{p.executable='D:\\Other\\ustrata.exe';},p=>{p.commandLine+=' --other';},
    p=>{p.sourceSha256='0'.repeat(64);},p=>{p.moduleSha256='0'.repeat(64);},
    p=>{p.sourceModifiedAt='2026-11-14T13:00:00Z';},p=>{p.moduleModifiedAt='not-a-date';},
    p=>{p.listeners[0].pid=5678;},p=>{p.listeners.pop();},p=>{p.listeners[0].address='0.0.0.0';},
    p=>{p.listeners[0].port=8099;},p=>{p.executable=42;},p=>{p.commandLine=null;}]) {
    const owner=ownerFixture();mutate(owner);assert.equal(isQualifiedSupervisorOwner(owner),false);
  }
});

test('owner probe is bounded hidden metadata inspection and fails closed on errors',async()=>{
  let runs=0;const runImpl=async(file,args,options)=>{
    runs++;assert.match(file,/WindowsPowerShell\\v1\.0\\powershell\.exe$/);
    assert.equal(options.windowsHide,true);assert.equal(options.timeout,5000);assert.equal(options.env.PSModulePath,'');
    assert.equal(args.includes('-NonInteractive'),true);assert.match(args.at(-1),/Get-NetTCPConnection/);
    assert.equal(/Stop-Process|Start-Process|Invoke-WebRequest|Invoke-RestMethod/.test(args.at(-1)),false);
    return {stdout:JSON.stringify(ownerFixture())};
  };
  assert.equal(await probeSupervisorOwner({platform:'linux',runImpl}),false);assert.equal(runs,0);
  assert.equal(await probeSupervisorOwner({platform:'win32',runImpl}),true);assert.equal(runs,1);
  for(const result of [{stdout:'not JSON'},{stdout:'{}'},{stdout:JSON.stringify({...ownerFixture(),pid:0})}])
    assert.equal(await probeSupervisorOwner({platform:'win32',runImpl:async()=>result}),false);
  assert.equal(await probeSupervisorOwner({platform:'win32',runImpl:async()=>{throw Error('timeout');}}),false);
});

test('owner is rechecked after a successful observation and before any later network read',async()=>{
  let owners=0,calls=0;const source=fixture();
  const read=createSupervisorObservation({enabled:true,ownerProbe:async()=>++owners===1,fetchImpl:async()=>{calls++;return Response.json({});}});
  await read();assert.equal(calls,8);await read();assert.equal(calls,8);assert.equal(owners,2);
  // Existing successful-identity fixture still exercises its eight bounded reads.
  assert.equal((await source.read()).state,'fresh');
});

test('legacy inference fallback skips all managed ports and refuses redirected reads',async()=>{
  const source=readFileSync(new URL('../serve.mjs',import.meta.url),'utf8');
  const begin=source.indexOf('const STRATA_PORTS ='),end=source.indexOf(';',begin)+1;
  const fn=source.indexOf('async function strataHealth()'),next=source.indexOf('const readInferenceSummary',fn);
  assert.ok(begin>=0&&end>begin&&fn>=0&&next>fn);
  const calls=[];const context=createContext({SUPERVISOR_MODEL_PORTS,AbortSignal,fetch:async(url,options)=>{
    calls.push(url);assert.equal(options.redirect,'manual');assert.equal(options.credentials,'omit');
    return new Response('',{status:302,headers:{location:'http://127.0.0.1:18090/health'}});
  }});
  new Script(source.slice(begin,end)+'\n'+source.slice(fn,next)+'\nglobalThis.probe=strataHealth;').runInContext(context);
  assert.equal(await context.probe(),null);assert.ok(calls.length>0);
  assert.ok(calls.every(url=>!SUPERVISOR_MODEL_PORTS.includes(Number(new URL(url).port))));
});
