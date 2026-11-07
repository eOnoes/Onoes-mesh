export function createSessionEntry({readPolicy,start,ready,available,onMode,onError,setTimer=setTimeout,clearTimer=clearTimeout}){
  let automatic,flight=null,attempted=false,paused=false,epoch=0,timer;
  const clear=()=>{if(timer!==undefined)clearTimer(timer);timer=undefined;};
  function recover(){
    if(paused||!available()||attempted)return Promise.resolve();
    if(flight)return flight;
    const current=epoch;
    const operation=(async()=>{
      try{
        if(automatic===undefined){const policy=await readPolicy();if(current!==epoch||paused||!available())return;automatic=policy?.automaticSession===true;onMode(automatic);}
        if(!automatic||ready()||current!==epoch||!available())return;
        attempted=true;await start();
      }catch(error){if(current===epoch&&!paused&&available()){attempted=true;onError(error);}}
    })();
    flight=operation;operation.finally(()=>{if(flight===operation)flight=null;});return operation;
  }
  return {
    recover,
    resume(){epoch++;flight=null;attempted=false;return recover();},
    suspend(){epoch++;flight=null;attempted=false;clear();},
    pause(){paused=true;this.suspend();},
    retry(){paused=false;automatic=undefined;return this.resume();},
    verified(expiresAt){attempted=false;clear();if(automatic&&Number.isSafeInteger(expiresAt))timer=setTimer(()=>{timer=undefined;this.resume();},Math.max(0,expiresAt-Date.now()+25));},
  };
}

// Same-origin, RAM-only proof handoff for an explicit connection in another tab.
// Receiving a candidate is not admission: app.js must verify it with the server.
export function createAdmissionPeers({readProof,Channel=globalThis.BroadcastChannel,now=Date.now,timeoutMs=250}={}){
  let channel;try{channel=new Channel('mesh.admission-peer.v1');}catch{return {request:async()=>null,close(){}};}
  const pending=new Map();let closed=false;
  const valid=proof=>proof&&Object.keys(proof).sort().join(',')==='csrfToken,expiresAt'&&typeof proof.csrfToken==='string'&&/^[A-Za-z0-9_-]{43}$/.test(proof.csrfToken)&&Number.isSafeInteger(proof.expiresAt)&&proof.expiresAt>now()&&proof.expiresAt<=now()+86400000;
  channel.onmessage=event=>{
    const data=event.data;
    if(closed||!data||typeof data.requestId!=='string'||!/^[0-9a-f-]{36}$/.test(data.requestId))return;
    if(data.type==='request'&&Object.keys(data).sort().join(',')==='requestId,type'){
      let proof;try{proof=readProof?.();}catch{return;}
      if(valid(proof))channel.postMessage({type:'candidate',requestId:data.requestId,proof:{csrfToken:proof.csrfToken,expiresAt:proof.expiresAt}});
    }else if(data.type==='candidate'&&Object.keys(data).sort().join(',')==='proof,requestId,type'&&valid(data.proof)){
      pending.get(data.requestId)?.({csrfToken:data.proof.csrfToken,expiresAt:data.proof.expiresAt});
    }
  };
  return {
    request(){
      if(closed)return Promise.resolve(null);
      return new Promise(resolve=>{
        const requestId=crypto.randomUUID();let timer;
        const finish=value=>{if(!pending.delete(requestId))return;clearTimeout(timer);resolve(value);};
        pending.set(requestId,finish);timer=setTimeout(()=>finish(null),timeoutMs);
        try{channel.postMessage({type:'request',requestId});}catch{finish(null);}
      });
    },
    close(){closed=true;channel.onmessage=null;channel.close();for(const finish of [...pending.values()])finish(null);}
  };
}
