import { randomBytes, timingSafeEqual } from 'node:crypto';

export const SESSION_COOKIE_NAME = 'mesh_trial';
export const TRIAL_ACTOR = Object.freeze({
  type: 'SYNTHETIC_TRIAL',
  role: 'SYNTHETIC_TRIAL',
  capabilities: Object.freeze(['trial:read', 'trial:mutate']),
});

const ID = /^[A-Za-z0-9_-]{43}$/;
const managers = new WeakSet();
const READ = new Set(['GET', 'HEAD']);
const WRITE = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);
const CLAIMS = new Set(['actor', 'role', 'roles', 'capability', 'capabilities',
  'identity', 'user', 'userid', 'credentials', 'credential', 'password', 'authorization',
  '__proto__', 'prototype', 'constructor']);
const normalize = value => value.toLowerCase().replace(/[-_]/g, '');
const forbidden = key => CLAIMS.has(key.toLowerCase()) || CLAIMS.has(normalize(key));

function options(value, allowed) {
  if (!value || Object.getPrototypeOf(value) !== Object.prototype ||
      Reflect.ownKeys(value).some(key => !allowed.includes(key))) {
    throw new TypeError('Invalid settings');
  }
}

function integer(value, min, max) {
  if (!Number.isSafeInteger(value) || value < min || value > max) {
    throw new TypeError('Invalid settings');
  }
}

export function createTrialSessionManager(settings) {
  options(settings, ['ttlMs', 'maxSessions', 'now']);
  const { ttlMs, maxSessions, now = Date.now } = settings;
  integer(ttlMs, 1, 86_400_000);
  integer(maxSessions, 1, 10_000);
  if (typeof now !== 'function') throw new TypeError('Invalid settings');
  const sessions = new Map();
  // At most one short-lived challenge per session, never private authority.
  const challenges = new Map();
  let lastTime = -1;
  function time() {
    const value = now();
    integer(value, 0, Number.MAX_SAFE_INTEGER - ttlMs);
    if (value < lastTime) throw new RangeError('Clock moved backwards');
    lastTime = value;
    return value;
  }
  time();
  function sweep(at) {
    for (const [id, session] of sessions) {
      if (session.expiresAt <= at) sessions.delete(id);
    }
    for (const [nonce, challenge] of challenges) {
      if (challenge.expiresAt <= at || !sessions.has(challenge.sessionId)) challenges.delete(nonce);
    }
  }
  function newSession(at) {
    let sessionId;
    do { sessionId = randomBytes(32).toString('base64url'); } while (sessions.has(sessionId));
    return Object.freeze({ sessionId, csrfToken: randomBytes(32).toString('base64url'),
      actor: TRIAL_ACTOR, createdAt: at, expiresAt: at + ttlMs });
  }
  function removeChallenges(id) {
    for (const [nonce, challenge] of challenges) if (challenge.sessionId === id) challenges.delete(nonce);
  }
  const manager = Object.freeze({
    createSession(...args) {
      if (args.length) throw new TypeError('Client claims are not accepted');
      const at = time();
      sweep(at);
      if (sessions.size >= maxSessions) {
        const error = new Error('Session capacity reached');
        error.code = 'TRIAL_CAPACITY';
        throw error;
      }
      const session = newSession(at);
      sessions.set(session.sessionId, session);
      return session;
    },
    createRecoveryChallenge(sessionId) {
      const at = time(); sweep(at);
      const session = sessions.get(sessionId);
      if (!session) return null;
      let nonce;
      do { nonce = randomBytes(32).toString('base64url'); } while (challenges.has(nonce));
      const expiresAt = Math.min(session.expiresAt, at + Math.min(ttlMs, 30000));
      removeChallenges(sessionId);
      challenges.set(nonce, Object.freeze({ sessionId, expiresAt }));
      return Object.freeze({ challenge: nonce, expiresAt });
    },
    completeRecovery(sessionId, nonce) {
      const at = time(); sweep(at);
      if (typeof nonce !== 'string' || !ID.test(nonce)) return null;
      const challenge = challenges.get(nonce);
      if (!challenge || challenge.sessionId !== sessionId || !sessions.has(sessionId)) return null;
      // Allocate before changing admission; then consume/revoke/replace without
      // an await. Rotation works at capacity without evicting other sessions.
      const session = newSession(at);
      removeChallenges(sessionId);
      sessions.delete(sessionId);
      sessions.set(session.sessionId, session);
      return session;
    },
    authorize(sessionId, settings = {}) {
      options(settings, ['mutation', 'csrfToken']);
      const { mutation = false, csrfToken } = settings;
      if (typeof mutation !== 'boolean') throw new TypeError('Invalid authorization settings');
      const at = time();
      sweep(at);
      if (typeof sessionId !== 'string' || !ID.test(sessionId)) return null;
      const session = sessions.get(sessionId);
      if (!session) return null;
      if (mutation && (typeof csrfToken !== 'string' || !ID.test(csrfToken) ||
          !timingSafeEqual(Buffer.from(csrfToken), Buffer.from(session.csrfToken)))) return null;
      return Object.freeze({ actor: TRIAL_ACTOR, expiresAt: session.expiresAt });
    },
    revoke(sessionId) {
      removeChallenges(sessionId);
      return typeof sessionId === 'string' && ID.test(sessionId) && sessions.delete(sessionId);
    },
    sweepExpired() { sweep(time()); return sessions.size; },
    size() { sweep(time()); return sessions.size; },
  });
  managers.add(manager);
  return manager;
}

