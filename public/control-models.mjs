// Shared read-only presentation. A reported resident never grants model control.
const lanes=new Map([
  ['qwen3.8-flash-next-iq3-s',{label:'Qwen3.8 Flash-Next IQ3_S',runtime:'UnbiasedStrata',port:18090}],
  ['qwen3.6-35b-a3b-ud-q6_k_xl',{label:'Qwen3.6 35B A3B Q6',runtime:'UnbiasedStrata',port:18091}],
  ['qwen3.8-27b',{label:'Qwen3.8 27B',runtime:'llama.cpp',port:8098}],
  ['nemotron-3.5-bolt-74b-a9b',{label:'Nemotron 3.5 Bolt 74B A9B',runtime:'llama.cpp',port:8099}],
]);
export function supervisorControlView(snapshot,now=Date.now()){
  const fresh=snapshot?.schemaVersion==='mesh-supervisor-observation/v1'&&snapshot.source==='local_supervisor'&&
    Number.isSafeInteger(snapshot.expiresAt)&&snapshot.expiresAt>now&&snapshot.expiresAt<=now+5000&&Array.isArray(snapshot.models);
  const rows=fresh?snapshot.models.filter(row=>lanes.has(row?.id)):[];
  const unique=new Set(rows.map(row=>row.id)).size===rows.length;
  const known=unique?rows.filter(row=>row.state==='reported_loaded'?row.loaded===true:['ready','unavailable'].includes(row.state)&&row.loaded===false):[];
  const residents=known.filter(row=>row.state==='reported_loaded'&&row.loaded===true);
  const complete=known.length===lanes.size,conflict=residents.length>1;
  const resident=!conflict&&residents.length===1?residents[0]:null;
  const empty=complete&&residents.length===0;
  const state=!fresh?'unavailable':conflict?'conflicting observations':resident?'reported loaded':empty?'none reported loaded':'unknown';
  const note=resident?'The supervisor reports this model loaded. Ownership, GPU mapping and model controls remain separately verified.':
    empty?'No supervised model is reported loaded. This is a read-only observation.':
    conflict?'The supervisor returned conflicting resident observations. Refresh status; residency is unconfirmed.':
    'Current supervised model residency is unknown. Previous model details are cleared.';
  const lane=resident&&lanes.get(resident.id);
  const models=resident?[{name:lane.label,residency:'reported_loaded'}]:[];
  return {
    engine:{name:lane?.runtime||'local model supervisor',port:lane?.port||null,source:'local_supervisor',loaded:resident?true:empty?false:null,
      modelAlias:resident?.id||null,modelShort:lane?.label||null,state,note},
    service:{id:'local-models',label:'Local model supervisor',reachable:known.length>0?true:null,loaded:resident?true:empty?false:null,
      detail:resident?lane.label+' · reported loaded':state,models,residencyKnown:complete&&!conflict},
    hints:resident||empty?[]:[note],
  };
}
