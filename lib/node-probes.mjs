import { execFile, spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { isIPv4 } from 'node:net';
import { homedir, hostname } from 'node:os';
import { join } from 'node:path';
import { promisify } from 'node:util';

export const TAILSCALE_EXECUTABLE = 'C:/Program Files/Tailscale/tailscale.exe';
export const TAILSCALE_STATUS_ARGV = Object.freeze(['status', '--json']);
export const NODE_PROBE_LIMITS = Object.freeze({ timeoutMs: 2000, cleanupGraceMs: 250,
  maxOutputBytes: 1048576, freshMs: 30000, staleGraceMs: 60000 });
export const NODE_IDENTITIES = Object.freeze([
  Object.freeze({ id: 'pc', label: 'PC', dnsName: 'emitchell.tail8c4a75.ts.net', tailscaleIp: '100.72.250.65' }),
  Object.freeze({ id: 'laptop', label: 'Laptop', dnsName: 'emitchell109-rog.tail8c4a75.ts.net', tailscaleIp: '100.119.162.99' })
]);
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const exactKeys = (value, keys) => object(value) && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
const error = code => ({ code });

export function validAiBox(node) {
  if (!exactKeys(node, Object.keys(NODE_IDENTITIES[0])) || node.id !== 'ai-box' || node.label !== 'AI box'
      || typeof node.dnsName !== 'string' || !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.tail8c4a75\.ts\.net$/.test(node.dnsName)
      || !isIPv4(node.tailscaleIp)) return false;
  const [first, second] = node.tailscaleIp.split('.').map(Number);
  return first === 100 && second >= 64 && second <= 127 &&
    NODE_IDENTITIES.every(fixed => fixed.dnsName !== node.dnsName && fixed.tailscaleIp !== node.tailscaleIp);
}

function configuredFleet() {
  try {
    const config = JSON.parse(readFileSync(new URL('../config/nodes.json', import.meta.url), 'utf8'));
    if (!exactKeys(config, ['schemaVersion', 'nodes']) || !Array.isArray(config.nodes) ||
        !NODE_IDENTITIES.every((fixed, i) => exactKeys(config.nodes[i], Object.keys(fixed)) &&
          Object.entries(fixed).every(([key, value]) => config.nodes[i][key] === value))) return null;
    if (config.schemaVersion === 'mesh-node-identities/v1' && config.nodes.length === 2)
      return { nodes: NODE_IDENTITIES };
    if (config.schemaVersion === 'mesh-node-identities/v2') {
      if (config.nodes.length === 3 && validAiBox(config.nodes[2])) return { nodes: [...NODE_IDENTITIES, config.nodes[2]] };
      return { nodes: NODE_IDENTITIES, configurationIssue: 'ai_box_identity_invalid' };
    }
  } catch { /* A missing or unreadable identity file cannot authorize a probe. */ }
  return null;
}

// Only the fixed executable/argv are ever sent to spawn. The trusted test hook
// substitutes disposable child processes, never browser or request data.
function runStatus(spawnImpl) {
  return new Promise(resolve => {
    let child, timer, cleanupTimer, failure = null, settled = false, bytes = 0;
    const chunks = [], diagnostics = [];
    const finish = result => {
      if (settled) return;
      settled = true;
      clearTimeout(timer); clearTimeout(cleanupTimer);
      child?.stdout?.destroy(); child?.stderr?.destroy();
      resolve(result);
    };
    const stop = code => {
      if (failure || settled) return;
      failure = code;
      // This is the retained child created by this call; no process enumeration,
      // image-wide taskkill, service restart or daemon control.
      try { if (!child.kill()) failure = 'process_cleanup_failed'; }
      catch { failure = 'process_cleanup_failed'; }
      cleanupTimer = setTimeout(() => finish({ code: 'process_cleanup_failed' }), NODE_PROBE_LIMITS.cleanupGraceMs);
    };
    try {
      child = spawnImpl(TAILSCALE_EXECUTABLE, [...TAILSCALE_STATUS_ARGV], {
        shell: false, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe']
      });
    } catch { finish({ code: 'cli_unavailable' }); return; }
    child.once('error', e => finish({ code: ['EACCES', 'EPERM'].includes(e?.code) ? 'cli_access_denied' : 'cli_unavailable' }));
    const take = (chunk, target) => {
      if (settled || failure) return;
      bytes += chunk.length;
      if (bytes > NODE_PROBE_LIMITS.maxOutputBytes) { stop('output_too_large'); return; }
      target.push(Buffer.from(chunk));
    };
    child.stdout.on('data', chunk => take(chunk, chunks));
    child.stderr.on('data', chunk => take(chunk, diagnostics));
    child.stdout.on('error', () => stop('cli_read_failed'));
    child.stderr.on('error', () => stop('cli_read_failed'));
    child.once('close', (exitCode, signal) => {
      if (failure) { finish({ code: failure }); return; }
      if (exitCode !== 0 || signal) {
        // Inspect only bounded diagnostics internally; never return tailnet data,
        // user profiles, raw stderr, auth hints, or paths supplied by the daemon.
        const denied = /access is denied|access denied|permission denied/i.test(Buffer.concat(diagnostics).toString('utf8'));
        finish({ code: denied ? 'cli_access_denied' : 'cli_failed' });
        return;
      }
      try { finish({ stdout: new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks)), code: null }); }
      catch { finish({ code: 'malformed_output' }); }
    });
    timer = setTimeout(() => stop('cli_timeout'), NODE_PROBE_LIMITS.timeoutMs);
  });
}