class HttpFailure extends Error {
  constructor(status) { super('Trial request denied'); this.status = status; }
}
const deny = (status, reason = '') => { const e = new HttpFailure(status); e.reason = reason; throw e; };

function inspectClaims(value, depth = 0) {
  if (depth > 16) deny(400);
  if (value && typeof value === 'object') {
    for (const [key, child] of Object.entries(value)) {
      if (forbidden(key)) deny(403);
      inspectClaims(child, depth + 1);
    }
  }
}

function requestHeaders(req, host, origin) {
  if (req.socket?.remoteAddress !== '127.0.0.1' || req.socket?.encrypted) deny(403, 'socket-not-loopback:' + (req.socket?.remoteAddress || '?'));
  const raw = req.rawHeaders;
  if (!Array.isArray(raw) || raw.length % 2 || raw.length > 128) deny(400);
  let bytes = 0;
  const found = new Map();
  for (let i = 0; i < raw.length; i += 2) {
    const name = raw[i];
    const value = raw[i + 1];
    if (typeof name !== 'string' || typeof value !== 'string') deny(400);
    bytes += Buffer.byteLength(name) + Buffer.byteLength(value);
    if (bytes > 8192 || !/^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/.test(name) ||
        /[^\x20-\x7e]/.test(value)) deny(400);
    const key = name.toLowerCase();
    if (['host', 'origin', 'cookie', 'x-trial-csrf', 'sec-fetch-site', 'content-type', 'content-length'].includes(key) &&
        found.has(key)) deny(400);
    if (key === 'authorization' || (key.startsWith('x-') && forbidden(key.slice(2)))) deny(403, 'forbidden-header:' + key);
    found.set(key, value);
  }
  if (found.get('host') !== host) deny(403, 'host-mismatch:' + found.get('host'));
  if (found.has('origin')) {
    if (found.get('origin') !== origin) deny(403, 'origin-mismatch:' + found.get('origin'));
  } else {
    if (!READ.has(req.method) || (found.has('sec-fetch-site') &&
        found.get('sec-fetch-site') !== 'same-origin')) deny(403, 'no-origin-write:' + req.method);
  }
  if (typeof req.url !== 'string' || req.url.length > 2048 ||
      !req.url.startsWith('/') || req.url.startsWith('//') || req.url.includes('#')) deny(400);
  let url;
  try { decodeURIComponent(req.url); url = new URL(req.url, origin); } catch { deny(400); }
  if (url.origin !== origin) deny(403);
  for (const key of url.searchParams.keys()) if (forbidden(key)) deny(403);
  return found;
}

