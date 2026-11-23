import {execFile} from 'node:child_process';
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {promisify} from 'node:util';
import {NODE_IDENTITIES, validAiBox} from './node-probes.mjs';

const execute = promisify(execFile);
const scriptUrl = new URL('../integrations/tripp-hardware.ps1', import.meta.url);
const expectedName = 'emitchell109-rog';
const freshMs = 30_000;

function normalizeWindowsSample(raw, expectedHost) {
  const sample = JSON.parse(raw);
  if (typeof sample?.hostName !== 'string' || sample.hostName.toLowerCase() !== expectedHost)
    throw Error('Unexpected telemetry host');
  const metric = (value, max) => Number.isFinite(value) && value >= 0 && value <= max ? value : null;
  return {cpuPct:metric(sample.cpuPct,100), ramPct:metric(sample.ramPct,100),
    gpuPct:metric(sample.gpuPct,100), gpuTempC:metric(sample.gpuTempC,150), cpuTempC:metric(sample.cpuTempC,150)};
}

export function normalizeTrippSample(raw) {
  return normalizeWindowsSample(raw, expectedName);
}

export function encodeTrippProbe(source) {
  const script = source.replaceAll('\r\n', '\n');
  const digest = createHash('sha256').update(script).digest('hex');
  if (digest !== '3c36a7c22d9bfb9e97f222402549a5fd600a8b16eadfb2da5f1a29dec7449b13')
    throw Error('Windows sensor script does not match the reviewed version');
  return Buffer.from(script, 'utf16le').toString('base64');
}

export async function readWindowsHardware(node, expectedHost, run = execute) {
  const {id, label, dnsName, tailscaleIp} = node;
  const laptop = NODE_IDENTITIES[1];
  if (!(id === 'laptop' && dnsName === laptop.dnsName && tailscaleIp === laptop.tailscaleIp) &&
      !validAiBox({id, label, dnsName, tailscaleIp})) throw Error('Unrecognized telemetry target');
  const encoded = encodeTrippProbe(await readFile(scriptUrl, 'utf8'));
  const alias = id === 'laptop' ? 'laptop-echo' : 'ai-box-echo';
  const {stdout} = await run('C:/Windows/System32/OpenSSH/ssh.exe', [
    '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ClearAllForwardings=yes',
    '-o', 'ForwardAgent=no', '-o', 'Hostname=' + node.tailscaleIp, '-o', 'ConnectTimeout=3', alias, 'powershell.exe',
    '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded
  ], {windowsHide:true, timeout:8000, maxBuffer:8192});
  return normalizeWindowsSample(stdout.replace(/^\uFEFF/, '').trim(), expectedHost);
}

// The node reader supplies the operator-configured, tailnet-verified addresses.
// A sensor opt-in never adds a node or selects a command from a client request.
export function withRemoteHardware(nodes, {laptop = false, aiBoxHost, sample = readWindowsHardware, clock = Date.now} = {}) {
  const hosts = new Map();
  if (laptop) hosts.set('laptop', expectedName);
  if (typeof aiBoxHost === 'string' && /^[a-z0-9][a-z0-9-]{0,14}$/i.test(aiBoxHost))
    hosts.set('ai-box', aiBoxHost.toLowerCase());
  if (!hosts.size) return nodes;
  const samples = new Map();
  const ready = n => n.status === 'ready' && n.tailscaleOnline === true && n.observationAvailability === 'available';
  let pending;
  function snapshot() {
    const view = nodes.snapshot();
    return {...view,nodes:view.nodes.map(n => {
      if (!hosts.has(n.id)) return n;
      const current = samples.get(n.id);
      const age = current ? clock() - current.at : Infinity;
      const usable = ready(n) && age >= 0 && age < freshMs;
      return {...n,hardware:usable ? current.value : null,
        hardwareObservedAt:usable ? new Date(current.at).toISOString() : null};
    })};
  }
  async function collect() {
    let view;
    try { view = await nodes.refresh(); }
    catch (error) { samples.clear(); throw error; }
    await Promise.all([...hosts].map(async ([id, expectedHost]) => {
      const node = view.nodes.find(n => n.id === id);
      if (!node || !ready(node)) { samples.delete(id); return; }
      try {
        const value = await sample(node, expectedHost);
        samples.set(id, {at:clock(),value});
      } catch { samples.delete(id); }
    }));
    return snapshot();
  }
  return {snapshot, refresh() {
    if (!pending) pending = collect().finally(() => { pending = undefined; });
    return pending;
  }};
}

export function withTrippHardware(nodes, options = {}) {
  return withRemoteHardware(nodes, {...options, laptop:true});
}
