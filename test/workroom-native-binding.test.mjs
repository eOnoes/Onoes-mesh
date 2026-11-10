import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {mkdtempSync,mkdirSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {randomUUID} from 'node:crypto';
import {createNativeWorkerBinding} from '../lib/workroom-native-binding.mjs';
import {openTaskStore} from '../lib/task-store.mjs';
import {startApp,ROOT} from '../server.mjs';

const profile = () => ({profileRef:'test-echo',identityRef:'test-principal',
  provider:'openai-codex',model:'synthetic-native-model',workspace:ROOT});
const plan = () => ({plan:{state:'locked',workerId:'echo',reviewerId:'nims',workspace:ROOT}});

test('native server binding is absent by default and rejects incomplete or widened configuration', () => {
  assert.equal(createNativeWorkerBinding(),null);
  for (const options of [null,{}, {profile:profile(),rpc(){},authorized:()=>true,credential:'forbidden'},
    {profile:{...profile(),provider:'custom',baseUrl:'http://127.0.0.1:1'},rpc(){},authorized:()=>true}])
    assert.throws(() => createNativeWorkerBinding(options));
});

test('binding pins the accepted profile, transport, workspace and Echo/Nims route', async () => {
  let calls=0;
  const options={profile:profile(),rpc:async()=>{calls++;return {ok:true};},authorized:()=>true};
  const binding=createNativeWorkerBinding(options),saved=binding.profileFor(plan());
  options.profile.model='changed';options.rpc=()=>{throw Error('Mutated transport used');};
  options.authorized=()=>false;saved.model='changed';
  assert.equal(binding.profileFor(plan()).model,'synthetic-native-model');
  assert.equal(binding.authorized({...profile(),model:'other'}),false);
  assert.equal(binding.authorized({}),false);
  for (const changes of [{state:'draft'},{workerId:'nims'},{reviewerId:'echo'},{workspace:'.'},
    {workspace:join(ROOT,'data','another-workspace')}])
    assert.throws(()=>binding.profileFor({plan:{...plan().plan,...changes}}),/locked team/);
  assert.deepEqual(await binding.rpc('prompt.lookup',{}),{ok:true});assert.equal(calls,1);
  assert.equal(binding.retireCompleted,true);await binding.close();
});

test('revocation blocks new and late RPC results; closing disconnects once without replay', async () => {
  let allowed=false,calls=0,finish,closed=0;
  const binding=createNativeWorkerBinding({profile:profile(),authorized:()=>allowed,
    rpc:()=>{calls++;return new Promise(resolve=>{finish=resolve;});},close:()=>{closed++;}});
  await assert.rejects(binding.rpc('session.create',{}),/not authorized/);assert.equal(calls,0);
  allowed=true;const pending=binding.rpc('prompt.lookup',{});allowed=false;finish({found:true});
  await assert.rejects(pending,/not authorized/);assert.equal(calls,1);
  const one=binding.close(),two=binding.close();assert.equal(one,two);await one;
  assert.equal(closed,1);allowed=true;assert.equal(binding.authorized(profile()),false);
  await assert.rejects(binding.rpc('prompt.submit',{}),/not authorized/);assert.equal(calls,1);
});

test('standalone and Relay-disabled startup reject enrollment before contacting its transport', async () => {
  const previous=process.env.MESH_STANDALONE;let calls=0;
  const options={profile:profile(),authorized:()=>true,rpc:()=>{calls++;}};
  try {
    process.env.MESH_STANDALONE='0';
    await assert.rejects(startApp({relayEnabled:false,nativeWorkerOptions:options}),/require Mesh/);
    await assert.rejects(startApp({relayEnabled:true,nativeWorkerOptions:{...options,
      profile:{...profile(),workspace:join(ROOT,'..')}}}),/outside trial root/i);
    process.env.MESH_STANDALONE='1';
    await assert.rejects(startApp({relayEnabled:true,nativeWorkerOptions:options}),/standalone/);
    assert.equal(calls,0);
  } finally {if(previous===undefined)delete process.env.MESH_STANDALONE;else process.env.MESH_STANDALONE=previous;}
});

test('failed transport cleanup leaves authorization closed and cannot reconnect or dispatch', async () => {
  let calls=0;
  const binding=createNativeWorkerBinding({profile:profile(),authorized:()=>true,
    rpc:()=>{calls++;},close:()=>{throw Error('Synthetic close failure');}});
  await assert.rejects(binding.close(),/Synthetic close failure/);
  await assert.rejects(binding.close(),/Synthetic close failure/);
  assert.equal(binding.authorized(profile()),false);
  await assert.rejects(binding.rpc('prompt.submit',{}),/not authorized/);assert.equal(calls,0);
});

test('actual admitted server team start uses the native binding and holds a mismatched profile without Relay fallback', async () => {
  const keys=['MESH_RELAY_MODE','MESH_RELAY_URL','MESH_RELAY_TOKEN_FILE','MESH_STANDALONE',
    'MESH_NIMS','MESH_NEMOTRON_CONTROL','MESH_MODEL_OBSERVATION','MESH_SIMPLE_FLOW',
    'MESH_DSH_APPROVAL_ORIGIN','MESH_DSH_TOKEN_FILE'];
  const previous=Object.fromEntries(keys.map(key=>[key,process.env[key]]));
  const token='synthetic-'+randomUUID(),tokenPath=join(mkdtempSync(join(tmpdir(),'mesh-binding-')),'key');
  writeFileSync(tokenPath,token);
  const agents=[{id:'echo',backend:'hermes',status:'idle',conversation_id:'fixture-echo'},
    {id:'nims',backend:'codex',status:'idle',conversation_id:'fixture-nims'}];
  let posts=0,disconnects=0,app;const requests=[];
  const peer=http.createServer((req,res)=>{
    res.setHeader('Content-Type','application/json');
    if(req.method!=='GET')posts++;
    if(req.headers.authorization!=='Bearer '+token){res.writeHead(401);res.end('{}');return;}
    if(req.url==='/api/agents'){res.end(JSON.stringify(agents));return;}
    if(req.url==='/api/mesh-capabilities'){res.end('{"taskSessionBinding":1}');return;}
    res.writeHead(503);res.end('{}');
  });
  const dataDir='data/native-binding-http-'+randomUUID();mkdirSync(join(ROOT,dataDir));
  const store=openTaskStore(join(ROOT,dataDir,'tasks.sqlite'));let task;
  try {
    task=store.create({title:'Synthetic binding test',description:'Do not dispatch real work',owner:'echo'});
    task=store.workroom.save(task.id,{project:'Fixture',criteria:'No real work',owner:'echo',team:'local_build',stage:'ready',revision:1});
    task=store.workroom.saveProgress(task.id,{goal:'Exercise native routing only',checklist:[{id:'one',text:'Fixture',status:'pending'}],
      result:'',evidence:'',reviewer:'',decision:'pending',revision:0,taskRevision:task.revision,briefRevision:task.workroom.revision});
    task=store.workroom.savePlan(task.id,{lead:'echo',spec:'Synthetic only',workspace:ROOT,allowedFiles:'data/never-written.md',
      checks:'No real work',boundaries:'No model calls',workerId:'echo',reviewerId:'nims',state:'locked',revision:0,
      taskRevision:task.revision,briefRevision:task.workroom.revision,progressRevision:task.progress.revision}).task;
  } finally {store.close();}
  try {
    await new Promise(resolve=>peer.listen(0,'127.0.0.1',resolve));
    process.env.MESH_RELAY_MODE='http';process.env.MESH_RELAY_URL='http://127.0.0.1:'+peer.address().port;
    process.env.MESH_RELAY_TOKEN_FILE=tokenPath;process.env.MESH_STANDALONE='0';process.env.MESH_NIMS='0';
    process.env.MESH_NEMOTRON_CONTROL='0';process.env.MESH_MODEL_OBSERVATION='0';process.env.MESH_SIMPLE_FLOW='0';
    process.env.MESH_DSH_APPROVAL_ORIGIN=process.env.MESH_RELAY_URL;process.env.MESH_DSH_TOKEN_FILE=tokenPath;
    app=await startApp({dataDir,relayEnabled:true,nativeWorkerOptions:{profile:profile(),authorized:()=>true,
      rpc:async(method,params)=>{requests.push({method,params});
        if(method==='session.create')return {session_id:'local-'+'a'.repeat(64)};
        if(method==='prompt.lookup')return {found:false,profile_contract:{closed:false}};
        throw Error('Unexpected native call');},close:()=>{disconnects++;}}});
    const headers={Origin:app.url,'Content-Type':'application/json'};
    const boot=await fetch(app.url+'/api/trial-session/bootstrap',{method:'POST',headers,body:'{}'});
    assert.equal(boot.status,201);const session=await boot.json();
    headers.Cookie=boot.headers.get('set-cookie').split(';')[0];headers['X-Trial-CSRF']=session.csrfToken;
    const response=await fetch(app.url+'/api/workroom/'+task.id+'/automation',{method:'POST',headers,
      body:JSON.stringify({action:'start',revision:0,planRevision:task.plan.revision,taskRevision:task.revision,
        briefRevision:task.workroom.revision,progressRevision:task.progress.revision})});
    assert.equal(response.status,200);
    const deadline=Date.now()+12000;let saved;
    do {
      const read=await fetch(app.url+'/api/workroom/'+task.id,{headers});assert.equal(read.status,200);
      saved=(await read.json()).task;
      if(saved.automation?.state==='paused')break;
      await new Promise(resolve=>setTimeout(resolve,25));
    } while(Date.now()<deadline);
    assert.equal(saved.automation.state,'paused');
    assert.equal(requests.filter(r=>r.method==='session.create').length,1);
    assert.ok(requests.some(r=>r.method==='prompt.lookup'));
    assert.ok(requests.slice(1).every(r=>r.method==='prompt.lookup'));
    assert.equal(requests[0].params.provider,'openai-codex');assert.equal(requests[0].params.max_turns,50);
    assert.deepEqual(requests[0].params.toolsets,['file']);assert.equal(requests[0].params.safe_mode,true);
    assert.equal(posts,0);assert.equal(saved.messages.length,1);assert.equal(saved.messages[0].nativeLocal.teamBound,1);
    await app.close();app=null;assert.equal(disconnects,1);
  } finally {
    await app?.close();peer.closeAllConnections();await new Promise(resolve=>peer.close(resolve));
    for(const key of keys){if(previous[key]===undefined)delete process.env[key];else process.env[key]=previous[key];}
  }
});
