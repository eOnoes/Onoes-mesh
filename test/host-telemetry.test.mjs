import test from 'node:test';
import assert from 'node:assert/strict';

test('shared host readings age, clear on failure and never invoke model controls', async () => {
  const originals = Object.fromEntries(['document','fetch','setInterval'].map(key => [key, globalThis[key]]));
  const makeNode = () => ({ children: [], textContent: '',dataset:{},style:{},append(...nodes) { this.children.push(...nodes); }, replaceChildren(...nodes) { this.children = nodes; } });
  const host = makeNode(),control=makeNode(), timers = [], requests = [];
  let fail = false;
  const sample = { generatedAt: new Date().toISOString(), host: 'Test PC', gpu: {name:'Test GPU',vramUsedMiB:100,vramTotalMiB:32000,utilPct:5} };
  const text = node => [node.textContent, ...node.children.map(text)].join(' ');
  try {
    globalThis.document = { getElementById: id => id === 'inference-host-telemetry' ? host : id==='ctl-root'?control:null, querySelectorAll: () => [], createElement: makeNode };
    globalThis.fetch = async url => { requests.push(url); if (fail) throw Error('offline'); return {ok:true,json:async()=>sample}; };
    globalThis.setInterval = (fn, interval) => { timers.push({fn,interval}); return timers.length; };
    const {hostTelemetryState} = await import('../public/control.mjs');
    await new Promise(resolve => setImmediate(resolve));
    const now = Date.now();
    assert.equal(hostTelemetryState({generatedAt:new Date(now).toISOString()}, now), 'fresh');
    assert.equal(hostTelemetryState({generatedAt:new Date(now-15001).toISOString()}, now), 'stale');
    assert.equal(hostTelemetryState({generatedAt:new Date(now+5001).toISOString()}, now), 'unknown');
    assert.equal(hostTelemetryState({generatedAt:'invalid'}, now), 'unknown');
    assert.equal(hostTelemetryState(null, now), 'unavailable');
    assert.match(text(host), /Test GPU/);
    assert.match(text(host), /100 \/ 32000 MiB/);
    const unchanged = host.children[0];
    timers.find(timer => timer.interval === 1000).fn();
    assert.equal(host.children[0], unchanged, 'unchanged readings must not repeatedly rebuild the live region');
    sample.generatedAt = new Date(now-20000).toISOString();
    timers.find(timer => timer.interval === 1000).fn();
    assert.match(text(host), /stale/);
    assert.match(text(control),/PC readings stale/);
    assert.doesNotMatch(text(control),/Test GPU/,'Control must clear expired GPU readings even without another response');
    assert.doesNotMatch(text(host), /Test GPU/);
    sample.generatedAt = new Date().toISOString(); sample.gpu.vramUsedMiB = -1;
    await timers.find(timer => timer.interval === 4000).fn();
    assert.doesNotMatch(text(host), /-1 \/ 32000/);
    assert.match(text(control),/Test GPU/,'fresh read restores Control');
    sample.generatedAt='invalid';await timers.find(timer=>timer.interval===4000).fn();
    assert.match(text(control),/PC readings unknown/);assert.doesNotMatch(text(control),/Test GPU|Invalid Date/);
    sample.generatedAt=new Date().toISOString();
    sample.modelObservation={schemaVersion:'mesh-supervisor-observation/v1',source:'local_supervisor',expiresAt:Date.now()+5000,models:[{id:'nemotron-3.5-bolt-74b-a9b',state:'reported_loaded',loaded:true}]};
    sample.engine={name:'strata',modelShort:'wrong earlier lane',loaded:false};sample.services=[];
    await timers.find(timer=>timer.interval===4000).fn();assert.match(text(control),/Nemotron/);assert.match(text(control),/reported loaded/);assert.doesNotMatch(text(control),/wrong earlier lane/);
    sample.modelObservation.expiresAt=Date.now()-1;timers.find(timer=>timer.interval===1000).fn();assert.doesNotMatch(text(control),/Nemotron/);assert.match(text(control),/unknown/);
    fail = true;
    await timers.find(timer => timer.interval === 4000).fn();
    assert.match(text(host), /unavailable/);
    assert.doesNotMatch(text(control),/Test GPU|Nemotron/);
    assert.doesNotMatch(text(host), /Test GPU/);
    assert.ok(requests.length >= 2);
    assert.ok(requests.every(url => url === '/inference/summary'));
  } finally {
    Object.assign(globalThis, originals);
  }
});
