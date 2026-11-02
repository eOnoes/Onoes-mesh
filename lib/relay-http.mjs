/**
 * HTTP bridge to the LIVE Relay (R8a of the Gate G2 decision).
 *
 * The old `relay-link.mjs` drove a *modified copy* of Relay as a child process over
 * stdio. This module drives the real Relay over its own HTTP API instead, so there
 * is one database, one notification plane and one place the agent keys live.
 *
 * It exports the same method names as `createRelayLink`, deliberately: the server
 * should be able to swap one for the other behind a flag and nothing else should
 * know. The one difference that matters is where the Workroom link is written: the
 * old child asked Mesh to create the task over stdout *after* Relay accepted the
 * message, and the real Relay has no callback. So `message()` sends to Relay first
 * and writes the link second, from here. Nothing anywhere may write the link first.
 *
 * `snapshot()` returns the real agent list (four agents, real backends), not the
 * single synthetic `mesh` agent. Adapting the UI to tabs is R9.
 *
 * Security posture is copied from the old link, not loosened: a token is required,
 * it is only ever sent to a loopback origin, redirects are refused, responses are
 * size-capped, and no token or credential is ever logged or returned to a browser.
 */
import { readFile } from 'node:fs/promises';
import { TaskError } from './task-store.mjs';
// R8d deletes `relay-link.mjs`; when it does, this validator moves in here. Until
// then it is imported rather than copied, so the two cannot disagree about what a
// message is.
import { validateRelayMessage } from './relay-link.mjs';

const MAX_BODY_BYTES = 262144;
const DEFAULT_TIMEOUT_MS = 4000;
const LOOPBACK = new Set(['127.0.0.1', 'localhost', '[::1]', '::1']);

function parseBase(raw) {
  let url;
  try { url = new URL(String(raw)); } catch { throw new TaskError(500, 'Relay URL is not a valid URL.'); }
  if (!['http:', 'https:'].includes(url.protocol) || !LOOPBACK.has(url.hostname)) {
    throw new TaskError(500, 'Relay URL must be a loopback http(s) origin.');
  }
  return { origin: url.origin, base: url.pathname.replace(/\/+$/, '') };
}

/**
 * @param {object} options
 * @param {string} options.baseUrl   loopback origin of the live Relay, e.g. http://127.0.0.1:8787
 * @param {string} [options.token]   bearer token (the gate token)
 * @param {string} [options.tokenFile] file to read it from on first use
 * @param {Function} [options.fetchImpl] injectable for tests
 * @param {number} [options.timeoutMs]
 */
