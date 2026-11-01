'use strict';
// Network-only: never cache conversations, approvals, attachments or app pages.
self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET' || event.request.mode !== 'navigate' ||
      new URL(event.request.url).origin !== self.location.origin) return;
  event.respondWith(fetch(event.request, {cache: 'no-store'}).catch(() => new Response(
    '<!doctype html><html lang="en"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="theme-color" content="#0d0d0f"><title>Mesh — connection unavailable</title><body style="background:#0d0d0f;color:#eee;font:16px monospace;padding:24px"><p>dummy??</p><h1>Mesh is showing offline</h1><p>Reconnect Tailscale and check that the PC is running. This app does not keep an offline copy of your conversation.</p><button onclick="location.reload()">Try again</button></body></html>',
    {status: 503, headers: {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'}}
  )));
});

// ---------------------------------------------------------------------------
// Opt-in Web Push (generic alerts only).
//
// The payload is always generic -- the server sends {"title": "Onoes Mesh",
// "body": "New Relay message"} and nothing else ever leaves the PC, so the
// browser vendor cannot read the conversation. The click target is this
// document's own origin and nothing else; opening a notification only opens
// or focuses the page. It never sends, approves, answers, or starts work, and
// it never caches a conversation.
// ---------------------------------------------------------------------------
const PUSH_ALLOWED_ORIGIN = self.location.origin;
const PUSH_ALLOWED_PATH = '/#relay';

function pushPayload(event) {
  // This worker is not a place to trust a payload, so it renders the generic
  // alert and nothing else. Whatever the decrypted body contains -- a chat
  // line, a question, an object, garbage -- the notification says the same
  // two lines. That keeps the promise made to the owner (generic only, no
  // conversation content) a property of the *receiver*, not only of the
  // sender, and it means a provider bug cannot leak the room into the
  // status bar. `data` is read so a malformed body cannot throw.
  try {
    // Read the body only to prove it cannot break this handler; nothing from
    // it is used. A body that is absent, empty or malformed all behave the
    // same way here: the generic alert still shows.
    if (event.data) event.data.json();
  } catch (_) {
    // Fall through: the generic alert is shown either way.
  }
  return {
    body: 'New Relay message',
    icon: '/mesh-icon-192.png',
    badge: '/mesh-badge-r-96.png',
    // One visible notification per generic alert, so a burst of messages
    // never floods the status bar. No silent:false/true here: the phone's
    // own settings decide sound and vibration.
    tag: 'relay-generic',
    renotify: true,
    requireInteraction: false,
  };
}

// Persist only a boolean sound preference, never conversations or attachments.
function soundPreference(value) {
  return new Promise((resolve, reject) => {
    const opening = indexedDB.open('relay-alert-preference', 1);
    opening.onupgradeneeded = () => opening.result.createObjectStore('preferences');
    opening.onerror = () => reject(new Error('Preference unavailable'));
    opening.onsuccess = () => {
      const db = opening.result;
      const tx = db.transaction('preferences', value === undefined ? 'readonly' : 'readwrite');
      const store = tx.objectStore('preferences');
      const request = value === undefined ? store.get('silent') : store.put(value === true, 'silent');
      let result = false;
      request.onsuccess = () => { result = value === undefined ? request.result === true : value === true; };
      tx.oncomplete = () => { db.close(); resolve(result); };
      tx.onerror = tx.onabort = () => { db.close(); reject(new Error('Preference unavailable')); };
    };
  });
}
self.addEventListener('message', event => {
  if (!event.data || event.data.type !== 'relay-push-sound' || typeof event.data.silent !== 'boolean') return;
  event.waitUntil(soundPreference(event.data.silent).then(() => {
    if (event.ports[0]) event.ports[0].postMessage({ok:true});
  }).catch(() => { if (event.ports[0]) event.ports[0].postMessage({ok:false}); }));
});
self.addEventListener('push', event => {
  event.waitUntil(soundPreference().catch(() => false).then(silent => {
    const options = pushPayload(event);
    if (silent) options.silent = true;
    return self.registration.showNotification('Onoes Mesh', options);
  }));
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  const target = new URL(PUSH_ALLOWED_PATH, PUSH_ALLOWED_ORIGIN);
  event.waitUntil(self.clients.matchAll({type: 'window', includeUncontrolled: true})
    .then(windows => {
      for (const window of windows) {
        // Focus an existing Relay tab rather than opening a second one.
        if (window.url && new URL(window.url).href === target.href) {
          return window.focus();
        }
      }
      return self.clients.openWindow(target.href);
    })
    .catch(() => undefined));
});
