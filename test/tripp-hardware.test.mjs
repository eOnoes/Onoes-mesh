import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {encodeTrippProbe, normalizeTrippSample, withTrippHardware} from '../lib/tripp-hardware.mjs';

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
