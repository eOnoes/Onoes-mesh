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
  return {schema: value.schema, runId, state: value.state, ownerId: value.ownerId, generation: value.generation,
    localWorkEnded: value.localWorkEnded, unverifiedToolCalls: value.unverifiedToolCalls,
    sourceObservedAt: value.sourceObservedAt, observationOnly: true, writerQuiescence: false};
}

