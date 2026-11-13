import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, writeFile, rename, readFile, realpath } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createLegacyAuthorizationReader } from '../lib/workroom-legacy-authorization.mjs';

async function fixture(changes = {}) {
  const dir = await realpath(await mkdtemp(join(tmpdir(), 'mesh-approval-fixture-'))), path = join(dir, 'approval.json');
  const planHash = 'a'.repeat(64), host = 'SYNTHETIC', bootedAt = '2026-01-01T00:00:00Z';
  const record = { schema: 'mesh/legacy-recovery-authorization/v1', owner: 'Eddie', decision: 'apply_exact_eight',
    planHash, host, bootedAt, authorizedAt: new Date(Date.now() - 10000).toISOString(),
    expiresAt: new Date(Date.now() + 60000).toISOString(), ...changes };
  const bytes = JSON.stringify(record); await writeFile(path, bytes);
  return { path, planHash, bytes, options: { recordPath: path, expectedSha256: createHash('sha256').update(bytes).digest('hex'), planHash, host, bootedAt } };
}

test('a pinned exact boot and plan approval is reread without writing or creating authority', async () => {
  const f = await fixture(), reader = await createLegacyAuthorizationReader(f.options);
  assert.deepEqual(await reader(f.planHash), { schema: 'mesh/legacy-recovery-authorization/v1', decision: 'apply_exact_eight', planHash: f.planHash, host: f.options.host, bootedAt: f.options.bootedAt, recordHash: f.options.expectedSha256 });
  assert.equal(await readFile(f.path, 'utf8'), f.bytes);
  await assert.rejects(reader('b'.repeat(64)), /another plan/);
});

test('preparation, wrong owner, wrong boot or host, expired, future and excessive authority are refused', async () => {
  for (const change of [{ decision: 'prepare' }, { owner: 'Echo' }, { bootedAt: '2020-01-01T00:00:00Z' },
    { host: 'OTHER' }, { expiresAt: new Date(Date.now() - 1).toISOString() },
    { authorizedAt: new Date(Date.now() + 30000).toISOString() },
    { expiresAt: new Date(Date.now() + 172800000).toISOString() }]) {
    const f = await fixture(change);
    await assert.rejects(createLegacyAuthorizationReader(f.options), /owner approval/);
  }
});

test('changed or removed approval immediately revokes an existing reader', async () => {
  const f = await fixture(), reader = await createLegacyAuthorizationReader(f.options);
  await writeFile(f.path, f.bytes + ' ');
  await assert.rejects(reader(f.planHash), /reviewed record/);
  await rename(f.path, f.path + '.revoked');
  await assert.rejects(reader(f.planHash), /ENOENT/);
  await writeFile(f.path, f.bytes);
  await assert.rejects(reader(f.planHash), /replaced/);
});

test('a hash supplied inside a document cannot substitute for the separately pinned hash', async () => {
  const f = await fixture();
  await assert.rejects(createLegacyAuthorizationReader({ ...f.options, expectedSha256: 'f'.repeat(64) }), /reviewed record/);
  await assert.rejects(createLegacyAuthorizationReader({ ...f.options, recordPath: 'approval.json' }), /trusted authorization/);
});