function cookieId(headers) {
  const cookie = headers.get('cookie');
  if (cookie === undefined) return null;
  if (!cookie || Buffer.byteLength(cookie) > 2048) deny(400);
  const pairs = cookie.split(';');
  if (pairs.length > 32) deny(400);
  const names = new Set();
  let id = null;
  for (const pair of pairs) {
    const item = pair.trim();
    const match = /^([!#$%&'*+.^_`|~0-9A-Za-z-]+)=([\x21\x23-\x2b\x2d-\x3a\x3c-\x5b\x5d-\x7e]*)$/.exec(item);
    if (!match || names.has(match[1])) deny(400);
    names.add(match[1]);
    if (match[1] === SESSION_COOKIE_NAME) {
      if (!ID.test(match[2])) deny(400);
      id = match[2];
    }
  }
  return id;
}

function jsonBody(req, headers) {
  if (headers.get('content-type') !== 'application/json') deny(415);
  const length = headers.get('content-length');
  if (length !== undefined && (!/^(0|[1-9][0-9]*)$/.test(length) || Number(length) > 4096)) deny(413);
  return new Promise((resolve, reject) => {
    const chunks = [];
    let bytes = 0;
    let settled = false;
    const timer = setTimeout(() => finish(new HttpFailure(408)), 2000);
    timer.unref();
    function finish(error, body) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      req.off('data', data); req.off('end', end); req.off('error', failed); req.off('aborted', failed);
      if (error) { req.resume(); reject(error); } else resolve(body);
    }
    function data(chunk) {
      bytes += chunk.length;
      if (bytes > 4096) return finish(new HttpFailure(413));
      chunks.push(chunk);
    }
    function failed() { finish(new HttpFailure(400)); }
    function end() {
      try {
        const body = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks)));
        if (!body || Array.isArray(body) || typeof body !== 'object') deny(400);
        inspectClaims(body);
        finish(null, body);
      } catch (error) { finish(error instanceof HttpFailure ? error : new HttpFailure(400)); }
    }
    req.on('data', data); req.on('end', end); req.on('error', failed); req.on('aborted', failed);
  });
}

function noStore(res) {
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('Pragma', 'no-cache');
  res.setHeader('X-Content-Type-Options', 'nosniff');
}

function failure(req, res, error) {
  req.resume();
  // Which rule refused, and the headers that decided it — never a cookie or token.
  // A bare 403 with no reason cost an hour of guessing during the G2 cutover.
  try {
    console.log(JSON.stringify({
      event: 'trial_denied',
      status: error instanceof HttpFailure ? error.status : 500,
      reason: error?.reason ?? null,
      method: req.method,
      url: String(req.url).slice(0, 160),
      host: req.headers.host ?? null,
      origin: req.headers.origin ?? null,
      sfs: req.headers['sec-fetch-site'] ?? null,
      at: new Date().toISOString(),
    }));
  } catch { /* logging must never change a response */ }
  res.statusCode = error instanceof HttpFailure ? error.status :
    error?.code === 'TRIAL_CAPACITY' ? 503 : 500;
  res.end();
  return null;
}

