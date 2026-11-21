import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizeTrippSample, withTrippHardware} from '../lib/tripp-hardware.mjs';

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
