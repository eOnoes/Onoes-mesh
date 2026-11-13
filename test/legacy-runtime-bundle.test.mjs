import test from 'node:test';
import assert from 'node:assert/strict';
import { cp, copyFile, mkdtemp } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { execFileSync } from 'node:child_process';

test('the packaged data layer starts without operator/preparation scripts', async () => {
  const root = resolve('.'), dir = await mkdtemp(join(tmpdir(), 'mesh-runtime-bundle-'));
  await cp(join(root, 'lib'), join(dir, 'lib'), { recursive: true });
  await cp(join(root, 'public'), join(dir, 'public'), { recursive: true });
  await cp(join(root, 'config'), join(dir, 'config'), { recursive: true });
  await copyFile(join(root, 'package.json'), join(dir, 'package.json'));
  const code = `import {resolve} from 'node:path';import {pathToFileURL} from 'node:url';
    const {openTaskStore}=await import(pathToFileURL(resolve('lib/task-store.mjs')));
    const store=openTaskStore(resolve('fixture.sqlite'));
    const task=store.create({title:'Packaged fixture',description:'No live providers'});
    const result={count:store.list().length,recovery:store.workroom.legacyRecovery.read(task.id,'missing')};
    store.close();console.log(JSON.stringify(result));`;
  const env = { ...process.env }; delete env.NODE_TEST_CONTEXT;
  const output = execFileSync(process.execPath, ['--input-type=module', '-e', code],
    { cwd: dir, env, windowsHide: true, timeout: 10000, encoding: 'utf8' });
  assert.deepEqual(JSON.parse(output.trim()), { count: 1, recovery: null });
});
