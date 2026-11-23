import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {homedir} from 'node:os';
import {controlledProbe} from './m5-nodes-fixture.mjs';
import {encodeTrippProbe, normalizeTrippSample, readWindowsHardware, withRemoteHardware, withTrippHardware} from '../lib/tripp-hardware.mjs';
import {NODE_IDENTITIES,createNodeProbeReader,readTrippHardware} from '../lib/node-probes.mjs';

const box = {id:'ai-box',label:'AI box',dnsName:'fixture.tail8c4a75.ts.net',tailscaleIp:'100.64.0.23'};
const fixtureSample = [
  'onoes-tripp onoes','@ram','Mem: 1000 400 200 1 100 600',
  '@cpu','r b us sy id wa st','0 0 0 0 100 0 0','1 0 10 10 70 10 0',
  '@thermal',JSON.stringify({'k10temp-test':{Tdie:{temp2_input:41.5},Tctl:{temp1_input:61.5}},'nvme-test':{Tdie:{temp1_input:90}}}),
  '@gpu','0, NVIDIA GeForce RTX 3060, N/A, 73','1, NVIDIA GeForce RTX 4080 SUPER, 34, 0','@ollama','NAME ID SIZE PROCESSOR CONTEXT RUNNER UNTIL','@ollama-ok','@strata-ready','@end',
].join('\n');

test('Tripp reads the pinned LAN alias with no address overrides, forwarding or PTY', async () => {
  const sample = await readTrippHardware(async (exe,args,opts) => {
    assert.equal(exe,'C:/Windows/System32/OpenSSH/ssh.exe');
    assert.deepEqual(args.slice(0,2),['-F',join(homedir(),'.ssh','keys','echo-tripp-temp-management','ssh_config')]);
    assert.equal(args.at(-2),'tripp-inference-temp');
    for (const option of ['BatchMode=yes','UpdateHostKeys=no','ForwardAgent=no','ClearAllForwardings=yes','IdentitiesOnly=yes','StrictHostKeyChecking=yes','-T']) assert.ok(args.includes(option));
    assert.equal(opts.windowsHide,true);
    return {stdout:fixtureSample};
  });
  assert.deepEqual(sample,{ramPct:40,cpuPct:20,gpuPct:73,cpuTempC:41.5,gpuTempC:34,ollamaModels:[],strataHealth:'ready',
    gpus:[{index:0,name:'NVIDIA GeForce RTX 3060',tempC:null,usagePct:73},
      {index:1,name:'NVIDIA GeForce RTX 4080 SUPER',tempC:34,usagePct:0}]});
});

test('missing metrics, wrong account, interrupted replies, and an unavailable model runtime remain distinct', async () => {
  const read = stdout => readTrippHardware(async()=>({stdout}));
  for (const bad of [fixtureSample.replace('onoes-tripp','omarchy'),fixtureSample.replace(' onoes\n',' guest\n'),fixtureSample.replace('@end','')])
    await assert.rejects(read(bad),/Incomplete Tripp/);
  const empty = await read('onoes-tripp onoes\n@end');
  assert.ok(Object.values(empty).every(x=>x===null));
  const withoutStrata = await read(fixtureSample.replace('@strata-ready',''));
  assert.equal(withoutStrata.strataHealth,null);
  assert.deepEqual(withoutStrata.ollamaModels,[]);
  assert.equal((await read(fixtureSample.replace('@ollama-ok',''))).ollamaModels,null);
  assert.deepEqual((await read(fixtureSample.replace('@ollama-ok','demo:small 0123abcd 1GB GPU 4096 GPU forever\n@ollama-ok'))).ollamaModels,['demo:small']);
});

test('a denied SSH connection is distinct from a rejected login and expires with its observation', async () => {
  const fixture = controlledProbe();
  let stderr = 'ssh: connect to host 10.0.0.1 port 22: Permission denied';
  const reader = createNodeProbeReader({...fixture.options, observeDesktop:true,
    sampleDesktop:() => readTrippHardware(async () => { throw Object.assign(Error('SSH failed'), {stderr}); })});
  const denied = (await reader.refresh()).trippDesktop;
  assert.deepEqual(denied, {state:'unknown', source:'lan_ssh', reason:'connection_denied', ageMs:0});
  fixture.advance(30000);
  assert.deepEqual(reader.snapshot().trippDesktop, {state:'unknown'});
  for (stderr of ['onoes@sample: Permission denied (publickey).', 'Host key verification failed.']) {
    const unknown = (await reader.refresh()).trippDesktop;
    assert.deepEqual(unknown, {state:'unknown', source:'lan_ssh', ageMs:0});
  }
});

