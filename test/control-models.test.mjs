import test from 'node:test';
import assert from 'node:assert/strict';
import {supervisorControlView,supervisorConnectionNotice} from '../public/control-models.mjs';
import {runInNewContext} from 'node:vm';
import {startApp} from '../server.mjs';
import {randomUUID} from 'node:crypto';
import {readFileSync} from 'node:fs';
const ids=['qwen3.8-flash-next-iq3-s','qwen3.6-35b-a3b-ud-q6_k_xl','qwen3.8-27b','nemotron-3.5-bolt-74b-a9b'];
const snapshot=()=>({schemaVersion:'mesh-supervisor-observation/v1',source:'local_supervisor',expiresAt:6000,models:ids.map(id=>({id,state:'ready',loaded:false}))});
test('actual HTTP serves the Control helper imported by the browser module',async()=>{
  const app=await startApp({dataDir:'data/control-static-'+randomUUID(),relayEnabled:false});
  try{const r=await fetch(app.url+'/control-models.mjs');assert.equal(r.status,200);assert.match(r.headers.get('content-type'),/javascript/);assert.equal(await r.text(),readFileSync('public/control-models.mjs','utf8'));}
  finally{await app.close();}
});
test('a ready earlier lane cannot mask the one reported loaded Nemotron; runtime/model source stays explicit',()=>{
  const s=snapshot();s.models[3]={id:ids[3],state:'reported_loaded',loaded:true};
  const view=supervisorControlView(s,1000);assert.equal(view.engine.name,'llama.cpp');assert.equal(view.engine.modelAlias,ids[3]);assert.equal(view.engine.loaded,true);
  assert.equal(view.engine.state,'reported loaded');assert.match(view.engine.note,/Ownership, GPU mapping/);assert.equal(view.service.models.length,1);assert.match(view.service.models[0].name,/Nemotron/);
  assert.equal(Object.hasOwn(view.engine,'controls'),false);
});
test('expired, malformed, missing, loading and conflicting observations clear old models without declaring an empty PC',()=>{
  for(const s of [null,{...snapshot(),expiresAt:1000},{...snapshot(),source:'other'}, {...snapshot(),models:[null]},
    {...snapshot(),models:[{id:ids[0],state:'loading_unconfirmed',loaded:null}]},
    {...snapshot(),models:[{id:ids[0],state:'reported_loaded',loaded:true},{id:ids[3],state:'reported_loaded',loaded:true}]},
    {...snapshot(),models:[...snapshot().models,snapshot().models[0]]}]){
    const view=supervisorControlView(s,1000);assert.equal(view.engine.loaded,null);assert.equal(view.engine.modelAlias,null);assert.equal(view.service.models.length,0);assert.notEqual(view.engine.state,'none reported loaded');
  }
});
test('only a complete consistent unloaded catalog reports none loaded; partial catalog stays unknown',()=>{
  assert.equal(supervisorControlView(snapshot(),1000).engine.state,'none reported loaded');
  assert.equal(supervisorControlView({...snapshot(),models:snapshot().models.slice(1)},1000).engine.loaded,null);
  const bad=snapshot();bad.models[0].loaded=true;assert.equal(supervisorControlView(bad,1000).engine.loaded,null);
});


test('unverified connection explains the hold and clears previous residency in Control and actual catalog renderer',()=>{
  const value={schemaVersion:'mesh-supervisor-observation/v1',source:'none',state:'unavailable',models:[{id:ids[3],state:'unknown',loaded:null,reason:'supervisor_identity_unverified'}]};
  const note=supervisorConnectionNotice(value);assert.match(note,/connection needs verification/);assert.match(note,/loaded is unknown/);
  const view=supervisorControlView(value,1000);assert.equal(view.engine.note,note);assert.equal(view.engine.loaded,null);assert.equal(view.engine.modelAlias,null);assert.deepEqual(view.service.models,[]);
  const source=readFileSync('public/app.js','utf8'),begin=source.indexOf('function renderSupervisorModels('),end=source.indexOf('\nfunction ',begin+1);
  assert.ok(begin>=0&&end>begin);
  const root={textContent:'previous resident',replaceChildren(){this.textContent='';}};
  const context={supervisorConnectionNotice,$:id=>{assert.equal(id,'local-model-catalog');return root;},value,localModelObservation:{loaded:true}};
  runInNewContext(source.slice(begin,end)+'\nrenderSupervisorModels(value);',context);
  assert.equal(root.textContent,note);assert.equal(context.localModelObservation,undefined);
  assert.equal(supervisorConnectionNotice(null),null);assert.equal(supervisorConnectionNotice(snapshot()),null);
});
