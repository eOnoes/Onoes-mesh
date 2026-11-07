import { tailscaleAccess } from './lib/tailscale-access.mjs';
import {requestAudit,auditReason} from './lib/request-audit.mjs';
// Mesh's serving layer: the app, a shared-token gate, and the two live connections.
//
// Why this file exists separately from test/m1-serve.mjs:
//   * startApp() refuses live connections by contract ("Live connections are outside
//     APP03"), so nothing here goes inside it.
//   * test/m1-serve.test.mjs tests that adapter, so extending it would drag the gate
//     into those tests. This is a second adapter with a different job.
//
// Shape:
//
//   /                 the app's static shell and its own /api/* (proxied, gated)
//   /relay/*          Relay's API, with the gate token attached server-side
//   /inference/*      live telemetry: Strata's API, nvidia-smi, the OS
//
// The gate copies relay_auth.py exactly: one shared secret, presented either as
// `Authorization: Bearer <token>` (scripts) or exchanged once per device for an
// HttpOnly cookie holding a SHA-256 digest bound to the token - never the token itself.
import http from 'node:http';
import { readFileSync, existsSync } from 'node:fs';
import { createHash, timingSafeEqual } from 'node:crypto';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { startApp } from './server.mjs';
import {createSupervisorObservation} from './lib/supervisor-observation.mjs';
import {supervisorControlView} from './public/control-models.mjs';

const run = promisify(execFile);

const PREVIEW_PORT = Number(process.env.MESH_PREVIEW_PORT ?? 4317);
const DATA_DIR = process.env.MESH_DATA_DIR ?? 'test/app03-mesh';
const RELAY_ORIGIN = process.env.MESH_RELAY_ORIGIN ?? 'http://127.0.0.1:8787';
// Supervised ports first (18090 Flash-Next, 18091 Qwen3.6, 8098 the llama.cpp exception),
// then the ad-hoc ports a hand-launched engine might use.
const STRATA_PORTS = [18095, 18090, 18091, 8098, 60409, 8080, 1234, 8000];
const supervisorObservationEnabled=process.env.MESH_STANDALONE!=='1'&&process.env.MESH_MODEL_OBSERVATION==='1';
const readSupervisorModels=createSupervisorObservation({enabled:supervisorObservationEnabled});
const KEY_FILE = process.env.MESH_GATE_KEY_FILE ?? 'D:/Dev/Onoes-Relay/.private/relay.key';
const COOKIE_NAME = 'mesh_session';
const COOKIE_MAX_AGE = 60 * 60 * 24 * 180;

function gateToken() {
  if (process.env.MESH_GATE_TOKEN) return process.env.MESH_GATE_TOKEN.trim();
  try { return readFileSync(KEY_FILE, 'utf8').trim(); } catch { return ''; }
}

const sha256 = (text) => createHash('sha256').update(text).digest('hex');
const cookieValue = (token) => sha256(`mesh-cookie:${token}`);

function safeEqual(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || !a || !b) return false;
  const x = Buffer.from(a);
  const y = Buffer.from(b);
  if (x.length !== y.length) return false;
  return timingSafeEqual(x, y);
}

function cookieFrom(header) {
  for (const chunk of String(header || '').split(';')) {
    const [name, ...rest] = chunk.trim().split('=');
    if (name === COOKIE_NAME) return rest.join('=');
  }
  return '';
}

function bearerFrom(header) {
  const [scheme, ...rest] = String(header || '').split(/\s+/);
  return scheme && scheme.toLowerCase() === 'bearer' ? rest.join(' ') : '';
}

function authed(req, token) {
  if(tailscaleAccess(req,{login:process.env.MESH_TAILSCALE_LOGIN,host:process.env.MESH_TAILSCALE_HOST}))return true;
  if (!token) return false;
  return safeEqual(bearerFrom(req.headers.authorization), token)
      || safeEqual(cookieFrom(req.headers.cookie), cookieValue(token));
}

function send(res, status, body, headers = {}) {
  res.writeHead(status, { 'Cache-Control': 'no-store', ...headers });
  res.end(body);
}

