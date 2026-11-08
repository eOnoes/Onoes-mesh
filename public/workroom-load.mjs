// Saved cards do not depend on optional Relay/Codex connection observations.
export function createBoardLoader({request,onBoard,onAgents}) {
  let epoch=0,reads=0,peerFlight=null;
  function clear(){epoch++;reads++;peerFlight=null;}
  async function load(){
    const session=epoch,read=++reads;
    const result=await request('/api/workroom');
    if(session!==epoch||read!==reads)return;
    if(!Array.isArray(result?.tasks))throw Error('Saved tasks unavailable.');
    onBoard(result);
    if(!peerFlight){
      const flight={};peerFlight=flight;
      flight.promise=Promise.resolve().then(()=>request('/api/relay/native/api/agents'))
        .then(agents=>({agents:Array.isArray(agents)?agents:[],available:Array.isArray(agents)}),()=>({agents:[],available:false}))
        .finally(()=>{if(peerFlight===flight)peerFlight=null;});
    }
    // Do not hold cards, editing or navigation hostage to a slow peer read.
    void peerFlight.promise.then(value=>{
      if(session===epoch&&read===reads)onAgents(value.agents,value.available);
    }).catch(()=>{});
    return result;
  }
  return {load,clear};
}
