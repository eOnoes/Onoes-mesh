import test from 'node:test';
import assert from 'node:assert/strict';
import {createSummaryReader} from '../lib/summary-cache.mjs';

test('overlapping refreshes share one collection and its completed snapshot', async () => {
  let release, calls = 0;
  const gate = new Promise(resolve => { release = resolve; });
  const sample = {generatedAt: 'one collection'};
  const read = createSummaryReader(async () => { calls++; await gate; return sample; });
  const first = read(), second = read(), third = read();
  assert.equal(first, second);
  assert.equal(second, third);
  await Promise.resolve();
  assert.equal(calls, 1);
  release();
  assert.deepEqual(await Promise.all([first, second, third]), [sample, sample, sample]);
  assert.equal(await read(), sample);
  assert.equal(calls, 1);
});

test('cache lifetime starts at completion and expires at the exact boundary', async () => {
  let tick = 0, calls = 0;
  const read = createSummaryReader(() => { calls++; tick += 1000; return {calls}; }, {now: () => tick});
  const first = await read();
  tick = 2999;
  assert.equal(await read(), first);
  tick = 3000;
  assert.deepEqual(await read(), {calls: 2});
});

test('a failed shared collection clears so the next refresh can recover', async () => {
  let calls = 0;
  const read = createSummaryReader(() => { if (++calls === 1) throw Error('unavailable'); return {ok: true}; });
  const first = read(), second = read();
  assert.equal(first, second);
  await assert.rejects(first, /unavailable/);
  await assert.rejects(second, /unavailable/);
  assert.deepEqual(await read(), {ok: true});
  assert.equal(calls, 2);
});

test('an expired sample is not served as fresh when the next collection fails', async () => {
  let tick = 0, calls = 0;
  const read = createSummaryReader(() => { if (++calls === 2) throw Error('offline'); return {calls}; }, {now: () => tick});
  await read();
  tick = 2000;
  await assert.rejects(read(), /offline/);
  assert.deepEqual(await read(), {calls: 3});
});

test('a clock moving backwards cannot keep an old sample fresh', async () => {
  let tick = 100, calls = 0;
  const read = createSummaryReader(() => ({calls: ++calls}), {now: () => tick});
  await read();
  tick = 99;
  assert.deepEqual(await read(), {calls: 2});
});
