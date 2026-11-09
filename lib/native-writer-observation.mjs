export function normalizeWriterObservation(value, runId, expectedOwner, expectedGeneration) {
  const uuid = value => typeof value === 'string' && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(value);
  const unknown = value?.state === 'unknown' || value?.state === 'not_configured';
  if (typeof runId !== 'string' || !/^run_[A-Za-z0-9_-]{1,128}$/.test(runId)
      || !value || value.schema !== 'mesh-relay-writer-observation/v1' || value.runId !== runId
      || value.observationOnly !== true || value.writerQuiescence !== false
      || (!unknown && value.state !== 'observed')
      || (unknown && (value.ownerId !== null || value.generation !== null || value.localWorkEnded !== false
        || value.unverifiedToolCalls !== null || value.sourceObservedAt !== null))
      || (!unknown && (!uuid(value.ownerId) || !uuid(value.generation) || typeof value.localWorkEnded !== 'boolean'
        || !Number.isSafeInteger(value.unverifiedToolCalls) || value.unverifiedToolCalls < 0
        || !Number.isSafeInteger(value.sourceObservedAt) || value.sourceObservedAt <= 0))
      || (expectedOwner !== undefined && (value.ownerId !== expectedOwner || value.generation !== expectedGeneration))) {
    throw new TypeError('Native worker observation is unverified.');
  }
  let fileCompletion;
  if (value.fileCompletion !== undefined) {
    const f = value.fileCompletion;
    if (unknown || !f || f.schema !== 'mesh-file-effect-summary/v1' || f.policy !== 'bounded_native_write_file_v1'
        || ![f.observedCalls,f.activeCalls,f.qualifiedCalls].every(n => Number.isSafeInteger(n) && n >= 0)
        || f.qualifiedCalls < 1 || f.observedCalls !== f.activeCalls + f.qualifiedCalls + value.unverifiedToolCalls
        || typeof f.effectsSettled !== 'boolean' || f.effectsSettled !== (f.activeCalls === 0 && value.unverifiedToolCalls === 0)
        || (value.localWorkEnded && f.activeCalls !== 0)) {
      throw new TypeError('Native file completion is unverified.');
    }
    fileCompletion = {schema:f.schema,policy:f.policy,observedCalls:f.observedCalls,activeCalls:f.activeCalls,
      qualifiedCalls:f.qualifiedCalls,effectsSettled:f.effectsSettled};
  }
  return {schema: value.schema, runId, state: value.state, ownerId: value.ownerId, generation: value.generation,
    localWorkEnded: value.localWorkEnded, unverifiedToolCalls: value.unverifiedToolCalls,
    sourceObservedAt: value.sourceObservedAt, observationOnly: true, writerQuiescence: false,
    ...(fileCompletion ? {fileCompletion} : {})};
}

