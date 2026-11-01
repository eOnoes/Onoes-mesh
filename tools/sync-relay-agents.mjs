// Snapshot Relay's agent list into public/agents.json.
//
// Why a snapshot and not a live proxy: Mesh's server refuses live connections on
// purpose - startApp throws 'Live connections are outside APP03.' - and that rule is
// older and stricter than this feature. So the app reads a static file and this tool
// refreshes it. tools/start-mesh.cmd runs it at logon, so it is current on every boot.
//
// The gate token is read here and never written anywhere. Only id/name/status/device/
// backend leave this process; feed text, usage and conversation ids stay in Relay.
import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ORIGIN = process.env.MESH_RELAY_ORIGIN ?? 'http://127.0.0.1:8787';
const KEY_FILE = process.env.RELAY_AUTH_KEY_FILE ?? 'D:/Dev/Onoes-Relay/.private/relay.key';
const OUT = path.join(ROOT, 'public', 'agents.json');

// Relay reports a free-text status; the reference draws a 7px dot per agent. Green means
// the agent is working or finished, blue means it is idle but reachable, grey means it is
// not running, red means it failed.
const DOT = {
  running: 'green', done: 'green', complete: 'green', ok: 'green',
  waiting: 'blue', idle: 'blue', ready: 'blue', connecting: 'blue',
  stopped: 'grey', offline: 'grey', unknown: 'grey',
  failed: 'red', error: 'red',
};

async function token() {
  if (process.env.RELAY_AUTH_TOKEN) return process.env.RELAY_AUTH_TOKEN.trim();
  try { return (await readFile(KEY_FILE, 'utf8')).trim(); } catch { return ''; }
}

async function main() {
  const key = await token();
  if (!key) {
    console.log('relay-agents: no gate token, leaving the snapshot untouched');
    return 0;
  }
  const res = await fetch(`${ORIGIN}/api/agents`, {
    headers: { Authorization: `Bearer ${key}` },
    signal: AbortSignal.timeout(8000),
  });
  if (!res.ok) {
    console.log(`relay-agents: Relay answered ${res.status}, leaving the snapshot untouched`);
    return 0;
  }
  const list = await res.json();
  const agents = (Array.isArray(list) ? list : []).map((a) => ({
    id: String(a.id ?? ''),
    name: String(a.name ?? a.id ?? ''),
    status: String(a.status ?? 'unknown'),
    device: String(a.device ?? ''),
    backend: String(a.backend ?? ''),
    dot: DOT[String(a.status ?? '').toLowerCase()] ?? 'grey',
  })).filter((a) => a.id);

  await writeFile(OUT, JSON.stringify({
    schema: 'mesh-relay-agents/v1',
    syncedAt: new Date().toISOString(),
    source: ORIGIN,
    agents,
  }, null, 2) + '\n', 'utf8');
  console.log(`relay-agents: wrote ${agents.length} agent(s) to public/agents.json`);
  return 0;
}

main().then((code) => process.exit(code)).catch((error) => {
  // Never fail the boot over a convenience snapshot.
  console.log(`relay-agents: ${error?.message ?? error}`);
  process.exit(0);
});
