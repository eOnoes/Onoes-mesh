import { LOCAL_PROFILE } from '../lib/local-inference.mjs';

// Deterministic in-memory evidence only; never starts or observes a process.
export function localFixture() {
  let at = Date.now(), running = false, exited = false;
  const identity = { pid: 12345, createdAt: new Date(at).toISOString(),
    executable: LOCAL_PROFILE.executable, executableSha256: LOCAL_PROFILE.executableSha256,
    cwd: LOCAL_PROFILE.cwd, argvHash: 'a'.repeat(64) };
  const calls = { start: [], stop: [], chat: [] };
  const fixture = { calls, identity, override: value => { override = value; },
    advance: ms => { at += ms; }, now: () => at, stopExits: true,
    chatChunks: ['Fixture reply'], holdStart: null, holdObserve: null };
  let override;
  fixture.adapter = { enabled: true, source: 'disposable_fixture',
    async observe() {
      if (fixture.holdObserve) await fixture.holdObserve;
      const result = { observedAt: at, custodyClear: !running, listenerAbsent: !running,
        identity: { ...identity }, retainedHandle: true,
        listener: running ? { pid: identity.pid, host: '127.0.0.1' } : null,
        health: { ok: running, observedAt: at, profileId: LOCAL_PROFILE.id },
        gpuMapping: 'VERIFIED', exited, exitVerified: exited };
      return override ? override(result) : result;
    },
    async start(profile, { signal }) {
      calls.start.push(profile);
      if (fixture.holdStart) await fixture.holdStart;
      if (signal.aborted) throw new Error('aborted');
      running = true; exited = false; return { ...identity };
    },
    async stop(lease) {
      calls.stop.push(lease);
      if (fixture.stopExits) { running = false; exited = true; }
    },
    async *chat(request, { signal }) {
      calls.chat.push({ maxTokens: request.maxTokens, stream: request.stream });
      for (const chunk of fixture.chatChunks) { if (signal.aborted) throw new Error('aborted'); yield chunk; }
    },
  };
  return fixture;
}
