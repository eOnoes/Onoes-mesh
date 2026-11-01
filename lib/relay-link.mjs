import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';
import { mkdir, writeFile, access } from 'node:fs/promises';
import { randomUUID, randomBytes } from 'node:crypto';
import path from 'node:path';
import { TaskError } from './task-store.mjs';

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const ID = /^[A-Za-z0-9_-]{1,80}$/;
const exact = (v, keys) => v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v).sort().join(',') === keys.sort().join(',');
export function validateRelayMessage(body) {
  if (!exact(body, ['id','text','conversationId','meshIntent']) || typeof body.id !== 'string' || !ID.test(body.id) || typeof body.conversationId !== 'string' || !UUID.test(body.conversationId) ||
      body.meshIntent !== 'create_task' || typeof body.text !== 'string' || !body.text.trim() || body.text.length > 4000 || body.text.includes('\0'))
    throw new TaskError(400, 'Provide a stable message id, current Relay conversation, text and explicit create_task intent.');
  return { id: body.id, text: body.text, conversationId: body.conversationId, meshIntent: 'create_task' };
}

// The server owns the runtime, pipe, destination, config and stores. HTTP never
// accepts any path, credential, URL, command, proposal or execution state.
export async function createRelayLink({ root, directory, confine, store, enabled = false }) {
  let child, origin, capability, unavailable = 'not_configured', startup;
  const intents = new Map();
  const source = await confine(path.join(root, 'service_roots', 'relay'));
  const runtimeDir = await confine(path.join(directory, 'relay'));
  const script = await confine(path.join(source, 'mesh_runtime.py'));
  const filename = await confine(path.join(runtimeDir, 'relay.sqlite'));
  const configPath = await confine(path.join(runtimeDir, 'isolated-config.json'));
  const python = 'C:\\Python314\\python.exe';
  const sitePackages = path.join(root, 'test', 'app03-m4-link-runtime', 'Lib', 'site-packages');
  const state = (status = unavailable) => ({ status, conversationId: null, links: [], error: status === 'unavailable' ? 'Actual isolated Relay unavailable; verify local Python dependencies or reconnect.' : null });
  async function stop() {
    const owned = child; child = undefined; origin = undefined; intents.clear();
    if (!owned) return;
    const exited = new Promise(resolve => { if (owned.exitCode !== null || owned.signalCode !== null) resolve(); else owned.once('exit', resolve); });
    owned.stdin.end();
    const timer = setTimeout(() => owned.kill(), 1500);
    await exited; clearTimeout(timer);
    console.log(JSON.stringify({ event: 'mesh_relay_stopped', pid: owned.pid, exitCode: owned.exitCode, signal: owned.signalCode }));
  }
  async function boot() {
    if (!enabled) return;
    unavailable = 'unavailable';
    try {
      await mkdir(runtimeDir, { recursive: true });
      await writeFile(configPath, JSON.stringify({ mesh_only: true, debug: false, agents: { mesh: { name: 'Mesh Workroom', backend: 'mesh', demo_fallback: false } } }));
      const dependencies = await confine(sitePackages);
      await access(dependencies);
      capability = randomBytes(32).toString('base64url');
      // Windows venv python.exe redirects to a second PID. Launch the fixed
      // native base directly so the listener is the owned ChildProcess. -I -S
      // excludes ambient/user/global imports and .pth startup hooks; only this
      // confined dependency directory and copied Relay source are added.
      const owned = spawn(python, ['-I', '-S', '-B', '-c', `import sys; sys.path[:0]=[${JSON.stringify(source)},${JSON.stringify(dependencies)}]; import mesh_runtime`], {
        cwd: runtimeDir, windowsHide: true, stdio: ['pipe','pipe','pipe'],
        env: { SystemRoot: process.env.SystemRoot, TEMP: runtimeDir, TMP: runtimeDir,
          RELAY_CONFIG_PATH: configPath, RELAY_SESSION_DB: filename, MESH_RELAY_CAPABILITY: capability }
      });
      child = owned;
      console.log(JSON.stringify({ event: 'mesh_relay_spawned', pid: owned.pid, executable: python }));
      // Only code-level diagnostics are surfaced; upstream bodies/credentials are never logged.
      owned.stderr.resume(); owned.stdin.on('error', () => {});
      const lines = createInterface({ input: owned.stdout });
      await new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(Error('Relay startup deadline')), 5000);
        const failed = () => { clearTimeout(timer); reject(Error('Relay runtime unavailable')); };
        owned.once('error', failed); owned.once('exit', failed);
        lines.on('line', line => {
          if (line.length > 40000 || child !== owned) return;
          let value; try { value = JSON.parse(line); } catch { return; }
          if (value.event === 'mesh_relay_listening' && value.pid === owned.pid && Number.isInteger(value.port) && value.port > 0 && value.port <= 65535) {
            origin = `http://127.0.0.1:${value.port}`; unavailable = 'fresh'; clearTimeout(timer);
            console.log(JSON.stringify({ event: 'mesh_relay_listening', pid: owned.pid, port: value.port }));
            resolve(); return;
          }
          if (value.event === 'mesh_relay_recover' && UUID.test(value.rpcId) && UUID.test(value.conversationId) && ID.test(value.messageId)) {
            // Read-only recovery may restore a reference, never create a task.
            let taskId = null;
            try { taskId = store?.relayReference({ scope:'relay:mesh',conversationId:value.conversationId,messageId:value.messageId }) ?? null; } catch { /* No fabricated reference. */ }
            owned.stdin.write(JSON.stringify({rpcId:value.rpcId,ok:true,taskId})+'\n');
            return;
          }
          if (value.event !== 'mesh_relay_link' || !UUID.test(value.rpcId) || !UUID.test(value.intent)) return;
          const intent = intents.get(value.intent);
          let result = { ok: false, status: 403, error: 'Mesh message intent is no longer admitted.' };
          if (intent && !intent.used && intent.admitted() && value.conversationId === intent.body.conversationId && value.messageId === intent.body.id && value.text === intent.body.text) {
            intent.used = true;
            try {
              if (!store) throw new TaskError(503, 'Workroom persistence unavailable.');
              result = { ok: true, ...store.linkRelay({ scope: 'relay:mesh', conversationId: value.conversationId, messageId: value.messageId, text: value.text }) };
              console.log(JSON.stringify({ event: 'mesh_relay_task_linked', conversationId: value.conversationId, messageId: value.messageId, taskId: result.taskId, duplicate: result.duplicate }));
            } catch (error) { result = { ok: false, status: error instanceof TaskError ? error.status : 503, error: 'Canonical Workroom link refused or unavailable.' }; }
          }
          owned.stdin.write(JSON.stringify({ rpcId: value.rpcId, ...result }) + '\n');
        });
      });
      owned.once('exit', () => { if (child === owned) { origin = undefined; unavailable = 'unavailable'; } });
    } catch {
      await stop();
      console.log(JSON.stringify({ event: 'mesh_relay_unavailable', reason: 'runtime_or_dependency_setup' }));
    }
  }
  async function request(route, { body, intent } = {}) {
    if (!origin) throw new TaskError(503, state().error ?? 'Relay is not configured.');
    const target = origin;
    try {
      const response = await fetch(target + route, { method: body ? 'POST' : 'GET', redirect: 'manual', signal: AbortSignal.timeout(4000),
        headers: { Origin: target, Authorization: `Bearer ${capability}`, ...(body ? { 'Content-Type': 'application/json', 'X-Mesh-Intent': intent } : {}) },
        ...(body ? { body: JSON.stringify(body) } : {}) });
      if (response.redirected || response.status >= 300 && response.status < 400) throw Error('Relay redirect refused');
      const reader = response.body.getReader(); const chunks = []; let size = 0;
      try { for (;;) { const part = await reader.read(); if (part.done) break; size += part.value.length; if (size > 262144) throw Error('Relay response too large'); chunks.push(part.value); } }
      finally { await reader.cancel(); }
      const text = Buffer.concat(chunks).toString('utf8');
      if (!response.ok) throw new TaskError([400,403,409].includes(response.status) ? response.status : 503, 'Actual Relay message refused or unavailable. Retry the same message id.');
      if (route === '/') return text;
      if (!/^application\/json(?:;|$)/i.test(response.headers.get('content-type') ?? '')) throw Error('Invalid Relay response');
      return JSON.parse(text);
    } catch (error) {
      if (error instanceof TaskError) throw error;
      throw new TaskError(503, 'Actual Relay unreachable or returned an invalid response. Retry the same message id.');
    }
  }
  async function snapshot() {
    if (!origin) return state();
    try {
      const agents = await request('/api/agents');
      if (!Array.isArray(agents) || agents.length !== 1 || agents[0].id !== 'mesh' || agents[0].backend !== 'mesh' || !UUID.test(agents[0].conversation_id) || !Array.isArray(agents[0].meshTaskLinks)) throw Error('Invalid Relay snapshot');
      const links = agents[0].meshTaskLinks.map(r => {
        if (r.conversation_id !== agents[0].conversation_id || !ID.test(r.message_id) || !UUID.test(r.task_id) || !store?.get(r.task_id)) throw Error('Unresolved canonical reference');
        return { messageId: r.message_id, taskId: r.task_id };
      });
      const pending = agents[0].meshPendingLinks;
      if (!Array.isArray(pending) || pending.some(id=>!ID.test(id))) throw Error('Invalid pending Relay identities');
      return { status: 'fresh', conversationId: agents[0].conversation_id, links, pending, error: null };
    } catch { return state('unavailable'); }
  }
  async function message(body, admitted) {
    const value = validateRelayMessage(body);
    const intent = randomUUID(); intents.set(intent, { body: value, admitted, used: false });
    try {
      if (!admitted()) throw new TaskError(403, 'Mesh admission expired.');
      const result = await request('/api/agents/mesh/message', { body: value, intent });
      if (result?.ok !== true || result.conversationId !== value.conversationId || result.messageId !== value.id || !UUID.test(result.taskId) || !store?.get(result.taskId)) throw new TaskError(503, 'Relay returned an unresolved canonical reference.');
      return result;
    } finally { intents.delete(intent); }
  }
  async function reconnect() {
    if (startup) return startup;
    startup = (async () => { await stop(); await boot(); return snapshot(); })();
    try { return await startup; } finally { startup = undefined; }
  }
  if (enabled) await boot();
  return { snapshot, message, reconnect, shell: () => request('/'), agents: () => request('/api/agents'),
    nativeRead: route => request(route), close: stop };
}
