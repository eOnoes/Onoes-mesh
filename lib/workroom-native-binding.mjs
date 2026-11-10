import {resolve,isAbsolute} from 'node:path';
import {TaskError} from './task-store.mjs';
import {localSessionProfile} from './workroom-local-sessions.mjs';

// Trusted process configuration only. Creating the binding performs no RPC,
// credential lookup, session creation or enrollment. Omission keeps Relay routing.
export function createNativeWorkerBinding(options) {
  if (options === undefined) return null;
  if (!options || Object.keys(options).some(key => !['profile','rpc','authorized','close'].includes(key))
      || typeof options.rpc !== 'function' || typeof options.authorized !== 'function'
      || options.close !== undefined && typeof options.close !== 'function')
    throw new TaskError(400, 'An explicit native worker connection is required.');
  const profile = Object.freeze(localSessionProfile(options.profile));
  if (profile.provider !== 'openai-codex')
    throw new TaskError(400, 'This server binding requires the reviewed native Codex profile.');
  // Copy the functions too: mutating the supplied configuration cannot replace
  // the transport or authority gate after the server has accepted it.
  const request = options.rpc, permission = options.authorized, disconnect = options.close;
  const key = JSON.stringify(profile);
  let closed = false, closing;
  const authorized = candidate => {
    if (closed) return false;
    try {
      return JSON.stringify(localSessionProfile(candidate)) === key && permission(profile) === true;
    } catch { return false; }
  };
  const requireAccess = () => {
    if (!authorized(profile)) throw new TaskError(403, 'Native worker connection is not authorized.');
  };
  return Object.freeze({
    retireCompleted: true,
    authorized,
    profileFor(task) {
      requireAccess();
      if (task?.plan?.state !== 'locked' || task.plan.workerId !== 'echo'
          || task.plan.reviewerId !== 'nims' || typeof task.plan.workspace !== 'string' || !isAbsolute(task.plan.workspace)
          || resolve(task.plan.workspace).toLowerCase() !== profile.workspace)
        throw new TaskError(409, 'The locked team does not match the enrolled native workspace and route.');
      return {...profile};
    },
    async rpc(method, params) {
      requireAccess();
      const result = await request(method, params);
      // A revoked or closed connection cannot import a late observation. Saved
      // IDs remain the recovery source; no replacement request is issued here.
      requireAccess();
      return result;
    },
    close() {
      closed = true;
      return closing ??= Promise.resolve().then(() => disconnect?.());
    },
  });
}