const execute = promisify(execFile);
const desktopAlias = 'tripp-inference-temp';
// Fixed read-only utilities from the verified LAN desktop. Parse their output on Echo's PC.
const desktopRead = [
  'export LC_ALL=C',
  '[ "$(hostname)" = onoes-tripp ] && [ "$(id -un)" = onoes ] || exit 1',
  'echo "onoes-tripp onoes"',
  'echo @ram', 'free -b',
  'echo @cpu', 'vmstat -w 1 2',
  'echo @thermal', 'sensors -j 2>/dev/null',
  'echo @gpu', 'timeout 2 nvidia-smi --query-gpu=index,name,temperature.gpu,utilization.gpu --format=csv,noheader,nounits 2>/dev/null',
  'echo @ollama', 'OLLAMA_HOST=127.0.0.1:11434 timeout 2 ollama ps 2>/dev/null && echo @ollama-ok',
  // This campaign's public health check reports readiness only. It does not identify a loaded model.
  "curl --disable --noproxy '*' --max-time 1 --max-filesize 4096 -fsS http://127.0.0.1:19010/health 2>/dev/null | jq -e '.status == \"ok\"' >/dev/null 2>&1 && echo @strata-ready",
  'echo @end',
].join('; ');

function cpuTemperature(output) {
  try {
    const chips = JSON.parse(output);
    const values = [];
    for (const [chip, readings] of Object.entries(chips)) {
      const amd = /^(k10temp|zenpower)-/.test(chip);
      if (!amd && !chip.startsWith('coretemp-')) continue;
      const labels = amd ? (readings.Tdie ? ['Tdie'] : ['Tctl']) : Object.keys(readings).filter(k => k.startsWith('Package id '));
      for (const label of labels) {
        for (const [key,value] of Object.entries(readings[label] ?? {})) {
          if (/^temp\d+_input$/.test(key) && Number.isFinite(value) && value >= 0 && value <= 150) values.push(value);
        }
      }
    }
    return values.length ? Math.max(...values) : null;
  } catch { return null; }
}

