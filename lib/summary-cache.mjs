// Share one read-only hardware collection across tabs. Failed reads are retried;
// completed samples expire independently of changes to the Windows wall clock.
export function createSummaryReader(collect, { now = () => performance.now(), ttlMs = 2000 } = {}) {
  let value, completedAt = null, pending;
  return () => {
    const tick = now();
    if (completedAt !== null && tick >= completedAt && tick - completedAt < ttlMs)
      return Promise.resolve(value);
    if (!pending) pending = Promise.resolve().then(collect).then(result => {
      value = result;
      completedAt = now();
      return result;
    }).finally(() => { pending = undefined; });
    return pending;
  };
}