function sendJson(res, status, value) {
  send(res, status, JSON.stringify(value), { 'Content-Type': 'application/json; charset=utf-8' });
}

const GATE_PAGE = `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>mesh</title>
<style>
:root{color-scheme:dark;--bg:#0d0d0f;--surface:#161618;--raised:#1d1d20;--border:#2a2a2e;
--ink:#e8e8ea;--muted:#b9b9bf;--quiet:#8a8a92;--faint:#5b5b63;--cyan:#4fd8e8}
*{box-sizing:border-box}
body{margin:0;min-height:100dvh;display:grid;place-items:center;background:var(--bg);color:var(--ink);
font:13px/19px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
form{width:min(92vw,380px);padding:18px;border:1px solid var(--border);border-radius:8px;background:var(--surface)}
.k{display:block;color:var(--quiet);font-size:10px;letter-spacing:.09em;text-transform:uppercase;margin-bottom:10px}
.prompt{color:var(--faint)}
input{width:100%;padding:9px 10px;border:1px solid var(--border);border-radius:6px;background:var(--bg);
color:var(--ink);font:inherit;margin-bottom:10px}
input:focus{outline:none;border-color:var(--cyan)}
button{width:100%;padding:9px;border:1px solid var(--border);border-radius:6px;background:var(--raised);
color:var(--ink);font:inherit;cursor:pointer}
button:hover{border-color:var(--faint)}
.err{color:#e06a5f;font-size:11px;margin-top:8px}
.foot{color:var(--faint);font-size:10px;margin-top:12px}
</style></head>
<body><form method="post" action="/unlock">
<span class="k">mesh · unlock</span>
<label class="prompt" for="token">~ $ unlock --token</label>
<input id="token" name="token" type="password" autocomplete="current-password" autofocus
 placeholder="paste the shared key" required>
<button type="submit">unlock</button>
<div class="foot">one shared secret · held once per device · 180 days</div>
</form></body></html>`;

// Ask the app to admit this browser. The gate and the app keep separate cookies on
// purpose: the gate proves you hold the shared key, the app's trial session proves it
// minted an admission. Performing both here means one unlock, not two.
async function appAdmission() {
  try {
    const res = await fetch(`${app.url}/api/trial-session/bootstrap`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', origin: app.url },
      body: '{}',
      signal: AbortSignal.timeout(8000),
    });
    const cookies = typeof res.headers.getSetCookie === 'function' ? res.headers.getSetCookie() : [];
    return { ok: res.ok, status: res.status, cookies };
  } catch (error) {
    return { ok: false, status: 0, cookies: [], error: String(error?.message ?? error) };
  }
}

// --- Live telemetry -----------------------------------------------------------------
// One short-timeout probe helper. Every service below is optional: a dead port must cost
// a timeout, never an exception, so the summary always renders.
async function probeJson(url, timeout = 1200) {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(timeout) });
    if (!res.ok) return null;
    return await res.json();
  } catch { return null; }
}

async function ollamaStatus() {
  const version = await probeJson('http://127.0.0.1:11434/api/version');
  if (!version?.version) return { reachable: false, detail: null, loadedCount: 0, libraryCount: 0, models: [] };
  const [ps, tags] = await Promise.all([
    probeJson('http://127.0.0.1:11434/api/ps'),
    probeJson('http://127.0.0.1:11434/api/tags'),
  ]);
  const loaded = Array.isArray(ps?.models) ? ps.models : [];
  const library = Array.isArray(tags?.models) ? tags.models : [];
  return {
    reachable: true,
    detail: `v${version.version}`,
    loadedCount: Array.isArray(ps?.models)?loaded.length:null,
    residencyKnown:Array.isArray(ps?.models),
    libraryCount: library.length,
    models: loaded.map((m) => ({
      name: String(m.name ?? ''),residency:'reported_loaded',
      vramGB: m.size_vram ? Math.round((m.size_vram / 1e9) * 100) / 100 : null,
    })),
  };
}

