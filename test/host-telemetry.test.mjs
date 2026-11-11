import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
import {sampleCpuTimes,cpuLoadPercent} from '../lib/host-cpu.mjs';

test('host CPU uses weighted cumulative time across every logical processor',()=>{
  const cpu=(user,idle)=>({times:{user,nice:0,sys:0,idle,irq:0}});
  const before=sampleCpuTimes(()=>[cpu(100,900),cpu(100,900)]);
  const after=sampleCpuTimes(()=>[cpu(120,980),cpu(180,1020)]);
  assert.equal(cpuLoadPercent(before,after),33.3);
  assert.equal(cpuLoadPercent(before,sampleCpuTimes(()=>[cpu(100,1000),cpu(100,1000)])),0);
  assert.equal(cpuLoadPercent(before,sampleCpuTimes(()=>[cpu(200,900),cpu(200,900)])),100);
});

test('missing or malformed host CPU readings remain unknown rather than zero',()=>{
  for(const read of [()=>[],()=>null,()=>{throw Error('unavailable');},()=>[{times:{idle:10}}],()=>[{times:{user:NaN,nice:0,sys:0,idle:10,irq:0}}]])assert.equal(sampleCpuTimes(read),null);
  assert.equal(cpuLoadPercent(null,{count:1,idle:1,total:2}),null);
});

test('CPU counter reset, changed topology and zero sampling time cannot report utilization',()=>{
  const before={count:2,idle:200,total:400};
  for(const after of [{...before},{count:1,idle:210,total:500},{count:2,idle:100,total:500},{count:2,idle:400,total:500},{count:2,idle:300,total:200},{count:2,idle:Infinity,total:500}])assert.equal(cpuLoadPercent(before,after),null);
});

