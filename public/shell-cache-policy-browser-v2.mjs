/** Public static shell only. No auth, API authority, messages, or mutation queues. */
export const POLICY_VERSION = 1;
export const CACHE_NAME = 'onoes-mesh-public-shell-cache04-v21';
export const PUBLIC_ASSETS = Object.freeze({
  '/': Object.freeze(['text/html']),
  '/app.js': Object.freeze(['text/javascript', 'application/javascript']),
  '/styles.css': Object.freeze(['text/css']),
  '/manifest.webmanifest': Object.freeze(['application/manifest+json']),
  '/icon.svg': Object.freeze(['image/svg+xml']),
  '/shell-cache-policy.mjs': Object.freeze(['text/javascript', 'application/javascript']),
  '/sw.js': Object.freeze(['text/javascript', 'application/javascript']),
});
export const MAX_ENTRIES = Object.keys(PUBLIC_ASSETS).length;
const SAFE_REQUEST_HEADERS = new Set([
  'accept', 'accept-language', 'cache-control', 'pragma', 'user-agent',
  'sec-ch-ua', 'sec-ch-ua-mobile', 'sec-ch-ua-platform', 'upgrade-insecure-requests',
  'sec-fetch-dest', 'sec-fetch-mode', 'sec-fetch-site', 'sec-fetch-user',
]);

function ownedOrigin(value) {
  try {
    const url = new URL(value);
    return url.origin === value && url.protocol === 'http:' &&
      ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname) ? value : null;
  } catch { return null; }
}

function staticURL(value, origin) {
  if (!ownedOrigin(origin) || typeof value !== 'string' || /[?#]/u.test(value)) return null;
  try {
    const url = new URL(value);
    if (url.origin !== origin || url.username || url.password || url.href !== value ||
        !Object.hasOwn(PUBLIC_ASSETS, url.pathname)) return null;
    return Object.freeze({ url: origin + url.pathname, path: url.pathname,
      mimeTypes: PUBLIC_ASSETS[url.pathname] });
  } catch { return null; }
}

function hasOnlySafeHeaders(headers, origin) {
  for (const [name, value] of headers) {
    if (name.toLowerCase() === 'origin' && ownedOrigin(origin) && value === origin) continue;
    if (!SAFE_REQUEST_HEADERS.has(name.toLowerCase())) return false;
  }
  return true;
}

/** Returns a bounded canonical descriptor, or null. Root requires navigation. */
export function getPublicEntry(request, origin) {
  if (!(request instanceof Request) || request.method !== 'GET' ||
      !hasOnlySafeHeaders(request.headers, origin)) return null;
  const entry = staticURL(request.url, origin);
  if (!entry || (entry.path === '/' && request.mode !== 'navigate')) return null;
  return entry;
}

/** Never copy caller headers, cookies, credentials, referrer, or request body. */
export function makePopulationRequest(request, origin) {
  const entry = getPublicEntry(request, origin);
  if (!entry) throw new TypeError('Request is outside the public shell policy');
  return canonicalRequest(entry);
}

function canonicalRequest(entry) {
  return new Request(entry.url, {
    method: 'GET', credentials: 'omit', mode: 'same-origin', redirect: 'error',
    cache: 'no-store', referrer: '', referrerPolicy: 'no-referrer',
    headers: { Accept: entry.mimeTypes.join(', ') },
  });
}

/** Metadata must be browser-supplied; public HTML must also be static by contract. */
export function isAdmissibleResponse(response, canonicalURL, origin) {
  const entry = staticURL(canonicalURL, origin);
  if (!entry || !(response instanceof Response) || response.status !== 200 ||
      response.type !== 'basic' || response.redirected || response.url !== entry.url ||
      response.headers.has('set-cookie') || response.headers.has('set-cookie2') ||
      response.headers.has('vary') || response.headers.has('location')) return false;
  const mime = (response.headers.get('content-type') ?? '').split(';')[0].trim().toLowerCase();
  if (!entry.mimeTypes.includes(mime)) return false;
  const control = response.headers.get('cache-control') ?? '';
  // Fail closed on quoted values rather than misreading commas inside quotes.
  if (control.includes('"')) return false;
  const directives = control.split(',')
    .map(value => value.trim().toLowerCase());
  return directives.includes('public') && !directives.some(value =>
    ['no-store', 'private'].includes(value.split('=')[0].trim()));
}

async function inspectKeys(cache, origin) {
  const keys = await cache.keys();
  if (keys.length > MAX_ENTRIES) return null;
  const seen = new Set();
  for (const key of keys) {
    if (!(key instanceof Request) || key.method !== 'GET' || key.credentials !== 'omit' ||
        !staticURL(key.url, origin) || !hasOnlySafeHeaders(key.headers) || seen.has(key.url)) return null;
    seen.add(key.url);
  }
  return keys;
}

async function readAccepted(cacheStorage, key, origin) {
  // Do not create a cache just to look for an offline entry.
  if (!(await cacheStorage.has(CACHE_NAME))) return null;
  const cache = await cacheStorage.open(CACHE_NAME);
  const keys = await inspectKeys(cache, origin);
  if (!keys?.some(candidate => candidate.url === key.url && candidate.method === 'GET')) return null;
  const response = await cache.match(key, { ignoreSearch: false, ignoreMethod: false, ignoreVary: false });
  return isAdmissibleResponse(response, key.url, origin) ? response : null;
}

async function storeAccepted(cacheStorage, key, response, origin) {
  const cache = await cacheStorage.open(CACHE_NAME);
  const keys = await inspectKeys(cache, origin);
  if (!keys || (keys.length === MAX_ENTRIES && !keys.some(candidate => candidate.url === key.url))) return;
  await cache.put(key, response.clone());
}

/** Network first via sanitized GET; only thrown network failure permits cache lookup.
 * Ineligible requests reject here and are left untouched by the SW event wrapper.
 * Storage errors never turn a failed request into a synthetic success.
 */
export async function handlePublicFetch(request, { origin, cacheStorage, fetchImpl }) {
  const key = makePopulationRequest(request, origin);
  let response;
  try {
    response = await fetchImpl(key);
  } catch (networkError) {
    try {
      const cached = await readAccepted(cacheStorage, key, origin);
      if (cached) return cached;
    } catch { /* unavailable storage: preserve original network failure */ }
    throw networkError;
  }
  if (isAdmissibleResponse(response, key.url, origin)) {
    try { await storeAccepted(cacheStorage, key, response, origin); }
    catch { /* Cache quota/availability must not break a valid network response. */ }
  }
  return response;
}
