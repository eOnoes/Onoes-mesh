// Explicit server-owned lifecycle only. Importing this module never starts work.
// Deployment must separately establish one process owner for the bound workspace.
const owners = new WeakMap();
const states = new Set(['saved','held','idle','uncertain','unavailable','busy']);

export function createProjectSyncRunner({outbox,transport,intervalMs=5000,maxBackoffMs=60000,
  maxPerPass=10,schedule=setTimeout,cancel=clearTimeout}={}) {
  if(!outbox || typeof outbox.drainOne!=='function' || owners.has(outbox) ||
    !transport || typeof transport.lookup!=='function' || typeof transport.submit!=='function' ||
    !Number.isSafeInteger(intervalMs) || intervalMs<100 || intervalMs>60000 ||
    !Number.isSafeInteger(maxBackoffMs) || maxBackoffMs<intervalMs || maxBackoffMs>300000 ||
    !Number.isSafeInteger(maxPerPass) || maxPerPass<1 || maxPerPass>100 ||
    typeof schedule!=='function' || typeof cancel!=='function')throw Error('Explicit bounded sync runtime required.');
  let running=false,stopped=false,timer=null,pending=null,failures=0,lastState='idle',retryInMs=null;
  const owner={};owners.set(outbox,owner);
  function clear(){if(timer!==null){cancel(timer);timer=null;}retryInMs=null;}
  function arm(delay){
    if(!running||stopped)return;
    retryInMs=delay;
    timer=schedule(()=>{timer=null;retryInMs=null;void runOnce();},delay);
    timer?.unref?.();
  }
  function snapshot(){return Object.freeze({state:stopped?'stopped':running?'running':'ready',lastState,retryInMs});}
  function runOnce(){
    if(stopped)return Promise.resolve(snapshot());
    if(pending)return pending;
    clear();
    // Defer the first access until pending is installed: concurrent calls coalesce.
    pending=Promise.resolve().then(async()=>{
      for(let count=0;count<maxPerPass&&!stopped;count++){
        const result=await outbox.drainOne(transport);
        if(!result||!states.has(result.state))throw Error('Invalid delivery state.');
        lastState=result.state;
        if(!['saved','held'].includes(lastState))break;
      }
    }).catch(()=>{lastState='unavailable';}).then(()=>{
      pending=null;
      if(stopped){if(owners.get(outbox)===owner)owners.delete(outbox);return snapshot();}
      failures=['uncertain','unavailable','busy'].includes(lastState)?Math.min(failures+1,20):0;
      arm(Math.min(maxBackoffMs,intervalMs*2**failures));
      return snapshot();
    });
    return pending;
  }
  return Object.freeze({
    start(){if(stopped)throw Error('Stopped sync runtime cannot restart.');if(!running){running=true;if(!pending)arm(0);}return snapshot();},
    runOnce,
    status:snapshot,
    stop(){
      stopped=true;running=false;clear();
      if(pending)return pending;
      if(owners.get(outbox)===owner)owners.delete(outbox);
      return Promise.resolve(snapshot());
    },
  });
}
