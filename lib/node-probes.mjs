import { execFile, spawn } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { isIPv4 } from 'node:net';
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
const desktopName = 'omarchy';

// This fixed read runs as the existing SSH user. Temperatures are millidegrees
// in sysfs and degrees in nvidia-smi. The controller converts them separately.
const sensorRead = `export LC_ALL=C
[ "$(cat /proc/sys/kernel/hostname)" = omarchy ] || exit 1
printf 'host omarchy\\n'
awk '$1 == "MemTotal:" && $2 ~ /^[0-9]+$/ {total=$2}
     $1 == "MemAvailable:" && $2 ~ /^[0-9]+$/ {available=$2; found=1}
     END {if (found && total>0 && available<=total) printf "ramPct %.0f\\n",100*(total-available)/total}' /proc/meminfo
cpu_ticks() { awk '$1=="cpu" && NF>=9 {for(i=2;i<=9;i++) total+=$i; printf "%.0f %.0f\\n",total,$5+$6; exit}' /proc/stat; }
{ cpu_ticks; sleep 0.25; cpu_ticks; } | awk '
  NR==1 {total=$1; idle=$2}
  NR==2 && $1>total && $2>=idle && $2-idle<=$1-total {printf "cpuPct %.0f\\n",100*(1-($2-idle)/($1-total))}'
for busy in /sys/class/drm/card*/device/gpu_busy_percent; do
  [ -r "$busy" ] && printf 'gpuPct %s\\n' "$(cat "$busy")"
done
for hw in /sys/class/hwmon/hwmon*; do
  driver=$(cat "$hw/name" 2>/dev/null) || continue
  case "$driver" in k10temp|zenpower|coretemp|amdgpu|nouveau) ;; *) continue ;; esac
  for input in "$hw"/temp*_input; do
    [ -r "$input" ] || continue
    label=$(cat "\${input%_input}_label" 2>/dev/null)
    case "$driver:$label" in
      coretemp:Package*|k10temp:Tctl|k10temp:Tdie|zenpower:Tdie) kind=cpuMilli ;;
      amdgpu:edge|nouveau:GPU*|nouveau:) kind=gpuMilli ;;
      *) continue ;;
    esac
    printf '%s %s\\n' "$kind" "$(cat "$input")"
  done
done
if command -v nvidia-smi >/dev/null 2>&1 && command -v timeout >/dev/null 2>&1; then
  timeout -k 0.25 1.5 nvidia-smi --query-gpu=temperature.gpu,utilization.gpu --format=csv,noheader,nounits 2>/dev/null |
    awk -F ', *' '{print "gpuC",$1; print "gpuPct",$2}'
fi`;

function tailnetV4(address) {
  if (!isIPv4(address)) return false;
  const [first, second] = address.split('.').map(Number);
  return first === 100 && second >= 64 && second <= 127;
}

export async function readOmarchyHardware(host, run = execute, address) {
  if (address !== undefined && !tailnetV4(address)) throw Error('Unexpected desktop address');
  const {stdout} = await run('C:/Windows/System32/OpenSSH/ssh.exe', [
    '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ClearAllForwardings=yes',
    '-o', 'ForwardAgent=no', '-o', 'UpdateHostKeys=no', '-o', 'ConnectTimeout=3',
    ...(address ? ['-o', 'Hostname='+address] : []), host, sensorRead,
  ], {windowsHide:true, timeout:6000, maxBuffer:8192});
  const [identity, ...lines] = stdout.trim().split(/\r?\n/);
  if (identity !== 'host omarchy') throw Error('Unexpected sensor host');
  const readings = {cpuTempC:null, gpuTempC:null, ramPct:null, cpuPct:null, gpuPct:null};
  for (const line of lines) {
    const usage = /^(ramPct|cpuPct|gpuPct) (\d+)$/.exec(line);
    if (usage) {
      const value = Number(usage[2]);
      if (value <= 100) readings[usage[1]] = Math.max(readings[usage[1]] ?? 0, value);
      continue;
    }
    const match = /^(cpuMilli|gpuMilli|gpuC) (\d+)$/.exec(line);
    if (!match) continue;
    const value = Number(match[2]) / (match[1] === 'gpuC' ? 1 : 1000);
    const key = match[1] === 'cpuMilli' ? 'cpuTempC' : 'gpuTempC';
    if (value <= 150) readings[key] = Math.max(readings[key] ?? 0, value);
  }
  return readings;
}

export async function readOmarchyTemperatures(host, run = execute) {
  const {cpuTempC,gpuTempC} = await readOmarchyHardware(host, run);
  return {cpuTempC,gpuTempC};
}

export async function observeOmarchy(stdout, mainDnsName, sample = (host,address) => readOmarchyHardware(host,execute,address)) {
  const dns = desktopName + mainDnsName.slice(mainDnsName.indexOf('.'));
  try {
    const data = JSON.parse(stdout);
    if (data.BackendState !== 'Running') return {state:'unknown'};
    const peers = Object.values(data.Peer);
    const matches = peers.filter(p =>
      p?.DNSName?.replace(/\.$/, '') === dns || p?.HostName === desktopName);
    if (matches.length !== 1) return {state:'unknown'};
    const [peer] = matches;
    const addresses = peer.TailscaleIPs?.filter(tailnetV4);
    if (peer.HostName !== desktopName || peer.OS !== 'linux' || peer.DNSName?.replace(/\.$/, '') !== dns ||
        addresses?.length !== 1 || peers.some(p => p !== peer && p?.TailscaleIPs?.includes(addresses[0])) ||
        data.Self?.TailscaleIPs?.includes(addresses[0]))
      return {state:'unknown'};
    if (peer.Online === false) return {state:'offline'};
    if (peer.Online !== true) return {state:'unknown'};
    try { return {state:'online', ...await sample(dns,addresses[0])}; }
    catch { return {state:'online'}; }
  } catch { return {state:'unknown'}; }
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
export function createNodeProbeReader({ spawnImpl = spawn, clock = Date.now, monotonic = () => performance.now(), observeDesktop = spawnImpl === spawn } = {}) {
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
      const result = fleet ? await runStatus(spawnImpl) : { code: 'config_invalid' };
      const at = new Date(clock()).toISOString(), tick = monotonic();
      const observations = result.code ? identities.map(() => ({ online: null, code: result.code })) : selectNodes(result.stdout, identities);
      if (observeDesktop) {
        desktop = result.code ? {state:'unknown'} : await observeOmarchy(result.stdout, identities[0].dnsName);
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
