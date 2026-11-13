// Shared by dispatch admission and the read-only legacy recovery collector.
export function isUnresolvedWorkSend(message) {
  return message?.phase === 'work' && ['prepared', 'unknown', 'accepted'].includes(message.state);
}
