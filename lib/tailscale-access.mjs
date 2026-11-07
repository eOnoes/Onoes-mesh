// Only enable behind the loopback-only Tailscale Serve proxy. Serve strips
// client-supplied identity headers and supplies the authenticated user itself.
export function tailscaleAccess(request, {login, host} = {}) {
  if(!login || !host)return false;
  const peer=request.socket?.remoteAddress;
  if(!['127.0.0.1','::1','::ffff:127.0.0.1'].includes(peer))return false;
  return request.headers.host===host &&
    request.headers['tailscale-user-login']===login;
}
