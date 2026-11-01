import http from 'node:http';

const VERSION = 'mesh-inference-observation/v1';
const BINDINGS = new Set(['legacy-current-v1', 'onoes-current-v1']);
const PATH = '/api/status';
const obj = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const keys = (v, allowed) => obj(v) && Object.keys(v).every(k => allowed.includes(k));
const id = v => typeof v === 'string' && /^[a-z][a-z0-9_-]{0,47}$/.test(v);
const label = v => typeof v === 'string' && /^[A-Za-z0-9][A-Za-z0-9 ()_-]{0,63}$/.test(v);
const integer = (v, min, max) => Number.isSafeInteger(v) && v >= min && v <= max;
const number = (v, max = 1e12) => typeof v === 'number' && Number.isFinite(v) && v >= 0 && v <= max ? v : null;
const timestamp = v => typeof v === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(v) && Number.isFinite(Date.parse(v)) && new Date(v).toISOString() === v;
const fail = code => { throw { code }; };

function origin(value) {
  // Canonical literal loopback only: no DNS, LAN, credentials, query or parser aliases.
  if (typeof value !== 'string' || !/^http:\/\/127\.0\.0\.1:[1-9]\d{3,4}$/.test(value)) fail('destination_rejected');
  const u = new URL(value);
  if (!integer(Number(u.port), 1024, 65535) || [8787, 5173].includes(Number(u.port))) fail('destination_rejected');
  return value;
}

function validate(config) {
  if (!keys(config, ['enabled', 'nodes', 'approvedOrigins', 'deadlineMs', 'maxResponseBytes', 'maxAgeMs']) || typeof config.enabled !== 'boolean' || !Array.isArray(config.nodes) || config.nodes.length > 32 || !Array.isArray(config.approvedOrigins) || config.approvedOrigins.length > 32) fail('config_invalid');
  const options = { deadlineMs: config.deadlineMs ?? 1000, maxResponseBytes: config.maxResponseBytes ?? 65536, maxAgeMs: config.maxAgeMs ?? 30000 };
  if (!integer(options.deadlineMs, 20, 5000) || !integer(options.maxResponseBytes, 256, 1048576) || !integer(options.maxAgeMs, 1, 300000)) fail('config_invalid');
  const approved = config.approvedOrigins.map(origin);
  if (new Set(approved).size !== approved.length) fail('config_invalid');
  const ids = new Set();
  const nodes = config.nodes.map(n => {
    if (!keys(n, ['id', 'label', 'enabled', 'source', 'sourceBinding', 'origin', 'observationPath', 'hostId', 'expected', 'modelBindings']) || !id(n.id) || !label(n.label) || typeof n.enabled !== 'boolean' || !['disposable_fixture', 'source_bound_live'].includes(n.source) || !BINDINGS.has(n.sourceBinding) || !id(n.hostId)) fail('config_invalid');
    if (ids.has(n.id)) fail('duplicate_node_id');
    ids.add(n.id);
    if (n.observationPath !== PATH) fail('path_rejected');
    const destination = origin(n.origin);
    if (!approved.includes(destination)) fail('destination_rejected');
    const expected = n.expected ?? {};
    if (!keys(expected, ['gpuCount', 'vramTotalMiB']) || (expected.gpuCount !== undefined && !integer(expected.gpuCount, 0, 64)) || (expected.vramTotalMiB !== undefined && number(expected.vramTotalMiB) === null)) fail('config_invalid');
    const bindings = n.modelBindings ?? [];
    if (!Array.isArray(bindings) || bindings.length > 128) fail('config_invalid');
    const seenSource = new Set(), seenId = new Set();
    for (const b of bindings) {
      if (!keys(b, ['sourceId', 'id', 'label']) || typeof b.sourceId !== 'string' || b.sourceId.length < 1 || b.sourceId.length > 256 || !id(b.id) || !label(b.label) || seenSource.has(b.sourceId) || seenId.has(b.id)) fail('config_invalid');
      seenSource.add(b.sourceId); seenId.add(b.id);
    }
    // Copy supervisor config once so later caller changes cannot redirect an in-flight read.
    return { ...n, expected: { ...expected }, modelBindings: bindings.map(b => ({ ...b })) };
  });
  return { ...options, enabled: config.enabled, nodes };
}

function emptyNode(n, status, source = n.source) {
  return { id: n.id, label: n.label, status, observedAt: null, source,
    capabilities: { observation: false, load: false, unload: false }, models: [],
    hardware: { expected: { gpuCount: n.expected.gpuCount ?? null, vramTotalMiB: n.expected.vramTotalMiB ?? null }, observed: null } };
}

// A fetch-compatible transport using only Node HTTP. No implicit fetch retries,
// redirects, proxy environment, connection pool or calls to other destinations.
function boundedGet(url, { signal, maxResponseBytes }) {
  return new Promise((resolve, reject) => {
    const req = http.request(url, { method: 'GET', agent: false, signal, headers: { Accept: 'application/json' } }, res => {
      resolve({ status: res.statusCode, redirected: false, body: res,
        headers: { get: name => res.headers[name.toLowerCase()] ?? null },
        cancel: () => { res.destroy(); req.destroy(); } });
      if (Number(res.headers['content-length']) > maxResponseBytes) res.destroy();
    });
    req.on('error', reject);
    req.end();
  });
}