async function lmStudioStatus() {
  const models = await probeJson('http://127.0.0.1:1234/v1/models');
  const list = Array.isArray(models?.data) ? models.data : [];
  return {
    reachable: Boolean(models),
    detail: models ? `${list.length} listed` : null,
    loadedCount: list.length,
    libraryCount: list.length,
    residencyKnown:false,
    models: list.slice(0, 8).map((m) => ({ name: String(m.id ?? ''),residency:'listed' })),
  };
}

async function comfyStatus() {
  const stats = await probeJson('http://127.0.0.1:8188/system_stats', 1500);
  if (!stats) return { reachable: false, detail: null, busy: null, queued: null };
  const device = Array.isArray(stats.devices) ? stats.devices[0] : null;
  return {
    reachable: true,
    detail: device ? `${device.name ?? 'device'} · ${Math.round((device.vram_total ?? 0) / 1e9)} GB` : null,
    busy: stats.execution_start != null,
    queued: stats.queue_remaining ?? null,
  };
}

async function strataHealth() {
  for (const port of STRATA_PORTS) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/health`, { signal: AbortSignal.timeout(1500) });
      if (!res.ok) continue;
      const health = await res.json();
      if (!health || !health.status) continue;
      // The supervisor answers /health on these ports while serving nothing:
      // {"status":"idle","servable":false,"detail":"ENGINE_NOT_BUILT…"}. Treating that as
      // an engine would report a model that is not loaded, so require a real answer.
      const servable = health.servable === true
        || health.loaded === true
        || ['ok', 'loaded', 'ready', 'busy'].includes(String(health.status).toLowerCase());
      if (!servable || health.servable === false) continue;
      const props = await fetch(`http://127.0.0.1:${port}/props`, { signal: AbortSignal.timeout(1500) })
        .then((r) => (r.ok ? r.json() : null)).catch(() => null);
            // The supervisor's /health omits max_context, so ask /v1/models as well - without
      // it the Control pane shows a blank context on a loaded model.
      const models = await fetch(`http://127.0.0.1:${port}/v1/models`, { signal: AbortSignal.timeout(1500) })
        .then((r) => (r.ok ? r.json() : null)).catch(() => null);
      return { port, health, props, models };
    } catch { /* try the next port */ }
  }
  return null;
}

let summaryCache = null;

