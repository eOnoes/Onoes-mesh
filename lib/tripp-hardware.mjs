import {execFile} from 'node:child_process';
import {readFile} from 'node:fs/promises';
import {promisify} from 'node:util';

const execute = promisify(execFile);
const scriptUrl = new URL('../integrations/tripp-hardware.ps1', import.meta.url);
const expectedName = 'emitchell109-rog';
const freshMs = 30_000;

export function normalizeTrippSample(raw) {
  const sample = JSON.parse(raw);
  if (typeof sample?.hostName !== 'string' || sample.hostName.toLowerCase() !== expectedName)
    throw Error('Unexpected telemetry host');
  const metric = (value, max) => Number.isFinite(value) && value >= 0 && value <= max ? value : null;
  return {cpuPct:metric(sample.cpuPct,100), ramPct:metric(sample.ramPct,100),
    gpuPct:metric(sample.gpuPct,100), gpuTempC:metric(sample.gpuTempC,150), cpuTempC:metric(sample.cpuTempC,150)};
}

async function sampleLaptop() {
  const script = await readFile(scriptUrl, 'utf8');
  const encoded = Buffer.from(script, 'utf16le').toString('base64');
  const {stdout} = await execute('C:/Windows/System32/OpenSSH/ssh.exe', [
    '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ClearAllForwardings=yes',
    '-o', 'ForwardAgent=no', '-o', 'Hostname=100.119.162.99', '-o', 'ConnectTimeout=3', 'laptop-echo', 'powershell.exe',
    '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded
  ], {windowsHide:true, timeout:8000, maxBuffer:8192});
  return normalizeTrippSample(stdout.replace(/^\uFEFF/, '').trim());
}

// A host explicitly enrolls this wrapper at startup. Reads use the configured
// laptop alias only after Mesh verifies its tailnet identity and online flag.
export function withTrippHardware(nodes, {sample = sampleLaptop, clock = Date.now} = {}) {
  let current, pending;
  function snapshot() {
    const view = nodes.snapshot();
    return {...view,nodes:view.nodes.map(n => {
      if (n.id !== 'laptop') return n;
      const age = current ? clock() - current.at : Infinity;
      const usable = n.status === 'ready' && n.tailscaleOnline === true &&
        n.observationAvailability === 'available' && age >= 0 && age < freshMs;
      return {...n,hardware:usable ? current.value : null,
        hardwareObservedAt:usable ? new Date(current.at).toISOString() : null};
    })};
  }
  async function collect() {
    current = undefined;
    const view = await nodes.refresh();
    const laptop = view.nodes.find(n => n.id === 'laptop');
    if (laptop?.status === 'ready' && laptop.tailscaleOnline === true && laptop.observationAvailability === 'available') {
      try { const value = await sample(); current = {at:clock(),value}; }
      catch { current = undefined; }
    }
    return snapshot();
  }
  return {snapshot, refresh() {
    if (!pending) pending = collect().finally(() => { pending = undefined; });
    return pending;
  }};
}