test('LAN telemetry survives a failed Tailscale discovery and clears after an SSH error',async()=>{
  const fixture=controlledProbe();fixture.fail();
  let calls=0;
  const reader=createNodeProbeReader({...fixture.options,observeDesktop:true,sampleDesktop:async()=>{
    if (++calls>1) throw Error('Unavailable');
    return {gpuPct:0};
  }});
  const [a,b]=await Promise.all([reader.refresh(),reader.refresh()]);
  assert.equal(calls,1);assert.deepEqual(a.trippDesktop,b.trippDesktop);
  assert.equal(a.trippDesktop.source,'lan_ssh');assert.equal(a.trippDesktop.gpuPct,0);
  assert.ok(a.nodes.every(n=>n.observationAvailability==='unavailable'));
  fixture.advance(30001);assert.equal(reader.snapshot().trippDesktop.state,'unknown');
  const next=await reader.refresh();assert.equal(next.trippDesktop.state,'unknown');
  assert.equal(next.trippDesktop.gpuPct,undefined);
});

test('the Windows collector uses the selected machine and verifies its returned name', async () => {
  for (const [node, name, alias] of [[NODE_IDENTITIES[1],'emitchell109-rog','laptop-echo'],[box,'print-host','ai-box-echo']]) {
    const run = async (exe, args, opts) => {
      assert.equal(exe,'C:/Windows/System32/OpenSSH/ssh.exe');
      assert.ok(args.includes('Hostname=' + node.tailscaleIp));
      assert.equal(args[args.indexOf('powershell.exe') - 1], alias);
      assert.ok(args.includes('StrictHostKeyChecking=yes'));
      assert.equal(opts.windowsHide,true);
      return {stdout:JSON.stringify({hostName:name.toUpperCase(),ramPct:34,cpuPct:0,gpuTempC:54})};
    };
    const sample = await readWindowsHardware(node,name,run);
    assert.deepEqual(sample,{ramPct:34,cpuPct:0,gpuPct:null,gpuTempC:54,cpuTempC:null});
    await assert.rejects(readWindowsHardware(node,'unexpected',run),/Unexpected telemetry host/);
  }
  await assert.rejects(readWindowsHardware({...box,tailscaleIp:'127.0.0.1'},'print-host',assert.fail),/Unrecognized telemetry target/);
});

test('remote sensors run independently and do not reuse a failed or stale peer sample', async () => {
  let time = 1, boxOffline = false, boxFailure = false, releaseLaptop;
  const view = () => ({nodes:[...NODE_IDENTITIES,box].map(n=>({...n,status:'ready',
    tailscaleOnline:!(boxOffline && n.id==='ai-box'),observationAvailability:'available'}))});
  const nodes = {snapshot:view,refresh:async()=>view()};
  const calls = [];
  const reader = withRemoteHardware(nodes,{laptop:true,aiBoxHost:'PRINT-HOST',clock:()=>time,
    async sample(node,host) {
      calls.push([node.id,host]);
      if(node.id==='laptop') {
        await new Promise(resolve=>{releaseLaptop=resolve;});
        return {cpuPct:11};
      }
      if(boxFailure) throw Error('Sensor unavailable');
      return {cpuPct:82};
    }});
  async function finishRefresh() {
    const pending=reader.refresh();
    await new Promise(resolve=>setImmediate(resolve));
    releaseLaptop();
    return pending;
  }
  const first=reader.refresh();
  await new Promise(resolve=>setImmediate(resolve));
  assert.deepEqual(calls,[['laptop','emitchell109-rog'],['ai-box','print-host']]);
  assert.equal(reader.snapshot().nodes[2].hardware.cpuPct,82);
  time+=1000; releaseLaptop(); await first;
  time+=29000;
  assert.equal(reader.snapshot().nodes[2].hardware,null);
  assert.equal(reader.snapshot().nodes[1].hardware.cpuPct,11);
  boxFailure=true;
  const failed=await finishRefresh();
  assert.equal(failed.nodes[2].hardware,null);
  assert.equal(failed.nodes[1].hardware.cpuPct,11);
  boxFailure=false; boxOffline=true; calls.length=0;
  await finishRefresh();
  assert.deepEqual(calls,[['laptop','emitchell109-rog']]);
  boxOffline=false;
  assert.equal((await finishRefresh()).nodes[2].hardware.cpuPct,82);
  assert.ok(!Object.hasOwn(reader.snapshot().nodes[0],'hardware'));
  for (const aiBoxHost of [undefined,'','invalid host','bad/name']) {
    assert.equal(withRemoteHardware(nodes,{aiBoxHost}),nodes);
  }
  calls.length=0;
  const onlyBox=withRemoteHardware(nodes,{aiBoxHost:'PRINT-HOST',sample:async n=>{calls.push(n.id);return {ramPct:40};}});
  const exclusive=await onlyBox.refresh();
  assert.deepEqual(calls,['ai-box']);
  assert.ok(!Object.hasOwn(exclusive.nodes[1],'hardware'));
});

