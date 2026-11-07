import { createHash } from 'node:crypto';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

// Identify the code loaded by this process, including uncommitted local work.
// No Git command, credential file, database or external service is consulted.
export function releaseInfo(root, dataDir) {
  const files = ['package.json', 'server.mjs', 'serve.mjs'];
  function walk(directory) {
    for (const entry of readdirSync(join(root, directory), { withFileTypes: true })) {
      if (entry.isSymbolicLink()) throw new Error('Linked release source is unsupported.');
      if (entry.name === '__pycache__' || /\.py[co]$/i.test(entry.name)) continue;
      const name = directory + '/' + entry.name;
      if (entry.isDirectory()) walk(name);
      else if (entry.isFile()) files.push(name);
    }
  }
  for (const directory of ['lib', 'public', 'shared', 'config']) walk(directory);
  const digest = createHash('sha256');
  for (const file of files.sort()) {
    const bytes = readFileSync(join(root, file));
    digest.update(file + '\0' + bytes.length + '\0');
    digest.update(bytes);
  }
  const sourceSha256 = digest.digest('hex');
  return Object.freeze({
    schemaVersion: 'mesh-release/v1',
    version: JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')).version,
    build: sourceSha256.slice(0, 12), sourceSha256,
    startedAt: new Date().toISOString(),
    database: dataDir.replaceAll('\\', '/') + '/tasks.sqlite',
    qualification: 'candidate',
    note: 'Private release candidate. Physical-phone acceptance and inference qualification remain open.'
  });
}
