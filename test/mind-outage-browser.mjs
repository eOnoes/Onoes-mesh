// Uses the disposable canonical Mind reader and the same browser settings as tripp-hardware-browser.mjs.
import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { once } from 'node:events';
import { mkdir } from 'node:fs/promises';
import http from 'node:http';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { openTaskStore } from '../lib/task-store.mjs';
import { startApp } from '../server.mjs';
import { canonicalMindFixture } from './mind-canonical-fixture.mjs';

const { chromium } = await import(process.env.M5_NODES_PLAYWRIGHT
  ? pathToFileURL(process.env.M5_NODES_PLAYWRIGHT).href : 'playwright');
const dir = 'data/mind-outage-' + randomUUID();
await mkdir(dir);
const store = openTaskStore(path.join(dir, 'tasks.sqlite'));
let card;
try { card = store.create({title: 'Printer enclosure clearance', owner: 'nims'}); }
finally { store.close(); }
const reader = await canonicalMindFixture(process.env.MESH_MIND_SOURCE, {bound: true});
const readerAddress = new URL(reader.baseUrl);
let reachable = true, interrupted = 0;
// Interrupt just the connection from Mesh to this reader. Its ledger, address
// and credential stay the same throughout the outage and recovery.
const link = http.createServer((req, res) => {
  if (!reachable) { interrupted++; req.socket.destroy(); return; }
  const upstream = http.request({
    hostname: readerAddress.hostname, port: readerAddress.port, path: req.url,
    method: req.method, headers: {...req.headers, host: readerAddress.host},
  }, reply => { res.writeHead(reply.statusCode, reply.headers); reply.pipe(res); });
  upstream.on('error', () => res.destroy());
  req.pipe(upstream);
});
let app, browser;
try {
  link.listen(0, '127.0.0.1');
  await once(link, 'listening');
  app = await startApp({ dataDir: dir, standalone: true, relayEnabled: false,
    mindRecallTestOptions: {source: 'disposable_fixture', baseUrl: 'http://127.0.0.1:' + link.address().port, token: reader.token} });
  browser = await chromium.launch({executablePath: process.env.M5_NODES_CHROMIUM});
  const page = await browser.newPage({viewport: {width: 390, height: 844}, isMobile: true, hasTouch: true});
  page.setDefaultTimeout(8000);
  let sessions = 0;
  page.on('request', req => { if (new URL(req.url()).pathname === '/api/trial-session/bootstrap') sessions++; });
  await page.goto(app.url + '/#mind');
  const menu = page.locator('#rail-menu');
  await menu.tap();
  await page.locator('#demo-start').tap();
  await page.waitForFunction(() => !document.querySelector('#refresh').disabled);
  if (await menu.getAttribute('aria-expanded') === 'true') await page.locator('#tab-mind').tap();
  const check = page.getByRole('button', {name: 'Check memory connection'});
  const read = page.getByRole('button', {name: 'Read matching memories'});
  const query = page.getByLabel('Search Onoes-Mind');
  const record = page.getByText('meshfixture shared', {exact: false});
  async function readShared() {
    await check.tap();
    await query.fill('meshfixture');
    await read.tap();
    await record.waitFor();
    assert.equal(await page.getByText(/meshfixture (HIDDEN|Echo private)/).count(), 0);
  }
  await readShared();
  reachable = false;
  await read.tap();
  await page.getByText('Memory read unavailable or invalid. Previous results cleared.').waitFor();
  assert.ok(interrupted > 0);
  assert.equal(await record.count(), 0);

  const openCard = () => page.evaluate(id => { location.hash = 'task=' + id; }, card.id);
  const sheet = page.getByRole('dialog', {name: 'Task details'});
  await openCard();
  await sheet.getByRole('button', {name: 'Edit card', exact: true}).tap();
  const goal = 'Measure both door hinges before printing.';
  await sheet.getByLabel('Goal', {exact: true}).fill(goal);
  // Dismiss the keyboard to restore the card's action bar.
  await sheet.getByLabel('Goal', {exact: true}).blur();
  const [saved] = await Promise.all([
    page.waitForResponse(r => new URL(r.url()).pathname === '/api/workroom/' + card.id + '/progress' && r.request().method() === 'PATCH'),
    sheet.getByRole('button', {name: 'Save changes', exact: true}).tap(),
  ]);
  assert.equal(saved.status(), 200);
  await sheet.waitFor({state: 'hidden'});
  await openCard();
  await sheet.getByText(goal, {exact: true}).first().waitFor();
  await sheet.getByRole('button', {name: 'Close card', exact: true}).tap();

  reachable = true;
  await page.evaluate(() => { location.hash = 'mind'; });
  await readShared();
  assert.equal(sessions, 1);
  console.log('Shared memory read, outage visible, old result cleared, Workroom goal saved and reopened, shared reader recovered in the same session.');
} finally {
  try { await browser?.close(); } finally {
    try { await app?.close(); } finally {
      if (link.listening) await new Promise(resolve => link.close(resolve));
      await reader.close();
    }
  }
}
