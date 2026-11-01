import { getPublicEntry, handlePublicFetch } from '/shell-cache-policy.mjs';

// Register as a module worker at /sw.js with scope / in the parent app.
// Shell cache 06. No install precache, activation purge, skipWaiting, clients.claim, or messages.
self.addEventListener('fetch', event => {
  const origin = self.location.origin;
  if (!getPublicEntry(event.request, origin)) return;
  event.respondWith(handlePublicFetch(event.request, {
    origin, cacheStorage: self.caches, fetchImpl: request => self.fetch(request),
  }));
});
