import {withRelaySource} from '../lib/connection-observations.mjs';
import test from 'node:test';import assert from 'node:assert/strict';import vm from 'node:vm';
import {createConnectionReader,emptyInference} from '../lib/service-connections.mjs';import {mockUI,flush} from './app-ui-fixture.mjs';
test('connection observations identify the actual HTTP Relay instead of claiming an isolated child',async()=>{
 const reader=withRelaySource(createConnectionReader({inferenceReader:async()=>emptyInference(),relayReader:async()=>({status:'fresh'})}),'live_relay_http');
 const snapshot=await reader();assert.equal(snapshot.services.find(s=>s.id==='relay').source,'live_relay_http');
 const failed=await withRelaySource(createConnectionReader({inferenceReader:async()=>emptyInference(),relayReader:async()=>{throw Error('private upstream detail');}}),'live_relay_http')();
 assert.equal(failed.services[0].source,'live_relay_http');assert.equal(failed.services[0].status,'unavailable');assert.doesNotMatch(JSON.stringify(failed),/private upstream detail/);
 assert.throws(()=>withRelaySource(reader,'invented'));
 const unchanged=await withRelaySource(async()=>({services:[{id:'relay',source:'none'},{id:'mind',source:'isolated_relay'}]}),'live_relay_http')();assert.equal(unchanged.services[0].source,'none');assert.equal(unchanged.services[1].source,'isolated_relay');
});
test('Overview distinguishes legacy adapters from working task/roster and read-only observation views',async()=>{
 const ui=mockUI();await flush();ui.context.overviewFixture={schemaVersion:'mesh-service-connections/v1',services:['relay','inference','agent','mind'].map(id=>({id,label:id,status:'not_configured',source:'none',observedAt:'2026-11-07T00:00:00.000Z',elapsedMs:0,errors:[]}))};
 vm.runInContext('renderConnections(overviewFixture)',ui.context);
 const box=ui.context.document.querySelectorAll('.service-connections')[0];const shown=box.children.map(n=>n.textContent).join('\n');
 for(const phrase of ['Legacy inference adapter','does not mean no model is running','Standalone Agent adapter','Relay peers and saved Workroom handoffs','Legacy Mind adapter','Saved task context comes from Workroom','own connection check'])assert.ok(shown.includes(phrase),phrase);
 vm.runInContext('renderConnections(undefined)',ui.context);assert.equal(box.children.length,1);assert.match(box.children[0].textContent,/unavailable/);
});