export async function readTrippHardware(run = execute) {
  if (run === execute && (process.platform !== 'win32' || hostname().toLowerCase() !== 'emitchell'))
    throw Error('The approved LAN profile is on Echo’s PC');
  const config = join(homedir(), '.ssh', 'keys', 'echo-tripp-temp-management', 'ssh_config');
  const {stdout} = await run('C:/Windows/System32/OpenSSH/ssh.exe', [
    '-F', config, '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', '-o','UpdateHostKeys=no',
    '-o','StrictHostKeyChecking=yes','-o','IdentitiesOnly=yes','-o','ForwardAgent=no',
    '-o','ClearAllForwardings=yes','-T',desktopAlias,desktopRead,
  ], {windowsHide:true, timeout:13000, maxBuffer:65536});
  const [identity,...lines] = stdout.trim().split(/\r?\n/);
  if (identity !== 'onoes-tripp onoes' || lines.at(-1) !== '@end') throw Error('Incomplete Tripp observation');
  const sections = new Map();
  let current;
  for (const line of lines) {
    if (line.startsWith('@')) { current=[]; sections.set(line,current); }
    else if (line.trim()) current?.push(line.trim());
  }
  const sample = {ramPct:null,cpuPct:null,gpuPct:null,cpuTempC:null,gpuTempC:null,ollamaModels:null,
    strataHealth:sections.has('@strata-ready') ? 'ready' : null};
  const mem = sections.get('@ram')?.find(s => s.startsWith('Mem:'))?.split(/\s+/);
  if (mem?.length === 7) {
    const total=Number(mem[1]), available=Number(mem[6]);
    if (Number.isSafeInteger(total) && total>0 && Number.isSafeInteger(available) && available>=0 && available<=total)
      sample.ramPct=Math.round(100*(1-available/total));
  }
  const cpu=sections.get('@cpu') ?? [], labels=cpu.find(s=>s.startsWith('r '))?.split(/\s+/);
  const samples=cpu.filter(s=>/^\d+\s/.test(s));
  if (labels && samples.length===2) {
    const row=samples[1].split(/\s+/).map(Number);
    const idle=row[labels.indexOf('id')], wait=row[labels.indexOf('wa')];
    if (row.length===labels.length && idle>=0 && wait>=0 && idle+wait<=100) sample.cpuPct=100-idle-wait;
  }
  sample.cpuTempC=cpuTemperature((sections.get('@thermal') ?? []).join('\n'));
  const metric = (text, max) => /^\d+$/.test(text) && Number(text) <= max ? Number(text) : null;
  for (const line of sections.get('@gpu') ?? []) {
    const row = /^(\d{1,3}),\s*(.{1,120}),\s*([^,]+),\s*([^,]+)$/.exec(line);
    if (!row) continue;
    const tempC = metric(row[3].trim(), 150);
    const usagePct = metric(row[4].trim(), 100);
    (sample.gpus ??= []).push({index:Number(row[1]), name:row[2].trim(), tempC, usagePct});
    if (tempC !== null) sample.gpuTempC = Math.max(sample.gpuTempC ?? 0, tempC);
    if (usagePct !== null) sample.gpuPct = Math.max(sample.gpuPct ?? 0, usagePct);
  }
  const [header,...models]=sections.get('@ollama') ?? [];
  if (sections.has('@ollama-ok') && /^NAME\s+ID\s+SIZE\b/.test(header ?? '') &&
      models.every(line=>/^\S+\s+[0-9a-f]{6,}\s/i.test(line)))
    sample.ollamaModels=models.map(line=>line.split(/\s+/)[0]);
  return sample;
}

function selectNodes(stdout, identities) {
  let data;
  try { data = JSON.parse(stdout); }
  catch { return identities.map(() => ({ online: null, code: 'malformed_output' })); }
  if (!object(data) || typeof data.BackendState !== 'string')
    return identities.map(() => ({ online: null, code: 'malformed_output' }));
  if (data.BackendState !== 'Running')
    return identities.map(() => ({ online: null, code: 'tailscale_not_running' }));
  if (!object(data.Self) || !object(data.Peer) || Object.values(data.Peer).some(peer => !object(peer)))
    return identities.map(() => ({ online: null, code: 'malformed_output' }));
  const peers = [data.Self, ...Object.values(data.Peer)];
  const dnsName = peer => typeof peer.DNSName === 'string' ? peer.DNSName.replace(/\.$/, '') : null;
  const hasIp = (peer, node) => Array.isArray(peer.TailscaleIPs) && peer.TailscaleIPs.includes(node.tailscaleIp);
  return identities.map(node => {
    // Either identity component selects a candidate; both must agree exactly.
    // Short host names, suffix matches and similarly named cloud nodes cannot win.
    const matches = peers.filter(peer => dnsName(peer) === node.dnsName || hasIp(peer, node));
    if (!matches.length) return { online: null, code: 'node_missing' };
    if (matches.length !== 1) return { online: null, code: 'identity_ambiguous' };
    const peer = matches[0];
    if (dnsName(peer) !== node.dnsName || !hasIp(peer, node)) return { online: null, code: 'identity_mismatch' };
    if (typeof peer.Online !== 'boolean') return { online: null, code: 'malformed_output' };
    return { online: peer.Online, code: peer.Online ? null : 'node_offline' };
  });
}