async function readBody(response, cap) {
  if (Number(response.headers?.get('content-length')) > cap) fail('response_too_large');
  const type = response.headers?.get('content-type');
  if (typeof type !== 'string' || !/^application\/json(?:\s*;|$)/i.test(type)) fail('response_shape');
  if (!response.body || typeof response.body[Symbol.asyncIterator] !== 'function') fail('response_shape');
  const chunks = []; let size = 0;
  for await (const chunk of response.body) {
    if (!(chunk instanceof Uint8Array)) fail('response_shape');
    size += chunk.byteLength;
    if (size > cap) fail('response_too_large');
    chunks.push(Buffer.from(chunk));
  }
  try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks))); }
  catch { fail('malformed_json'); }
}

function dispose(response) {
  try {
    if (response?.cancel) Promise.resolve(response.cancel()).catch(() => {});
    else if (response?.body?.destroy) response.body.destroy();
    else if (response?.body?.cancel) Promise.resolve(response.body.cancel()).catch(() => {});
  } catch { /* cleanup never exposes diagnostics or extends a deadline */ }
}

function modelEvidence(host) {
  const fields = ['runtime', 'context', 'sizeGB', 'vramGB'];
  const collect = records => {
    const byId = new Map();
    for (const m of records) {
      const previous = byId.get(m.id);
      // Missing and null both express unknown. Extra private fields are ignored.
      if (previous && fields.some(k => !Object.is(previous[k] ?? null, m[k] ?? null))) fail('response_shape');
      byId.set(m.id, m);
    }
    return byId;
  };
  const loaded = collect(host.models), library = collect(host.library);
  for (const [id, m] of loaded) {
    const catalog = library.get(id);
    if (!catalog) continue;
    if (!Object.is(m.runtime ?? null, catalog.runtime ?? null) || fields.slice(1).some(k => m[k] != null && catalog[k] != null && !Object.is(m[k], catalog[k]))) fail('response_shape');
  }
  // Compatible catalog omissions never overwrite or fill loaded measurements.
  return { loaded, all: new Map([...library, ...loaded]) };
}

function gpuEvidence(gpu) {
  if (gpu === null) return null;
  const checks = { count: v => integer(v, 0, 64), vramTotal: v => number(v) !== null,
    vramUsed: v => number(v) !== null, coreUtil: v => number(v, 100) !== null };
  for (const [k, valid] of Object.entries(checks)) if (gpu[k] != null && !valid(gpu[k])) fail('response_shape');
  if (gpu.vramUsed != null && gpu.vramTotal != null && gpu.vramUsed > gpu.vramTotal) fail('response_shape');
  if (gpu.count === 0 && [gpu.vramTotal, gpu.vramUsed, gpu.coreUtil].some(v => v != null && v > 0)) fail('response_shape');
  return { gpuCount: gpu.count ?? null, vramTotalMiB: gpu.vramTotal ?? null,
    vramUsedMiB: gpu.vramUsed ?? null, utilizationPercent: gpu.coreUtil ?? null };
}

function normalize(data, n, now, maxAgeMs) {
  if (!obj(data)) fail('response_shape');
  let host;
  if (Array.isArray(data.hosts)) {
    if (data.hosts.length > 32 || data.hosts.some(h => !obj(h) || typeof h.id !== 'string')) fail('response_shape');
    const matches = data.hosts.filter(h => h.id === n.hostId);
    if (matches.length !== 1) fail('response_shape');
    host = matches[0];
  } else if (data.id === n.hostId) host = data;
  else fail('response_shape');
  const out = emptyNode(n, 'unknown', 'disposable_fixture');
  if (host.reachable === false) return { node: { ...out, status: 'unavailable' }, code: 'node_unreachable' };
  if (!obj(host.server) || !Array.isArray(host.models) || !Array.isArray(host.library) || host.models.length + host.library.length > 256 || (host.gpu !== null && !obj(host.gpu)) || [...host.models, ...host.library].some(m => !obj(m) || typeof m.id !== 'string' || m.id.length > 256)) fail('response_shape');
  if (typeof host.server.running !== 'boolean' || typeof host.server.ollama !== 'boolean') fail('response_shape');
  const evidence = modelEvidence(host), gpu = gpuEvidence(host.gpu);
  // Current status has no timestamp. Only a labeled disposable test extension is
  // accepted as timing evidence; HTTP receipt time never becomes measurement time.
  let code = 'timestamp_missing';
  const timing = data.fixtureTiming;
  if (timing !== undefined) {
    if (!keys(timing, ['label', 'observedAt']) || timing.label !== 'source-contract-shaped/v1' || !timestamp(timing.observedAt) || Date.parse(timing.observedAt) > now) code = 'timestamp_invalid';
    else {
      out.observedAt = timing.observedAt;
      out.status = now - Date.parse(timing.observedAt) > maxAgeMs ? 'stale' : 'fresh';
      code = out.status === 'stale' ? 'observation_stale' : null;
    }
  }
  out.capabilities.observation = true;
  out.models = n.modelBindings.flatMap(binding => {
    const m = evidence.all.get(binding.sourceId);
    if (!m) return [];
    const knownRuntime = ['lmstudio', 'ollama', 'mock'].includes(m.runtime) ? m.runtime : null;
    const loaded = evidence.loaded.has(binding.sourceId);
    let resident = null;
    if (out.status === 'fresh') {
      if (m.runtime === 'mock' && data.mode === 'local-mock') resident = loaded;
      if (m.runtime === 'lmstudio' && host.server.running && host.server.stateKnown === true && host.server.lmsApi === 'v0') resident = loaded;
      if (m.runtime === 'ollama' && host.server.ollama) resident = loaded;
    }
    // LM Studio context is model capacity, not the active session window.
    return [{ id: binding.id, label: binding.label, runtime: knownRuntime, resident,
      contextWindow: out.status === 'fresh' && knownRuntime !== null && integer(m.context, 1, 16777216) ? m.context : null,
      sizeGB: out.status === 'fresh' ? number(m.sizeGB, 100000) : null,
      vramGB: out.status === 'fresh' && loaded ? number(m.vramGB, 100000) : null }];
  });
  if (out.status === 'fresh') out.hardware.observed = gpu;
  return { node: out, code };
}

