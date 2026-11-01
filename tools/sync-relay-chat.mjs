// Snapshot a Relay conversation into public/chat.json.
//
// The Relay pane should show the real conversation, not placeholder copy. Mesh's server
// refuses live connections on purpose ('Live connections are outside APP03.'), so the
// app reads a snapshot and this tool refreshes it - the same arrangement as
// tools/sync-relay-agents.mjs.
//
// The gate token is read here and never written. Only the message text, who said it,
// when, and attachment NAMES leave this process.
import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ORIGIN = process.env.MESH_RELAY_ORIGIN ?? 'http://127.0.0.1:8787';
const KEY_FILE = process.env.RELAY_AUTH_KEY_FILE ?? 'D:/Dev/Onoes-Relay/.private/relay.key';
const OUT = path.join(ROOT, 'public', 'chat.json');
const AGENT = process.env.MESH_CHAT_AGENT ?? 'echo';
const LIMIT = 200;

async function token() {
  if (process.env.RELAY_AUTH_TOKEN) return process.env.RELAY_AUTH_TOKEN.trim();
  try { return (await readFile(KEY_FILE, 'utf8')).trim(); } catch { return ''; }
}

async function get(key, route) {
  const res = await fetch(`${ORIGIN}${route}`, {
    headers: { Authorization: `Bearer ${key}` },
    signal: AbortSignal.timeout(10000),
  });
  if (!res.ok) throw new Error(`${route} answered ${res.status}`);
  return res.json();
}

async function main() {
  const key = await token();
  if (!key) {
    console.log('relay-chat: no gate token, leaving the snapshot untouched');
    return 0;
  }

  const agents = await get(key, '/api/agents');
  const agent = (Array.isArray(agents) ? agents : []).find((a) => a.id === AGENT);
  if (!agent) {
    console.log(`relay-chat: agent ${AGENT} is not in Relay's list, leaving the snapshot untouched`);
    return 0;
  }
  const sessionId = String(agent.conversation_id ?? '');
  if (!sessionId) {
    console.log(`relay-chat: ${AGENT} has no conversation, leaving the snapshot untouched`);
    return 0;
  }

  const payload = await get(key, `/api/agents/${encodeURIComponent(AGENT)}/sessions/${encodeURIComponent(sessionId)}/messages`);
  const raw = Array.isArray(payload.messages) ? payload.messages : [];

  // Relay's shape is {id, k, t, attachments, created_at} with k in {you, ag}.
  const messages = raw.slice(-LIMIT).map((m) => ({
    id: String(m.id ?? ''),
    k: m.k === 'you' ? 'you' : 'ag',
    t: String(m.t ?? ''),
    at: String(m.created_at ?? ''),
    files: (Array.isArray(m.attachments) ? m.attachments : [])
      .map((f) => ({ name: String(f.name ?? ''), size: Number(f.size ?? 0) }))
      .filter((f) => f.name),
  })).filter((m) => m.t || m.files.length);

  await writeFile(OUT, JSON.stringify({
    schema: 'mesh-relay-chat/v1',
    syncedAt: new Date().toISOString(),
    source: ORIGIN,
    agent: { id: agent.id, name: agent.name ?? agent.id, status: agent.status ?? 'unknown' },
    sessionId,
    count: messages.length,
    messages,
  }, null, 2) + '\n', 'utf8');

  console.log(`relay-chat: wrote ${messages.length} message(s) for ${agent.name ?? AGENT}`);
  return 0;
}

main().then((code) => process.exit(code)).catch((error) => {
  console.log(`relay-chat: ${error?.message ?? error} (snapshot left as it was)`);
  process.exit(0);
});