async function inferenceSummary() {
  // One PowerShell pass for everything the OS knows, one nvidia-smi call for the card,
  // and the service probes in parallel. Four separate PowerShell launches took ~2s; this
  // takes ~300ms.
  // A single string, NOT joined lines: joining with '; ' turns `[pscustomobject]@{` into
  // `[pscustomobject]@{;`, which PowerShell rejects as an incomplete hash literal.
  const psScript = `
$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$disks = @(Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Used -ne $null } | ForEach-Object { [pscustomobject]@{ name=$_.Name+':'; usedGB=[math]::Round($_.Used/1GB,1); freeGB=[math]::Round($_.Free/1GB,1); totalGB=[math]::Round(($_.Used+$_.Free)/1GB,1) } })
[pscustomobject]@{
  os=$os.Caption; osVersion=$os.Version
  uptimeSec=[int]((Get-Date)-$os.LastBootUpTime).TotalSeconds
  cpuName=$cpu.Name; cpuCores=$cpu.NumberOfCores; cpuThreads=$cpu.NumberOfLogicalProcessors; cpuLoad=$cpu.LoadPercentage
  ramTotalGB=[math]::Round($os.TotalVisibleMemorySize/1MB,1); ramFreeGB=[math]::Round($os.FreePhysicalMemory/1MB,1)
  disks=$disks
} | ConvertTo-Json -Depth 5 -Compress`;

  const [psOut, gpuOut, strata, ollama, lmstudio, comfyui,modelObservation] = await Promise.all([
    run('powershell', ['-NoProfile', '-NonInteractive', '-Command', psScript], { timeout: 8000, windowsHide: true })
      .then((r) => { try { return JSON.parse(r.stdout.trim()); } catch { return null; } }).catch(() => null),
    run('nvidia-smi', ['--query-gpu=name,memory.used,memory.total,utilization.gpu,power.draw,power.limit,temperature.gpu,fan.speed,clocks.current.graphics,clocks.current.memory',
      '--format=csv,noheader,nounits'], { timeout: 5000, windowsHide: true }).then((r) => r.stdout.trim()).catch(() => ''),
    supervisorObservationEnabled?Promise.resolve(null):strataHealth(),
    ollamaStatus(),
    lmStudioStatus(),
    comfyStatus(),
    readSupervisorModels(),
  ]);

  let gpu = null;
  if (gpuOut) {
    const f = gpuOut.split(',').map((x) => x.trim());
    const used = Number(f[1]); const total = Number(f[2]);
    gpu = {
      name: f[0], vramUsedMiB: used, vramTotalMiB: total,
      vramPct: total > 0 ? Math.round((1000 * used) / total) / 10 : null,
      utilPct: Number(f[3]), powerW: Number(f[4]), powerLimitW: Number(f[5]), tempC: Number(f[6]),
      fanPct: Number.isFinite(Number(f[7])) ? Number(f[7]) : null,
      clockMHz: Number.isFinite(Number(f[8])) ? Number(f[8]) : null,
      memClockMHz: Number.isFinite(Number(f[9])) ? Number(f[9]) : null,
    };
  }

  const ram = { usedPct: null, usedGB: null, totalGB: null };
  if (psOut && psOut.ramTotalGB) {
    ram.totalGB = psOut.ramTotalGB;
    ram.usedGB = Math.round((psOut.ramTotalGB - psOut.ramFreeGB) * 10) / 10;
    ram.usedPct = Math.round((1000 * ram.usedGB) / psOut.ramTotalGB) / 10;
  }

  const disks = Array.isArray(psOut?.disks)
    ? psOut.disks.map((d) => ({ name: d.name, usedGB: d.usedGB, totalGB: d.totalGB,
        usedPct: d.totalGB > 0 ? Math.round((1000 * d.usedGB) / d.totalGB) / 10 : null }))
    : [];

  const system = psOut ? {
    os: psOut.os, osVersion: psOut.osVersion,
    uptimeSec: psOut.uptimeSec,
    cpuName: psOut.cpuName, cpuCores: psOut.cpuCores, cpuThreads: psOut.cpuThreads,
    cpuLoadPct: psOut.cpuLoad ?? null,
    node: process.version,
  } : null;

  // Services the other control panel tracks, so Mesh can report reachability the same way.
  const supervised=supervisorObservationEnabled?supervisorControlView(modelObservation):null;
  const services = [supervised?supervised.service:strata ? {
    id: 'strata', label: 'UnbiasedStrata', base: `127.0.0.1:${strata.port}`,
    reachable: true, loaded: strata.health.loaded === true,
    detail: strata.health.model ?? null,
  } : { id: 'strata', label: 'UnbiasedStrata', base: 'ports 18090-18095', reachable: false, loaded: false, detail: null },
    { id: 'ollama', label: 'Ollama', base: '127.0.0.1:11434', ...ollama },
    { id: 'lmstudio', label: 'LM Studio', base: '127.0.0.1:1234', ...lmstudio },
    { id: 'comfyui', label: 'ComfyUI', base: '127.0.0.1:8188', ...comfyui }];

  const hints = [];
  if(supervised)hints.push(...supervised.hints);
  else if (!strata) hints.push('No inference engine answered. Model status is unavailable.');
  if (ollama.reachable && ollama.loadedCount === 0) hints.push('Ollama is up with no resident models.');
  if (!ollama.reachable) hints.push('Ollama is not answering on 11434.');
  if (!lmstudio.reachable) hints.push('LM Studio is not answering on 1234.');
  if (!comfyui.reachable) hints.push('ComfyUI is not answering on 8188.');
  if (gpu && gpu.vramPct >= 90) hints.push('VRAM is above 90% - a new load will have to evict.');
  if (psOut && psOut.cpuLoad >= 85) hints.push('CPU is above 85%; prompt processing will be slow.');

  return {
    schema: 'mesh-inference/live-v2',
    generatedAt: new Date().toISOString(),
    host: process.env.MESH_HOST_LABEL ?? "Echo's PC",
    platform: `${process.platform} ${process.arch}`,
    ...(supervisorObservationEnabled?{modelObservation}:{}),
    engine: supervised?supervised.engine:strata ? {
      name: strata.props?.engine ?? 'strata',
      port: strata.port,
      loaded: strata.health.loaded ?? null,
      busy: strata.health.busy ?? null,
      modelAlias: strata.health.model ?? strata.props?.model_alias ?? null,
      modelShort: shortModel(strata.health.model ?? strata.props?.model_alias),
      modelPath: strata.props?.model_path ?? null,
      contextMax: strata.health.max_context ?? strata.props?.default_generation_settings?.n_ctx ?? strata.models?.data?.[0]?.context_length ?? null,
      buildInfo: strata.props?.build_info ?? null,
      state: engineState(strata),
    } : null,
    gpu, ram, disks, system, services, hints,
    throughput: { tps: null, pps: null, contextUsed: null, contextPct: null,
      reason: supervised?'Throughput counters are not provided by the model supervisor.':strata ? (strata.health.busy ? 'generating - no counter exposed by this build' : 'engine is idle')
                    : 'no engine answered on the usual ports' },
    cost: { simulatedUsd: null, reason: 'needs a token stream; run the engine behind a proxy' },
  };
}