/**
 * Server-owned, in-memory reader. Caller owns refreshing; no watcher or persistence.
 * refresh() performs one native status read for the configured nodes; snapshot()
 * only ages the cache. Concurrent refresh calls share the same owned operation.
 * Ready means the CLI reported Online=true, not a successful packet ping. All
 * timestamps are local observation times, never invented daemon measurements.
 * Last success survives failures but only grants stale for 60s from that success.
 */
export function createNodeProbeReader({ spawnImpl = spawn, clock = Date.now, monotonic = () => performance.now(), observeDesktop = spawnImpl === spawn, sampleDesktop = readTrippHardware } = {}) {
  if (typeof spawnImpl !== 'function' || typeof clock !== 'function' || typeof monotonic !== 'function') throw new TypeError('invalid probe hooks');
  const fleet = configuredFleet();
  const identities = fleet?.nodes ?? NODE_IDENTITIES;
  const states = identities.map(() => ({ lastProbeAt: null, lastSuccessAt: null,
    successTick: null, online: null, code: 'not_probed', availability: 'unavailable' }));
  let pending;
  let desktop = {state:'unknown'}, desktopTick = -Infinity;
  const snapshot = () => {
    const tick = monotonic();
    return { schemaVersion: 'mesh-node-probes/v1', observedAt: new Date(clock()).toISOString(),
      source: spawnImpl === spawn ? 'native_tailscale_cli' : 'disposable_transport',
      scope: 'tailnet_node_state', limits: { freshMs: NODE_PROBE_LIMITS.freshMs, staleGraceMs: NODE_PROBE_LIMITS.staleGraceMs },
      ...(observeDesktop && {trippDesktop: tick - desktopTick < NODE_PROBE_LIMITS.freshMs
        ? {...desktop, ageMs:Math.max(0, tick - desktopTick)} : {state:'unknown'}}),
      ...(fleet?.configurationIssue && { configurationIssue: fleet.configurationIssue }),
      nodes: identities.map((node, index) => {
        const state = states[index];
        const age = state.successTick === null ? Infinity : Math.max(0, tick - state.successTick);
        const status = age >= NODE_PROBE_LIMITS.staleGraceMs ? 'offline'
          : state.online === true && state.availability === 'available' && age < NODE_PROBE_LIMITS.freshMs ? 'ready' : 'stale';
        const code = state.code ?? (status === 'ready' ? null : 'observation_expired');
        return { ...node, status, lastProbeAt: state.lastProbeAt, lastSuccessAt: state.lastSuccessAt,
          observationType: 'tailscale_status_cached_online', timestampSource: 'local_probe_completion',
          observationAvailability: state.availability, tailscaleOnline: state.online,
          packetReachability: 'unknown', inferenceReadiness: 'unknown', modelReadiness: 'unknown',
          capabilities: { observation: true, control: false, load: false, inference: false, unload: false },
          errors: code ? [error(code)] : [] };
      }) };
  };
  const refresh = () => {
    if (pending) return pending;
    pending = (async () => {
      const [result, lan] = await Promise.all([
        fleet ? runStatus(spawnImpl) : {code:'config_invalid'},
        observeDesktop ? Promise.resolve().then(sampleDesktop).then(
          sample => ({...sample, state:'online', source:'lan_ssh'}),
          () => ({state:'unknown', source:'lan_ssh'})) : null,
      ]);
      const at = new Date(clock()).toISOString(), tick = monotonic();
      const observations = result.code ? identities.map(() => ({ online: null, code: result.code })) : selectNodes(result.stdout, identities);
      if (observeDesktop) {
        desktop = lan;
        desktopTick = tick;
      }
      observations.forEach((observation, index) => {
        const state = states[index];
        state.lastProbeAt = at; state.online = observation.online; state.code = observation.code;
        state.availability = observation.online === null ? 'unavailable' : 'available';
        if (observation.online === true) { state.lastSuccessAt = at; state.successTick = tick; }
      });
      return snapshot();
    })().finally(() => { pending = null; });
    return pending;
  };
  return Object.freeze({ refresh, snapshot });
}
