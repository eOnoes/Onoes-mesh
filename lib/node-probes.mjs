import { spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';

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

function fixedConfigValid() {
  try {
    const config = JSON.parse(readFileSync(new URL('../config/nodes.json', import.meta.url), 'utf8'));
    return exactKeys(config, ['schemaVersion', 'nodes']) && config.schemaVersion === 'mesh-node-identities/v1'
      && Array.isArray(config.nodes) && config.nodes.length === 2 && config.nodes.every((node, index) =>
        exactKeys(node, Object.keys(NODE_IDENTITIES[index])) && Object.entries(NODE_IDENTITIES[index]).every(([key, value]) => node[key] === value));
  } catch { return false; }
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

function selectNodes(stdout) {
  let data;
  try { data = JSON.parse(stdout); }
  catch { return NODE_IDENTITIES.map(() => ({ online: null, code: 'malformed_output' })); }
  if (!object(data) || typeof data.BackendState !== 'string')
    return NODE_IDENTITIES.map(() => ({ online: null, code: 'malformed_output' }));
  if (data.BackendState !== 'Running')
    return NODE_IDENTITIES.map(() => ({ online: null, code: 'tailscale_not_running' }));
  if (!object(data.Self) || !object(data.Peer) || Object.values(data.Peer).some(peer => !object(peer)))
    return NODE_IDENTITIES.map(() => ({ online: null, code: 'malformed_output' }));
  const peers = [data.Self, ...Object.values(data.Peer)];
  const dnsName = peer => typeof peer.DNSName === 'string' ? peer.DNSName.replace(/\.$/, '') : null;
  const hasIp = (peer, node) => Array.isArray(peer.TailscaleIPs) && peer.TailscaleIPs.includes(node.tailscaleIp);
  return NODE_IDENTITIES.map(node => {
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
 * refresh() performs one native status read for the two fixed nodes; snapshot()
 * only ages the cache. Concurrent refresh calls share the same owned operation.
 * Ready means the CLI reported Online=true, not a successful packet ping. All
 * timestamps are local observation times, never invented daemon measurements.
 * Last success survives failures but only grants stale for 60s from that success.
 */
export function createNodeProbeReader({ spawnImpl = spawn, clock = Date.now, monotonic = () => performance.now() } = {}) {
  if (typeof spawnImpl !== 'function' || typeof clock !== 'function' || typeof monotonic !== 'function') throw new TypeError('invalid probe hooks');
  const configValid = fixedConfigValid();
  const states = NODE_IDENTITIES.map(() => ({ lastProbeAt: null, lastSuccessAt: null,
    successTick: null, online: null, code: 'not_probed', availability: 'unavailable' }));
  let pending;
  const snapshot = () => {
    const tick = monotonic();
    return { schemaVersion: 'mesh-node-probes/v1', observedAt: new Date(clock()).toISOString(),
      source: spawnImpl === spawn ? 'native_tailscale_cli' : 'disposable_transport',
      scope: 'tailnet_node_state', limits: { freshMs: NODE_PROBE_LIMITS.freshMs, staleGraceMs: NODE_PROBE_LIMITS.staleGraceMs },
      nodes: NODE_IDENTITIES.map((node, index) => {
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
      const result = configValid ? await runStatus(spawnImpl) : { code: 'config_invalid' };
      const at = new Date(clock()).toISOString(), tick = monotonic();
      const observations = result.code ? NODE_IDENTITIES.map(() => ({ online: null, code: result.code })) : selectNodes(result.stdout);
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