// One word for what the engine is doing. The supervisor reports loaded but not busy, so
// "loaded with no busy signal" is stated as loaded rather than guessed as idle.
function engineState(found) {
  if (!found) return 'stopped';
  const busy = found.health.busy;
  if (busy === true) return 'busy';
  if (busy === false) return 'idle';
  return found.health.loaded === true ? 'loaded' : 'unknown';
}

function shortModel(name) {
  if (!name) return null;
  // Shorten a gguf fragment ("JoyFox-Qwen3.6-35B-A3B-...-Q5_K_M" -> "JoyFox 35B-A3B Q5_K_M").
  // An alias like "qwen3.8-flash-next-iq3-s" carries no size or quant token, so it is
  // already as short as it gets - return it untouched instead of gluing its first
  // fragment on the front.
  const size = name.match(/(\d+(?:\.\d+)?B-A\d+B)/)?.[1] ?? name.match(/(\d+(?:\.\d+)?B)/)?.[1] ?? '';
  const quant = name.match(/(Q\d[_A-Za-z0-9]*)/)?.[1] ?? '';
  if (!size && !quant) return name;
  return [name.split(/[-_.]/)[0], size, quant].filter(Boolean).join(' ');
}

// --- Relay proxy --------------------------------------------------------------------
async function relayProxy(req, res, token, path) {
  const url = `${RELAY_ORIGIN}${path}`;
  const headers = { Authorization: `Bearer ${token}` };
  if (req.headers['content-type']) headers['Content-Type'] = req.headers['content-type'];
  const body = ['POST', 'PUT', 'PATCH'].includes(req.method) ? await readBody(req) : undefined;
  try {
    const upstream = await fetch(url, { method: req.method, headers, body, signal: AbortSignal.timeout(20000) });
    const text = await upstream.text();
    res.writeHead(upstream.status, {
      'Content-Type': upstream.headers.get('content-type') ?? 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
    });
    res.end(text);
  } catch (error) {
    sendJson(res, 502, { ok: false, error: `relay unreachable: ${error?.message ?? error}` });
  }
}