async function observe(n, options, now, fetchImpl) {
  if (!options.enabled || !n.enabled) return { node: emptyNode(n, 'disabled', 'disabled'), code: null };
  // There are no admitted live bindings in v1. Config cannot lift this gate.
  if (n.source === 'source_bound_live') return { node: emptyNode(n, 'unsupported'), code: 'source_gate_held' };
  const controller = new AbortController(); let response, timer, timedOut = false;
  const work = async () => {
    response = await fetchImpl(n.origin + PATH, { method: 'GET', redirect: 'manual', credentials: 'omit', cache: 'no-store', signal: controller.signal, maxResponseBytes: options.maxResponseBytes, headers: { Accept: 'application/json' } });
    if (controller.signal.aborted) { dispose(response); fail('deadline_exceeded'); }
    if (response?.redirected || integer(response?.status, 300, 399)) fail('redirect_rejected');
    if ([401, 403].includes(response?.status)) fail('unauthorized');
    if ([404, 405, 501].includes(response?.status)) fail('route_unsupported');
    if (response?.status !== 200) fail('upstream_unavailable');
    return normalize(await readBody(response, options.maxResponseBytes), n, now, options.maxAgeMs);
  };
  try {
    return await Promise.race([work(), new Promise((_, reject) => {
      timer = setTimeout(() => { timedOut = true; controller.abort(); reject({ code: 'deadline_exceeded' }); }, options.deadlineMs);
    })]);
  } catch (e) {
    const allowed = new Set(['redirect_rejected', 'unauthorized', 'route_unsupported', 'upstream_unavailable', 'response_too_large', 'response_shape', 'malformed_json', 'deadline_exceeded']);
    const code = timedOut ? 'deadline_exceeded' : allowed.has(e?.code) ? e.code : 'upstream_unavailable';
    const status = code === 'unauthorized' ? 'unauthorized' : code === 'route_unsupported' ? 'unsupported' : ['response_shape', 'malformed_json'].includes(code) ? 'unknown' : 'unavailable';
    return { node: emptyNode(n, status), code };
  } finally {
    clearTimeout(timer); controller.abort();
    dispose(response);
  }
}

export async function readInferenceSnapshot({ config, nowIso, fetchImpl = boundedGet } = {}) {
  const validTime = nowIso === undefined || timestamp(nowIso);
  const observedAt = nowIso === undefined || !validTime ? new Date().toISOString() : nowIso;
  const result = { schemaVersion: VERSION, observedAt, status: 'not_configured', nodes: [], errors: [] };
  if (!validTime) return { ...result, status: 'invalid', errors: [{ code: 'clock_invalid', nodeId: null }] };
  if (config === undefined || config === null) return result;
  let options;
  try { options = validate(config); if (typeof fetchImpl !== 'function') fail('config_invalid'); }
  catch (e) { return { ...result, status: 'invalid', errors: [{ code: ['duplicate_node_id', 'path_rejected', 'destination_rejected'].includes(e?.code) ? e.code : 'config_invalid', nodeId: null }] }; }
  const rows = await Promise.all(options.nodes.map(n => observe(n, options, Date.parse(observedAt), fetchImpl)));
  result.nodes = rows.map(r => r.node);
  result.errors = rows.filter(r => r.code).map(r => ({ code: r.code, nodeId: r.node.id }));
  const states = new Set(result.nodes.map(n => n.status));
  if (!options.enabled) result.status = 'disabled';
  else if (!rows.length) result.status = 'not_configured';
  else if (states.size === 1 && ['disabled', 'fresh', 'stale', 'unavailable', 'unauthorized', 'unsupported'].includes(result.nodes[0].status)) result.status = result.nodes[0].status;
  else result.status = 'partial';
  return result;
}