// Each method performs actual IncomingMessage enforcement before returning context or responding.
export function createTrialHttpGuard(settings) {
  options(settings, ['manager', 'port']);
  const { manager, port } = settings;
  integer(port, 1, 65535);
  if (!managers.has(manager)) throw new TypeError('Invalid manager');
  const host = `127.0.0.1:${port}`;
  const origin = `http://${host}`;
  const clearCookie = `${SESSION_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0`;
  function boundary(req, res) {
    noStore(res);
    const headers = requestHeaders(req, host, origin);
    const id = cookieId(headers);
    return { headers, id };
  }
  async function admitted(req, res, onlyPost = false) {
    const { headers, id } = boundary(req, res);
    if ((onlyPost && req.method !== 'POST') || (!READ.has(req.method) && !WRITE.has(req.method))) deny(405);
    const session = manager.authorize(id);
    if (!session) deny(401);
    const mutation = WRITE.has(req.method);
    // Originless browser reads require the same session-bound proof as mutations.
    // A supplied proof must be valid even on an Origin-bearing read. In
    // particular, a recovery nonce never substitutes for private authority.
    const requireCsrf = mutation || !headers.has('origin') || headers.has('x-trial-csrf');
    if (requireCsrf && !manager.authorize(id, { mutation: true, csrfToken: headers.get('x-trial-csrf') })) deny(403);
    const body = mutation ? await jsonBody(req, headers) : null;
    if (!mutation && (headers.has('transfer-encoding') ||
        (headers.has('content-length') && headers.get('content-length') !== '0'))) deny(400);
    // Recheck after asynchronous body input: expiry and revocation may happen while it is arriving.
    if (!manager.authorize(id, { mutation: requireCsrf, csrfToken: headers.get('x-trial-csrf') })) deny(401);
    return { id, session, body };
  }
  function admission(res, session) {
    res.setHeader('Set-Cookie', `${SESSION_COOKIE_NAME}=${session.sessionId}; Path=/; HttpOnly; SameSite=Strict; Max-Age=${Math.ceil((session.expiresAt - session.createdAt) / 1000)}`);
    res.setHeader('Content-Type', 'application/json; charset=utf-8');
    res.statusCode = 201;
    res.end(JSON.stringify({ admission: 'EXPLICIT_SYNTHETIC_DEMO', actor: session.actor,
      csrfToken: session.csrfToken, expiresAt: session.expiresAt }));
    return true;
  }
  async function recoveryInput(req, res) {
    const initial = boundary(req, res);
    if (req.method !== 'POST') deny(405);
    const body = await jsonBody(req, initial.headers);
    if (Object.keys(body).length) deny(400);
    // Revalidate all request boundaries and exact cookie binding after input.
    const current = boundary(req, res);
    if (current.id !== initial.id || current.headers.get('x-trial-csrf') !== initial.headers.get('x-trial-csrf')) deny(403);
    return current;
  }
  return Object.freeze({
    trustedOrigin: origin,
    async recoveryChallenge(req, res) {
      try {
        const { headers, id } = await recoveryInput(req, res);
        if (headers.has('x-trial-csrf')) deny(403);
        const challenge = manager.createRecoveryChallenge(id);
        if (!challenge) deny(401);
        res.setHeader('Content-Type', 'application/json; charset=utf-8');
        res.statusCode = 200;
        res.end(JSON.stringify(challenge));
        return true;
      } catch (error) { return failure(req, res, error); }
    },
    async recoveryComplete(req, res) {
      try {
        const { headers, id } = await recoveryInput(req, res);
        const session = manager.completeRecovery(id, headers.get('x-trial-csrf'));
        if (!session) deny(403);
        return admission(res, session);
      } catch (error) { return failure(req, res, error); }
    },
    async bootstrap(req, res) {
      try {
        const { headers, id } = boundary(req, res);
        if (req.method !== 'POST') deny(405);
        if (id !== null) {
          if (!manager.authorize(id)) {
            // A restart/expiry invalidates admission, but the old HttpOnly
            // cookie must not prevent the next explicit session request.
            res.setHeader('Set-Cookie', clearCookie);
            deny(401);
          }
          if (!manager.authorize(id, { mutation: true, csrfToken: headers.get('x-trial-csrf') })) deny(403);
          deny(409);
        }
        const body = await jsonBody(req, headers);
        if (Object.keys(body).length) deny(400);
        const session = manager.createSession();
        return admission(res, session);
      } catch (error) { return failure(req, res, error); }
    },
    async authorize(req, res) {
      try {
        const { session, body } = await admitted(req, res);
        return Object.freeze({ actor: session.actor, expiresAt: session.expiresAt, body });
      } catch (error) { return failure(req, res, error); }
    },
    async logout(req, res) {
      try {
        const { id, body } = await admitted(req, res, true);
        if (Object.keys(body).length) deny(400);
        manager.revoke(id);
        res.setHeader('Set-Cookie', clearCookie);
        res.statusCode = 204;
        res.end();
        return true;
      } catch (error) { return failure(req, res, error); }
    },
  });
}
