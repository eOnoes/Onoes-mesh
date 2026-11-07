import test from 'node:test';import assert from 'node:assert/strict';
import {parseGpuMetrics} from '../lib/gpu-metrics.mjs';
test('real zero GPU counters remain zero while blank and unavailable counters remain unknown',()=>{
 const row=parseGpuMetrics('Test GPU, 0, 32000, 0, 0, 300, 0, 0, 0, 0');
 assert.equal(row.utilPct,0);assert.equal(row.vramPct,0);assert.equal(row.scope,'device');assert.equal(row.attribution,'unverified');
 const unavailable=parseGpuMetrics('Test GPU, , 32000, [N/A], N/A, , [Not Supported], , , ');
 for(const key of ['vramUsedMiB','vramPct','utilPct','powerW','powerLimitW','tempC','fanPct','clockMHz','memClockMHz'])assert.equal(unavailable[key],null,key);
 assert.equal(unavailable.vramTotalMiB,32000);
});
test('invalid, contradictory and multi-device samples cannot fabricate GPU readiness or percentages',()=>{
 for(const value of [null,'','x'.repeat(4097),'Test GPU,1,2','GPU1,1,2,3,4,5,6,7,8,9\nGPU2,1,2,3,4,5,6,7,8,9'])assert.equal(parseGpuMetrics(value),null);
 const row=parseGpuMetrics('Test GPU, 33000, 32000, 101, Infinity, -1, bad, 200, , NaN');
 for(const key of ['vramUsedMiB','vramPct','utilPct','powerW','powerLimitW','tempC','fanPct','clockMHz','memClockMHz'])assert.equal(row[key],null,key);
 assert.equal(parseGpuMetrics('Test GPU,0,0,0,0,0,0,0,0,0').vramPct,null);
});