function readBody(req, limit = 1_000_000) {
  return new Promise((resolve, reject) => {
    let size = 0; const chunks = [];
    req.on('data', (c) => {
      size += c.length;
      if (size > limit) { reject(new Error('body too large')); req.destroy(); return; }
      chunks.push(c);
    });
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}

// --- Server --------------------------------------------------------------------------
const token = gateToken();
// A working session, not a five-minute demo one: the operator was being logged out
// mid-thought, which disabled the whole UI including the Relay prompt. The cookie's
// Max-Age is derived from this TTL, so raising one raises both.
const SESSION_TTL_MS = 12 * 60 * 60 * 1000;
const app = await startApp({ dataDir: DATA_DIR, sessionTtlMs: SESSION_TTL_MS });
const backend = new URL(app.url);

const server = http.createServer(async (req, res) => {
  // A denial with no reason is undebuggable. The operator hit a bare "forbidden"
  // twice; this records which check refused, and the headers that decided it, with
  // no token or cookie value ever written.
  const deny = (reason) => {
    req.resume();
    try {
      console.log(JSON.stringify({
        event: 'gate_denied', reason:auditReason(reason), ...requestAudit(req), at: new Date().toISOString(),
      }));
    } catch { /* logging must never break a response */ }
    send(res, 403, 'forbidden');
  };
  const scheme = req.headers['x-forwarded-proto'] === 'https' ? 'https' : 'http';
  const externalOrigin = `${scheme}://${req.headers.host}`;
  // Same-origin check. `tailscale serve` terminates TLS and forwards with Host
  // rewritten to 127.0.0.1:4317 while the browser's Origin stays
  // https://<name>.ts.net:8446, so comparing Origin against the raw Host 403'd every
  // POST from the tailnet — and every RELOAD, which re-sends Origin on a navigation.
  // That is why the app loaded once and then said "forbidden".
  //
  // The browser's own `Sec-Fetch-Site` is the better signal: page script cannot set
  // it, and a cross-site request is marked `cross-site`. When it is absent (curl, an
  // older client), fall back to comparing by host against Host / X-Forwarded-Host /
  // MESH_EXTERNAL_HOST — which still refuses a foreign origin.
  const hostOf = value => {
    try { return new URL(value).host.toLowerCase(); } catch { return ''; }
  };
  const forwardedHost = String(req.headers['x-forwarded-host'] || '').split(',')[0].trim().toLowerCase();
  const allowedHosts = new Set(
    [String(req.headers.host || '').toLowerCase(), forwardedHost,
      String(process.env.MESH_EXTERNAL_HOST || '').toLowerCase()].filter(Boolean),
  );
  const secFetchSite = req.headers['sec-fetch-site'];
  // A link from another app may navigate to the shell. It cannot perform a
  // mutation or read an API response. Authentication is still checked below.
  const entryNavigation = req.method === 'GET' && req.url === '/' &&
    req.headers['sec-fetch-mode'] === 'navigate' && req.headers['sec-fetch-dest'] === 'document' &&
    !req.headers.origin;
  if (secFetchSite && !['same-origin', 'none'].includes(secFetchSite) && !entryNavigation) return deny('sec-fetch-site:' + secFetchSite);
  if (req.headers.origin && secFetchSite !== 'same-origin') {
    const originHost = hostOf(req.headers.origin);
    if (!originHost || !allowedHosts.has(originHost)) return deny('origin-host:' + (originHost || 'unparseable'));
  }
  if (!req.url.startsWith('/') || req.url.startsWith('//')) return deny('url-shape');

  const url = new URL(req.url, externalOrigin);
  const path = url.pathname;

  // unlock / lock are the only unauthenticated writes
  if (path === '/unlock' && req.method === 'POST') {
    const body = (await readBody(req).catch(() => Buffer.alloc(0))).toString('utf8');
    const presented = new URLSearchParams(body).get('token') ?? '';
    if (!token) return send(res, 500, 'no gate token configured on this machine');
    if (!safeEqual(presented.trim(), token)) {
      return send(res, 401, GATE_PAGE.replace('<div class="foot">', '<div class="err">that key does not match</div><div class="foot">'),
        { 'Content-Type': 'text/html; charset=utf-8' });
    }
    const secure = scheme === 'https' ? '; Secure' : '';
    // The app mints its own trial session from its own Start handler. Creating one here
    // too meant two bootstrap attempts per unlock and a 403 on the second. `mesh_gate` is
    // readable by the page (not HttpOnly) purely so the client knows the gate is real and
    // may start the session itself.
    const cookies = [
      `${COOKIE_NAME}=${cookieValue(token)}; Path=/; HttpOnly; SameSite=Lax; Max-Age=${COOKIE_MAX_AGE}${secure}`,
      `mesh_gate=1; Path=/; SameSite=Lax; Max-Age=${COOKIE_MAX_AGE}${secure}`,
    ];
    console.log(JSON.stringify({ event: 'unlock', cookies: cookies.length }));
    return send(res, 303, '', { Location: '/#unlock', 'Set-Cookie': cookies });
  }
  if (path === '/lock' && req.method === 'POST') {
    return send(res, 303, '', { Location: '/', 'Set-Cookie': [
      `${COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0`,
      `mesh_gate=; Path=/; SameSite=Lax; Max-Age=0`,
    ] });
  }

  // everything else needs the key
    // A browser on this PC reaches the app directly on loopback, so it is already behind the
  // keyboard that owns it. Tailscale preserves Host, so a tailnet visitor arrives with the
  // ts.net name and still gets the unlock page: the PC stays frictionless without reopening
  // the tailnet hole.
  const hostHeader = String(req.headers.host || '').toLowerCase();
  const localHost = /^(127\.0\.0\.1|localhost)(:\d+)?$/.test(hostHeader);
  if (!localHost && !authed(req, token)) {
    // A page gets the unlock form; anything API-shaped gets a plain 401 so the client can
    // react to it. Returning HTML to a fetch() would parse as garbage.
    const wantsJson = path.startsWith('/api/') || path.startsWith('/relay/') || path.startsWith('/inference/')
      || String(req.headers.accept || '').includes('application/json');
    if (wantsJson || req.method !== 'GET') {
      req.resume();
      return sendJson(res, 401, { ok: false, error: 'locked', unlock: '/unlock' });
    }
    return send(res, 200, GATE_PAGE, { 'Content-Type': 'text/html; charset=utf-8' });
  }

  // The client asks this to learn whether it is behind the gate adapter at all; a plain
  // m1-serve fixture has no such route, so browser tests keep their locked-board behaviour.
  if (path === '/gate/status') {
    if(req.method!=='GET')return sendJson(res,405,{error:'Method not allowed'});
    return sendJson(res, 200, { local: localHost, gated: authed(req, token), automaticSession: tailscaleAccess(req,{login:process.env.MESH_TAILSCALE_LOGIN,host:process.env.MESH_TAILSCALE_HOST}) });
  }

  if (path.startsWith('/relay/')) return relayProxy(req, res, token, path.slice('/relay'.length) + url.search);
    // The collector costs ~1.7s (one PowerShell launch + nvidia-smi + four probes). Every
  // panel polls every 5s, so two open tabs would double that for identical numbers.
  if (path === '/inference/summary') {
    if (summaryCache && Date.now() - summaryCache.at < 2000) return sendJson(res, 200, summaryCache.value);
    try { const value = await inferenceSummary(); summaryCache = { at: Date.now(), value }; return sendJson(res, 200, value); }
    catch (error) { return sendJson(res, 500, { ok: false, error: String(error?.message ?? error) }); }
  }

  // the app itself
  const headers = { ...req.headers, host: backend.host };
  if (headers.origin) headers.origin = app.url;
  for (const name of Object.keys(headers)) {
    if (name === 'forwarded' || name.startsWith('x-forwarded-') || name.startsWith('tailscale-')) delete headers[name];
  }
  const upstream = http.request({ hostname: '127.0.0.1', port: backend.port, path: req.url, method: req.method, headers }, (response) => {
    res.writeHead(response.statusCode, response.headers);
    response.pipe(res);
  });
  upstream.on('error', () => { if (!res.headersSent) res.writeHead(502); res.end(); });
  req.on('aborted', () => upstream.destroy());
  res.on('close', () => upstream.destroy());
  req.pipe(upstream);
});

await new Promise((resolve, reject) => {
  server.once('error', reject);
  server.listen(PREVIEW_PORT, '127.0.0.1', resolve);
});

console.log(JSON.stringify({
  event: 'mesh_listening', pid: process.pid, url: app.url,
  previewUrl: `http://127.0.0.1:${server.address().port}`,
  dataDir: DATA_DIR, gate: token ? 'token' : 'NO TOKEN', mode: app.mode,
}));

let stopping = false;
async function stop() {
  if (stopping) return;
  stopping = true;
  const closed = new Promise((resolve, reject) => server.close((e) => (e ? reject(e) : resolve())));
  server.closeAllConnections();
  await closed;
  await app.close();
}
for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => stop().catch((e) => { console.error(e); process.exitCode = 1; }));
