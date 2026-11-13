import { createHash } from 'node:crypto';
import { isAbsolute, resolve } from 'node:path';
import { lstat, open, realpath } from 'node:fs/promises';

const digest = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const key = value => process.platform === 'win32' ? value.toLowerCase() : value;
const identity = value => `${value.dev}:${value.ino}:${value.birthtimeNs}`;

// Operator-only configuration: never construct this from a model or HTTP request.
// The reviewed hash is supplied separately from the file. No approval is created.
export async function createLegacyAuthorizationReader({ recordPath, expectedSha256, planHash, host, bootedAt }) {
  if (!isAbsolute(recordPath || '') || !digest(expectedSha256) || !digest(planHash) ||
      typeof host !== 'string' || !host || !Number.isFinite(Date.parse(bootedAt))) {
    throw Error('Exact trusted authorization binding is required.');
  }
  const path = resolve(recordPath);
  async function fileInfo() {
    if (key(await realpath(path)) !== key(path)) throw Error('Aliased approval paths are refused.');
    const info = await lstat(path, { bigint: true });
    if (!info.isFile() || info.isSymbolicLink() || info.size > 16384n || info.ino <= 0n) {
      throw Error('Invalid approval file.');
    }
    return info;
  }
  const originalIdentity = identity(await fileInfo());
  async function authorize(requestedPlanHash) {
    if (requestedPlanHash !== planHash) throw Error('Approval belongs to another plan.');
    const info = await fileInfo();
    if (identity(info) !== originalIdentity) throw Error('Approval file was replaced.');
    const handle = await open(path, 'r');
    let bytes;
    try {
      const opened = await handle.stat({ bigint: true });
      if (identity(opened) !== originalIdentity || opened.size > 16384n) throw Error('Approval changed during read.');
      const buffer = Buffer.alloc(16385);
      const { bytesRead } = await handle.read(buffer, 0, buffer.length, 0);
      if (bytesRead > 16384) throw Error('Approval file exceeds its size limit.');
      bytes = buffer.subarray(0, bytesRead);
    } finally { await handle.close(); }
    if (identity(await fileInfo()) !== originalIdentity ||
        createHash('sha256').update(bytes).digest('hex') !== expectedSha256) throw Error('Approval bytes do not match the reviewed record.');
    const record = JSON.parse(bytes.toString('utf8'));
    const issued = Date.parse(record.authorizedAt), expires = Date.parse(record.expiresAt), now = Date.now();
    if (record.schema !== 'mesh/legacy-recovery-authorization/v1' || record.owner !== 'Eddie' ||
        record.decision !== 'apply_exact_eight' || record.planHash !== planHash ||
        record.host !== host || record.bootedAt !== bootedAt ||
        !Number.isFinite(issued) || !Number.isFinite(expires) || issued > now || expires <= now ||
        expires <= issued || expires - issued > 86400000) {
      throw Error('Exact current owner approval is missing or expired.');
    }
    return Object.freeze({ schema: record.schema, decision: record.decision, planHash, host, bootedAt, recordHash: expectedSha256 });
  }
  await authorize(planHash);
  return authorize;
}
