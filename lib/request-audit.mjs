const fixed=new Set(['/', '/api/health','/api/tasks','/api/workroom','/api/trial-session/bootstrap','/api/trial-session/logout','/api/trial-session/recovery-challenge','/api/trial-session/recovery-complete','/gate/status']);
export function requestAudit(req){
  const path=String(req.url||'').split(/[?#]/,1)[0];
  const entity=/^\/api\/(tasks|workroom)\/[A-Za-z0-9_-]+(?:\/(progress|sync|message|handoff|apply-update|apply-review|proposal|approve|deny|cancel))?$/.exec(path);
  const url=fixed.has(path)?path:entity?`/api/${entity[1]}/:id${entity[2]?'/'+entity[2]:''}`:'[unrecognized route]';
  return {method:['GET','HEAD','POST','PUT','PATCH','DELETE','OPTIONS'].includes(req.method)?req.method:'OTHER',url,
    hostPresent:Boolean(req.headers?.host),originPresent:Boolean(req.headers?.origin),forwardedHostPresent:Boolean(req.headers?.['x-forwarded-host'])};
}
export const auditReason=reason=>/^[a-z_-]+/i.exec(String(reason||''))?.[0]||'unspecified';
