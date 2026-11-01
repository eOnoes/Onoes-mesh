'use strict';
// Isolated tests for the opt-in Web Push slice: service-worker push/click
// handling and the Settings controls. No real notification is shown, no real
// permission is requested, and no network call leaves this fixture.
const fs = require('fs'), vm = require('vm'), assert = require('assert');

// ---------------------------------------------------------------------------
// Service worker fixture
// ---------------------------------------------------------------------------
function swFixture(origin = 'https://emitchell.tail8c4a75.ts.net:8450') {
  const listeners = {};
  const notifications = [];
  const opened = [];
  const sw = {
    self: {
      location: {origin},
      clients: {
        claim: async () => {},
        openWindow: async url => { opened.push(url); return null; },
        matchAll: async () => sw.__windows || [],
      },
      registration: {
        showNotification: async (title, options) => { notifications.push({title, options}); },
      },
      addEventListener: (name, fn) => { listeners[name] = fn; },
      skipWaiting: async () => {},
    },
    URL, Response, fetch: async () => { throw new Error('offline'); },
    __windows: [],
  };
  vm.createContext(sw);
  vm.runInContext(fs.readFileSync('mesh-sw.js', 'utf8'), sw);
  return {listeners, notifications, opened, sw};
}

function pushEvent(data) {
  const waits = [];
  return {
    data: data === undefined ? null : {json: () => data},
    waits,
    waitUntil(promise) { waits.push(promise); return promise; },
  };
}

async function main() {
  const basic = swFixture();
  let intercepted = false;
  basic.listeners.fetch({request: {method: 'POST', mode: 'navigate', url: 'https://x/api/send'},
    respondWith() { intercepted = true; }});
  assert(!intercepted, 'POST navigation must not be intercepted');
  basic.listeners.fetch({request: {method: 'GET', mode: 'cors', url: 'https://x/api/history'},
    respondWith() { intercepted = true; }});
  assert(!intercepted, 'a cors request must not be intercepted');
  assert(!intercepted, 'non-navigation GET must not be intercepted');
  // A separate worker for the navigation case, so an earlier refusal cannot
  // be mistaken for this one.
  const nav = swFixture();
  let offline = null;
  nav.listeners.fetch({request: {method: 'GET', mode: 'navigate',
    url: 'https://emitchell.tail8c4a75.ts.net:8450/'},
    respondWith(promise) { offline = promise; }});
  assert(offline, 'a same-origin navigation is intercepted');
  const offlineResponse = await offline;
  assert.equal(offlineResponse.status, 503, 'offline navigation still answers 503');

  // --- push: generic payload, no conversation content --------------------
  const pushed = swFixture();
  const event = pushEvent({title: 'Onoes Mesh', body: 'New Relay message'});
  pushed.listeners.push(event);
  await Promise.all(event.waits);
  assert.equal(pushed.notifications.length, 1, 'one notification per push event');
  assert.equal(pushed.notifications[0].title, 'Onoes Mesh');
  const options = pushed.notifications[0].options;
  assert.equal(options.body, 'New Relay message');
  assert.equal(options.tag, 'relay-generic');
  assert.equal(options.renotify, true);
  assert.equal(options.icon, '/mesh-icon-192.png');
  assert.equal(options.badge, '/mesh-badge-r-96.png');
  // The phone decides sound: the worker must not set silent:true/false.
  assert(!('silent' in options), 'silent must be left to the device');
  assert(!('vibrate' in options), 'vibration must be left to the device');

  // --- push: a hostile payload degrades to the generic body ---------------
  const hostile = swFixture();
  const hostileEvent = pushEvent({title: 'Eddie', body: 'The goal failed and here is the private log line'});
  hostile.listeners.push(hostileEvent);
  await Promise.all(hostileEvent.waits);
  assert.equal(hostile.notifications[0].title, 'Onoes Mesh');
  assert.equal(hostile.notifications[0].options.body, 'New Relay message');
  // No chat content survives anywhere in the notification.
  assert(!JSON.stringify(hostile.notifications).includes('private log line'));

  // --- push: a missing or unparseable payload still alerts generically ----
  for (const payload of [undefined, {}, null, {title: '', body: ''}]) {
    const generic = swFixture();
    const e = pushEvent(payload);
    generic.listeners.push(e);
    await Promise.all(e.waits);
    assert.equal(generic.notifications[0].title, 'Onoes Mesh');
    assert.equal(generic.notifications[0].options.body, 'New Relay message');
  }

  // --- push: a payload that is not JSON does not crash the worker ---------
  const badJson = swFixture();
  const badEvent = {data: {json: () => { throw new Error('bad json'); }}, waits: [],
    waitUntil(p) { this.waits.push(p); return p; }};
  let threw = false;
  try {
    badJson.listeners.push(badEvent);
    await Promise.all(badEvent.waits);
  } catch (_) { threw = true; }
  assert(!threw, 'a malformed push payload must not throw out of the handler');
  assert.equal(badJson.notifications.length, 1, 'a malformed payload still alerts');
  assert.equal(badJson.notifications[0].options.body, 'New Relay message');

  // --- notificationclick: opens/focuses this origin only ------------------
  const click = swFixture();
  let closed = 0;
  const clickEvent = {
    notification: {close() { closed += 1; }},
    waits: [],
    waitUntil(p) { this.waits.push(p); return p; },
  };
  click.listeners.notificationclick(clickEvent);
  await Promise.all(clickEvent.waits);
  assert.equal(closed, 1, 'the notification closes itself');
  assert.deepEqual(click.opened,
    ['https://emitchell.tail8c4a75.ts.net:8450/#relay'],
    'a click opens the private Relay route, nothing else');

  // --- notificationclick: an existing Relay tab is focused, not duplicated -
  const focus = swFixture();
  focus.sw.__windows = [{url: 'https://emitchell.tail8c4a75.ts.net:8450/#relay', focused: false,
    focus() { this.focused = true; return Promise.resolve(this); }}];
  const focusEvent = {
    notification: {close() {}}, waits: [],
    waitUntil(p) { this.waits.push(p); return p; },
  };
  focus.listeners.notificationclick(focusEvent);
  await Promise.all(focusEvent.waits);
  assert(focus.sw.__windows[0].focused, 'an open Relay tab is focused');
  assert.equal(focus.opened.length, 0, 'no second tab is opened');

  // --- notificationclick: a foreign tab is never focused ------------------
  const foreign = swFixture();
  foreign.sw.__windows = [{url: 'https://evil.example/', focused: false,
    focus() { this.focused = true; return Promise.resolve(this); }}];
  const foreignEvent = {
    notification: {close() {}}, waits: [],
    waitUntil(p) { this.waits.push(p); return p; },
  };
  foreign.listeners.notificationclick(foreignEvent);
  await Promise.all(foreignEvent.waits);
  assert(!foreign.sw.__windows[0].focused, 'a foreign tab is never focused');
  assert.equal(foreign.opened[0], 'https://emitchell.tail8c4a75.ts.net:8450/#relay');

  // --- the worker never caches -------------------------------------------
  assert(!fs.readFileSync('mesh-sw.js', 'utf8').includes('caches.'));

  console.log('PASS service-worker push payload, degradation, click target and focus rules');
}

// Node runs top-level await only inside a module or an async wrapper; wrap it
// explicitly so the exit code is decided by the assertions above.
main().catch(error => { console.error(error); process.exit(1); });
