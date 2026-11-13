import { createHash } from 'node:crypto';
import { statSync, realpathSync } from 'node:fs';
import { isAbsolute, resolve } from 'node:path';

export function databaseFileIdentity(path) {
  if (typeof path !== 'string' || !isAbsolute(path)) throw Error('An absolute database file is required.');
  const file = statSync(path, { bigint: true });
  if (!file.isFile() || file.ino <= 0n || file.birthtimeNs <= 0n) throw Error('Database file identity is unavailable.');
  // Preserve the existing recovery fingerprint's canonical field order.
  return createHash('sha256').update(JSON.stringify({ created: String(file.birthtimeNs), device: String(file.dev), file: String(file.ino) })).digest('hex');
}

export function databasePathKey(path) {
  if (typeof path !== 'string' || !isAbsolute(path)) throw Error('An absolute database file is required.');
  const canonical = resolve(realpathSync.native(path));
  return process.platform === 'win32' ? canonical.toLowerCase() : canonical;
}