export async function createRelayHttpLink({ baseUrl, token, tokenFile, store, fetchImpl, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  const { origin, base } = parseBase(baseUrl);
  const doFetch = fetchImpl ?? globalThis.fetch;
  let cache = typeof token === 'string' && token ? token : null;

  async function bearer() {
    if (cache) return cache;
    if (!tokenFile) throw new TaskError(503, 'Relay gate token is not configured.');
    try {
      cache = (await readFile(tokenFile, 'utf8')).trim();
    } catch {
      throw new TaskError(503, 'Relay gate token could not be read.');
    }
    if (!cache) throw new TaskError(503, 'Relay gate token is empty.');
    return cache;
  }

  /** One bounded request. Returns { text, json } and never leaks the token into an error. */
  async function request(route, { method = 'GET', body, auth = true } = {}) {
    const headers = { ...(body ? { 'Content-Type': 'application/json' } : {}) };
    if (auth) headers.Authorization = `Bearer ${await bearer()}`;
    let response;
    try {
      response = await doFetch(`${origin}${base}${route}`, {
        method,
        redirect: 'manual',
        signal: AbortSignal.timeout(timeoutMs),
        headers,
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
    } catch {
      // A relay that is down is "unavailable", never "unauthorised" and never a stack.
      throw new TaskError(503, 'Live Relay is unreachable. Retry this step.');
    }
    if (response.redirected || (response.status >= 300 && response.status < 400)) {
      throw new TaskError(503, 'Live Relay tried to redirect; refused.');
    }
    const reader = response.body.getReader();
    const chunks = [];
    let size = 0;
    try {
      for (;;) {
        const part = await reader.read();
        if (part.done) break;
        size += part.value.length;
        if (size > MAX_BODY_BYTES) throw new TaskError(503, 'Live Relay response was too large.');
        chunks.push(part.value);
      }
    } finally {
      await reader.cancel().catch(() => {});
    }
    const text = Buffer.concat(chunks).toString('utf8');
    const type = response.headers.get('content-type') ?? '';
    return {
      status: response.status,
      ok: response.ok,
      text,
      json: /^application\/json(?:;|$)/i.test(type) ? JSON.parse(text) : undefined,
    };
  }

  /** Real Relay agents, normalised to the fields Mesh needs. Never invented. */
  async function agents() {
    const result = await request('/api/agents');
    if (!result.ok || !Array.isArray(result.json)) {
      throw new TaskError(503, 'Live Relay did not return an agent list.');
    }
    return result.json.map(agent => ({
      id: String(agent.id),
      name: String(agent.name ?? agent.id),
      backend: String(agent.backend ?? ''),
      device: String(agent.device ?? ''),
      status: String(agent.status ?? ''),
      conversation_id: agent.conversation_id ?? null,
      approval: agent.approval ?? null,
      budget: agent.budget ?? null,
    }));
  }

  /**
   * The Relay pane's snapshot. `conversationId` is the *primary* agent's active
   * conversation -- the pane can only send into one conversation at a time, and
   * pretending otherwise would mean inventing a "current" that Relay does not have.
   *
   * `links` is empty on purpose for now: the old child returned `meshTaskLinks` from
   * inside Relay, and the real Relay keeps no such index. The Workroom's own store is
   * the record (R8b writes it), so the pane must read links from there once that read
   * API exists -- returning an empty list is honest, returning a fabricated one would
   * not be.
   */
  async function snapshot() {
    try {
      const list = await agents();
      const withConversation = list.filter(a => a.conversation_id);
      const pinned = process.env.MESH_RELAY_AGENT
        ? list.find(a => a.id === process.env.MESH_RELAY_AGENT)
        : null;
      const primary = pinned ?? withConversation[0] ?? null;
      if (!primary?.conversation_id) {
        return {
          status: 'unavailable', agents: list, conversationId: null, links: [], pending: [],
          primaryAgentId: primary?.id ?? null,
          error: 'Live Relay is reachable but no agent has an active conversation yet. Send once from Relay, then reconnect.',
        };
      }
      return {
        status: 'fresh', agents: list, primaryAgentId: primary.id,
        conversationId: primary.conversation_id, links: [], pending: [], error: null,
      };
    } catch (error) {
      const reason = error instanceof TaskError ? error.message : 'Live Relay unavailable.';
      return { status: 'unavailable', agents: [], conversationId: null, links: [], pending: [], error: reason };
    }
  }

  return {
    mode: 'http',
    snapshot,
    agents,
    /** Read-only pass-through for the surfaces Mesh mirrors (auth status, sessions). */
    async nativeRead(route) {
      if (!route.startsWith('/')) throw new TaskError(400, 'A native read path must be absolute.');
      const result = await request(route);
      if (!result.ok) throw new TaskError(result.status === 401 ? 401 : 503, 'Live Relay refused the read.');
      return result.json ?? result.text;
    },
    async shell() {
      // `/` is outside Relay's gate (it has to render the unlock screen), so no token.
      const result = await request('/', { auth: false });
      if (!result.ok) throw new TaskError(503, 'Live Relay shell unavailable.');
      return result.text;
    },
    /**
     * Send one message and link it to a Workroom task (R8b).
     *
     * The old child asked *Mesh* to create the task over stdout after Relay had
     * accepted the message. Real Relay has no such callback, so the order is now
     * explicit here: Relay first, link second, and never the reverse. If Relay
     * refuses, no link is written. If Relay accepts but the link fails, the error
     * says the message was sent — the retry is safe because the message id is
     * stable and Relay dedupes it, but the operator must not be told a lie about
     * what happened.
     *
     * The agent is resolved from the conversation rather than assumed: the real
     * Relay has four agents, not one synthetic `mesh` agent.
     */
    async message(body, admitted) {
      const value = validateRelayMessage(body);
      if (!admitted()) throw new TaskError(403, 'Mesh admission expired.');
      let agent;
      try {
        agent = (await agents()).find(a => a.conversation_id === value.conversationId);
      } catch {
        throw new TaskError(503, 'Live Relay is unreachable, so the message was not sent.');
      }
      if (!agent) {
        throw new TaskError(409, 'That conversation is not active on any agent. Refresh Relay and retry.');
      }
      const result = await request(`/api/agents/${encodeURIComponent(agent.id)}/message`, {
        method: 'POST',
        body: { id: value.id, text: value.text, files: [] },
      });
      if (!result.ok) {
        const status = [400, 403, 409].includes(result.status) ? result.status : 503;
        throw new TaskError(status, 'Live Relay refused the message. Retry the same message id.');
      }
      if (result.json?.ok !== true) {
        throw new TaskError(503, 'Live Relay did not confirm the message.');
      }
      if (!store?.linkRelay) throw new TaskError(503, 'Workroom persistence unavailable, so nothing was sent.');
      let link;
      try {
        link = store.linkRelay({
          scope: 'relay:mesh', conversationId: value.conversationId,
          messageId: value.id, text: value.text,
        });
      } catch {
        throw new TaskError(503, 'Relay accepted the message but the Workroom link could not be written.');
      }
      if (!link?.taskId) {
        throw new TaskError(503, 'Relay accepted the message but no Workroom task was created.');
      }
      return {
        ok: true,
        conversationId: value.conversationId,
        messageId: value.id,
        agentId: agent.id,
        taskId: link.taskId,
        duplicate: Boolean(link.duplicate || result.json?.duplicate),
      };
    },
    async reconnect() {
      return snapshot();
    },
    async close() {
      cache = null;
    },
  };
}
