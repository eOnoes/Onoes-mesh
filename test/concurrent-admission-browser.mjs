import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import { pathToFileURL } from 'node:url';
import { startApp } from '../server.mjs';

const { chromium } = await import(process.env.M5_NODES_PLAYWRIGHT
  ? pathToFileURL(process.env.M5_NODES_PLAYWRIGHT).href : 'playwright');
const app = await startApp({ dataDir: 'data/concurrent-tabs-' + randomUUID(), standalone: true, relayEnabled: false });
let browser;
try {
  browser = await chromium.launch({ executablePath: process.env.M5_NODES_CHROMIUM });
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const pages = await Promise.all([context.newPage(), context.newPage()]);
  let bootstraps = 0;
  await context.route('**/api/trial-session/bootstrap', async route => {
    bootstraps++;
    // Model the round trip while both fresh tabs are trying to connect.
    await delay(250);
    await route.continue();
  });
  await Promise.all(pages.map(async page => {
    await page.goto(app.url + '/#workroom');
    await page.locator('#rail-menu').tap();
  }));
  // Native touch actions bring each tab to the foreground in sequence. Dispatch
  // both Start gestures together to exercise an overlapping navigation.
  const started = pages.map(page => page.waitForResponse(r =>
    ['/api/health', '/api/trial-session/bootstrap'].includes(new URL(r.url()).pathname)));
  await Promise.all(pages.map(page => page.locator('#demo-start').evaluate(button => button.click())));
  await Promise.all(started);
  assert.equal(bootstraps, 1, 'Opening two tabs together should create one browser session');
  for (const page of pages) {
    await page.waitForFunction(() => !document.querySelector('#refresh').disabled);
    const [tasks] = await Promise.all([
      page.waitForResponse(r => new URL(r.url()).pathname === '/api/tasks'),
      page.locator('#refresh').tap(),
    ]);
    assert.equal(tasks.status(), 200);
  }
  assert.equal(bootstraps, 1);
  console.log('Two phone-width tabs connected, one bootstrap, both boards refreshed.');

  const holder = pages[0];
  const proof = await holder.evaluate(() => JSON.parse(sessionStorage.getItem('mesh.synthetic-demo.proof.v1')));
  const cookie = (await context.cookies()).find(({name}) => name === 'mesh_trial');
  assert.ok(proof && cookie?.httpOnly, 'Both tabs use a verified session and the shared HttpOnly cookie');
  const postOutsideBrowser = (route, body) => fetch(app.url + route, {
    method: 'POST', body: JSON.stringify(body), headers: {
      Origin: app.url, Cookie: `${cookie.name}=${cookie.value}`,
      'Content-Type': 'application/json', 'X-Trial-CSRF': proof.csrfToken,
    },
  });
  const title = 'Disposable Workroom card after a stale peer';
  const saved = await postOutsideBrowser('/api/tasks', { title, description: '', label: '', status: 'open' });
  assert.equal(saved.status, 201);
  await saved.json();

  // A background browser tab may still offer proof from before a server
  // restart. Revoke outside its cookie jar and deliver that exact old proof.
  assert.equal((await postOutsideBrowser('/api/trial-session/logout', {})).status, 204);
  assert.ok((await context.cookies()).some(item => item.name === cookie.name && item.value === cookie.value));
  await holder.evaluate(oldProof => {
    window.staleAdmissionFixture = new BroadcastChannel('mesh.admission-peer.v1');
    window.staleAdmissionFixture.onmessage = ({ data }) => {
      if (data.type === 'request') window.staleAdmissionFixture.postMessage({
        type: 'candidate', requestId: data.requestId, proof: oldProof,
      });
    };
  }, proof);

  const reopened = await context.newPage();
  const observed = [];
  const writes = [];
  reopened.on('response', response => observed.push([new URL(response.url()).pathname, response.status()]));
  reopened.on('request', request => {
    if (request.method() !== 'GET') writes.push(new URL(request.url()).pathname);
  });
  await reopened.goto(app.url + '/#workroom');
  await reopened.locator('#workroom-session-start').tap();
  await reopened.getByText(title, { exact: true }).first().waitFor({state: 'visible', timeout: 10000});
  assert.deepEqual(observed.filter(([route]) => route === '/api/health' || route.startsWith('/api/trial-session/')).slice(0, 4), [
    ['/api/health', 401],
    ['/api/trial-session/bootstrap', 401],
    ['/api/trial-session/bootstrap', 201],
    ['/api/health', 200],
  ]);
  assert.deepEqual(writes, ['/api/trial-session/bootstrap', '/api/trial-session/bootstrap']);
  assert.equal(bootstraps, 3, 'The rejected peer uses only the existing stale-cookie clearing round trip');
  console.log('One phone tap recovered a rejected sibling session and reopened the saved board.');
} finally {
  try { await browser?.close(); } finally { await app.close(); }
}