test('only the reviewed sensor query is encoded for the laptop', async () => {
  const script = (await readFile(new URL('../integrations/tripp-hardware.ps1', import.meta.url), 'utf8')).replaceAll('\r\n', '\n');
  const encoded = encodeTrippProbe(script);
  assert.equal(Buffer.from(encoded, 'base64').toString('utf16le'), script);
  assert.equal(encodeTrippProbe(script.replaceAll('\n', '\r\n')), encoded);
  assert.throws(() => encodeTrippProbe(script.replace('cpuPct', 'otherMetric')), /reviewed version/);
});

test('only the expected laptop supplies bounded readings; missing sensors remain unknown', () => {
  const json = obj => JSON.stringify({hostName:'EMITCHELL109-ROG', ...obj});
  assert.deepEqual(normalizeTrippSample(json({cpuPct:0,ramPct:101,gpuPct:'5',gpuTempC:55})),
    {cpuPct:0,ramPct:null,gpuPct:null,gpuTempC:55,cpuTempC:null});
  assert.throws(() => normalizeTrippSample(json({hostName:'other'})));
});

test('refresh shares the SSH read, clears stale values, and skips offline or ambiguous peers', async () => {
  let online = true, available = true, time = 10000, calls = 0, fail = false;
  const view = () => ({nodes:[{id:'pc'}, {id:'laptop',status:'ready',tailscaleOnline:online,
    observationAvailability:available ? 'available' : 'unavailable'}]});
  const reader = withTrippHardware({snapshot:view,refresh:async()=>view()}, {
    clock:()=>time, sample:async()=>{calls++; if(fail)throw Error(); return {cpuPct:25};}
  });
  assert.equal(reader.snapshot().nodes[1].hardware,null);
  await Promise.all([reader.refresh(),reader.refresh()]);
  assert.equal(calls,1);
  assert.equal(reader.snapshot().nodes[1].hardware.cpuPct,25);
  time += 30000;
  assert.equal(reader.snapshot().nodes[1].hardware,null);
  fail=true; await reader.refresh();
  assert.equal(reader.snapshot().nodes[1].hardware,null);
  online=false; await reader.refresh(); available=false; online=true; await reader.refresh();
  assert.equal(calls,2);
  assert.deepEqual(reader.snapshot().nodes[0],{id:'pc'});
});

test('a pending refresh preserves a fresh sample with its original expiry', async () => {
  let time = 1000, sample = async () => ({cpuPct:25});
  let online = true, failDiscovery = false;
  const view = () => ({nodes:[{id:'laptop', status:'ready', tailscaleOnline:online, observationAvailability:'available'}]});
  const reader = withTrippHardware({
    snapshot:view,
    async refresh() { if (failDiscovery) throw Error('discovery failed'); return view(); }
  }, {clock:() => time, sample:() => sample()});
  const first = (await reader.refresh()).nodes[0];
  let finish;
  sample = () => new Promise(resolve => { finish = resolve; });
  time += 100;
  const pending = reader.refresh();
  await Promise.resolve();
  assert.deepEqual(reader.snapshot().nodes[0], first);
  time += 29900;
  assert.equal(reader.snapshot().nodes[0].hardware, null);
  finish({cpuPct:40});
  assert.equal((await pending).nodes[0].hardware.cpuPct, 40);
  online = false;
  await reader.refresh();
  online = true;
  assert.equal(reader.snapshot().nodes[0].hardware, null);
  sample = async () => ({cpuPct:50});
  await reader.refresh();
  failDiscovery = true;
  await assert.rejects(reader.refresh(), /discovery failed/);
  assert.equal(reader.snapshot().nodes[0].hardware, null);
});