test('shared host readings age, clear on failure and never invoke model controls', async () => {
  const originals = Object.fromEntries(['document','fetch','setInterval','setTimeout','clearTimeout'].map(key => [key, globalThis[key]]));
  const makeNode = () => ({ children: [], textContent: '',dataset:{},style:{},append(...nodes) { this.children.push(...nodes); }, replaceChildren(...nodes) { this.children = nodes; } });
  const host = makeNode(),control=makeNode(), timers = [], requests = [];
  let fail = false,hold=false,honorAbort=false;const held=[],events={},timeouts=[];
  const sample = { generatedAt: new Date().toISOString(), host: 'Test PC', system:{cpuLoadPct:12},ram:{usedGB:16,totalGB:64,usedPct:25},gpu: {name:'Test GPU',vramUsedMiB:100,vramTotalMiB:32000,utilPct:5} };
  const text = node => [node.textContent, ...node.children.map(text)].join(' ');
  try {
    globalThis.document = {hidden:false,addEventListener:(name,fn)=>{events[name]=fn;}, getElementById: id => id === 'inference-host-telemetry' ? host : id==='ctl-root'?control:null, querySelectorAll: () => [], createElement: makeNode };
    globalThis.fetch = async (url,options) => { requests.push(url);if(hold)return new Promise((resolve,reject)=>{held.push({resolve,signal:options?.signal});if(honorAbort)options.signal.addEventListener('abort',()=>reject(Error('aborted')),{once:true});});if (fail) throw Error('offline'); return {ok:true,json:async()=>sample}; };
    globalThis.setTimeout=(fn,ms)=>{const t={fn,ms};timeouts.push(t);return t;};globalThis.clearTimeout=t=>{if(t)t.cleared=true;};
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
    assert.match(text(host), /CPU use 12%/);assert.match(text(host), /RAM 16 \/ 64 GB/);assert.match(text(host), /RAM use 25%/);
    const unchanged = host.children[0];
    timers.find(timer => timer.interval === 1000).fn();
    assert.equal(host.children[0], unchanged, 'unchanged readings must not repeatedly rebuild the live region');
    sample.system.cpuLoadPct=0;sample.ram.usedGB=0;sample.ram.usedPct=0;
    timers.find(timer=>timer.interval===1000).fn();
    assert.match(text(host),/CPU use 0%/);assert.match(text(host),/RAM 0 \/ 64 GB/);assert.match(text(host),/RAM use 0%/);
    for(const invalid of [-1,101,'50',null]){
      sample.system.cpuLoadPct=invalid;sample.ram.usedPct=invalid;sample.ram.usedGB=65;
      timers.find(timer=>timer.interval===1000).fn();
      assert.doesNotMatch(text(host),/CPU use (?:-1|101|50|null)%|RAM use (?:-1|101|50|null)%|65 \/ 64 GB/);
    }
    sample.generatedAt = new Date(now-20000).toISOString();
    timers.find(timer => timer.interval === 1000).fn();
    assert.match(text(host), /stale/);
    assert.match(text(control),/PC readings stale/);
    assert.doesNotMatch(text(control),/Test GPU/,'Control must clear expired GPU readings even without another response');
    assert.doesNotMatch(text(host), /Test GPU/);
    assert.doesNotMatch(text(host),/CPU use|RAM use|64 GB/);
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
    fail=false;hold=true;const poll=timers.find(t=>t.interval===4000).fn;
    const first=poll();await new Promise(resolve=>setImmediate(resolve));const second=poll();await new Promise(resolve=>setImmediate(resolve));
    assert.equal(held.length,1,'a stalled request must not accumulate overlapping telemetry polls');await second;
    document.hidden=true;events.visibilitychange();assert.equal(held[0].signal.aborted,true);assert.doesNotMatch(text(control),/Test GPU/);
    const count=requests.length;await poll();assert.equal(requests.length,count,'hidden pages must not collect');
    document.hidden=false;hold=false;sample.generatedAt=new Date().toISOString();sample.gpu.name='Fresh GPU';events.visibilitychange();await new Promise(resolve=>setImmediate(resolve));assert.match(text(control),/Fresh GPU/);
    held[0].resolve({ok:true,json:async()=>({...sample,gpu:{...sample.gpu,name:'OLD HELD GPU'}})});await first;assert.match(text(control),/Fresh GPU/);assert.doesNotMatch(text(control),/OLD HELD GPU/);
    hold=true;honorAbort=true;const stalled=poll();await new Promise(resolve=>setImmediate(resolve));const timeout=timeouts.filter(t=>t.ms===8000&&!t.cleared).at(-1);assert.ok(timeout);timeout.fn();await stalled;assert.match(text(host),/unavailable/);assert.doesNotMatch(text(control),/Fresh GPU/);

  } finally {
    Object.assign(globalThis, originals);
  }
});


test('summary CPU warning follows the displayed sample even when Windows disagrees', async () => {
  const source=await readFile(new URL('../serve.mjs',import.meta.url),'utf8').then(text=>text.replaceAll('\r\n','\n'));
  const start=source.indexOf('async function inferenceSummary() {');
  const end=source.indexOf('\n}\n',start)+2;
  assert.ok(start>=0&&end>start,'summary function must be present');
  for(const [displayed,windows,expected] of [[9.9,99,false],[85,0,true],[100,0,true],[84.9,99,false],[null,99,false]]){
    const requests=[];
    const context=vm.createContext({
      process:{version:'test',platform:'test',arch:'test',env:{}},
      sampleCpuTimes:()=>null,cpuLoadPercent:()=>displayed,
      run:async(command)=>{requests.push(command);return {stdout:command==='powershell'?JSON.stringify({cpuLoad:windows}):''};},
      parseGpuMetrics:()=>null,supervisorObservationEnabled:false,
      strataHealth:async()=>null,ollamaStatus:async()=>({reachable:false}),
      lmStudioStatus:async()=>({reachable:false}),comfyStatus:async()=>({reachable:false}),
      readSupervisorModels:async()=>null,
    });
    const summary=await vm.runInContext(source.slice(start,end)+'; inferenceSummary()',context);
    assert.equal(summary.system.cpuLoadPct,displayed);
    assert.equal(summary.hints.some(hint=>hint.startsWith('CPU is above 85%')),expected,`displayed=${displayed}, Windows=${windows}`);
    assert.deepEqual(requests,['powershell','nvidia-smi'],'only read-only collectors are used');
  }
});
