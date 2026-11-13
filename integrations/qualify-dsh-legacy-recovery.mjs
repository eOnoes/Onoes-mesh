// Exercise installed DSH recovery code only against disposable tasks and a fake host.
// Never import this from Mesh's server or use its results as worker-retirement proof.
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, readFile, writeFile, copyFile, mkdir } from 'node:fs/promises';
import { homedir } from 'node:os';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';

const hash = bytes => createHash('sha256').update(bytes).digest('hex');
const installed = resolve(homedir(), '.dsh/profiles/a2a/node_modules/dsh-a2a-server/lib');
const expectedBundle = '06b7585153e100d12a1efc875f79e29e1e06998c29be29293635a2433e4cf410';
const source = await readFile(join(installed, 'index.js'));
assert.equal(hash(source), expectedBundle, 'Installed source changed; review before running this qualification.');
const approval = await readFile(join(installed, 'mesh-approval.mjs'));
const data = resolve('data');
await mkdir(data, { recursive: true });
const fixture = await mkdtemp(join(data, 'dsh-legacy-recovery-'));
const fixtureLib = join(fixture, 'lib');
await mkdir(fixtureLib);
await copyFile(join(installed, '../package.json'), join(fixture, 'package.json'));
await writeFile(join(fixtureLib, 'index.mjs'), Buffer.concat([
  source, Buffer.from('\nexport { FileTaskStore, DefaultRequestHandler };\n'),
]));
await copyFile(join(installed, 'mesh-approval.mjs'), join(fixtureLib, 'mesh-approval.mjs'));
const { FileTaskStore, DefaultRequestHandler, apply } = await import(pathToFileURL(join(fixtureLib, 'index.mjs')));

const file = join(fixture, 'a2a-tasks.json');
const working = id => ({ id, contextId: 'synthetic-context', status: { state: 2 }, artifacts: [], history: [] });
const original = Buffer.from(JSON.stringify([working('synthetic-old-task')]));
await writeFile(file, original);
let creates = 0;
const routes = [], disposers = [];
const ctx = {
  logger: { warn() {}, error() {} },
  agents: { async create() { creates++; throw Error('Synthetic host forbids worker creation.'); } },
  get(name) {
    if (name === 'sessionPersistence') return {};
    if (name === 'webServer') return { register(route) { routes.push(route); return () => {}; } };
    return undefined;
  },
  on() {},
  effect(factory) { disposers.push(factory()); },
};
await apply(ctx, { persistTasks: true, persistenceRoot: fixture, cwd: fixture });
assert.equal(creates, 0);
assert.ok(routes.some(route => route.path === '/a2a'), 'Actual startup must register the task route.');
assert.deepEqual(await readFile(file), original);
for (const dispose of disposers.reverse()) await dispose();
assert.equal(creates, 0);

const store = new FileTaskStore(file);
await store.init();
assert.equal((await store.load('synthetic-old-task', {})).status.state, 2);
let nativeCancels = 0;
const handler = new DefaultRequestHandler({}, store, {
  async execute() { throw Error('Synthetic test forbids execution.'); },
  async cancelTask() { nativeCancels++; },
});
const cancelled = await handler.cancelTask({ id: 'synthetic-old-task' }, {});
assert.equal(cancelled.status.state, 5);
assert.equal(nativeCancels, 0);
assert.equal(cancelled.writerQuiescence, undefined);
const reopened = new FileTaskStore(file);
await reopened.init();
assert.equal((await reopened.load('synthetic-old-task', {})).status.state, 5);
assert.equal(hash(await readFile(join(installed, 'index.js'))), expectedBundle);
assert.equal(hash(await readFile(join(installed, 'mesh-approval.mjs'))), hash(approval));

const result = {
  observedAt: new Date().toISOString(), fixture, sourceSha256: expectedBundle,
  checks: {
    startupLoadsWithoutCreatingWorkers: true, actualTaskRouteRegistered: true,
    startupPreservesSavedTaskBytes: true, cleanupCreatesNoWorkers: true,
    freshStoreRetainsWorkingState: true, cancellationCanBeMetadataOnly: true,
    noNativeCancellationCalled: true, cancellationHasNoRetirementProof: true,
    cancelledMetadataSurvivesReopen: true, installedSourceUnchanged: true,
  },
  boundary: 'Installed-code snapshot with export-only instrumentation, synthetic task file and fake host. No live services, credentials, provider calls or real task operations. Not whole-worker retirement or production restart acceptance.',
};
await writeFile(join(data, 'dsh-legacy-recovery-qualification-20261112.json'), JSON.stringify(result, null, 2) + '\n');
process.stdout.write(JSON.stringify(result) + '\n');
