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
