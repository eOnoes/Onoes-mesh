// Preserve the frozen connection reader; label only its injected Relay observation.
// The mode comes from server-owned adapter construction, never browser input.
export function withRelaySource(read,source){
  if(!['isolated_relay','live_relay_http'].includes(source))throw Error('Unsupported Relay observation source.');
  return async()=>{
    const snapshot=await read();
    return {...snapshot,services:snapshot.services.map(service=>service.id==='relay'&&service.source==='isolated_relay'?{...service,source}:service)};
  };
}
