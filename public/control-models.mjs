// Shared read-only presentation. A reported resident never grants model control.
const lanes=new Map([
  ['qwen3.8-flash-next-iq3-s',{label:'Qwen3.8 Flash-Next IQ3_S',runtime:'UnbiasedStrata',port:18090}],
  ['qwen3.6-35b-a3b-ud-q6_k_xl',{label:'Qwen3.6 35B A3B Q6',runtime:'UnbiasedStrata',port:18091}],
  ['qwen3.8-27b',{label:'Qwen3.8 27B',runtime:'llama.cpp',port:8098}],
  ['nemotron-3.5-bolt-74b-a9b',{label:'Nemotron 3.5 Bolt 74B A9B',runtime:'llama.cpp',port:8099}],
]);
export function supervisorConnectionNotice(snapshot){
  return snapshot?.schemaVersion==='mesh-supervisor-observation/v1'&&snapshot.source==='none'&&
    Array.isArray(snapshot.models)&&snapshot.models.some(row=>row?.reason==='supervisor_identity_unverified')
    ?'Model connection needs verification. Whether a model is loaded is unknown.':null;
}
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
    supervisorConnectionNotice(snapshot)||'Current supervised model residency is unknown. Previous model details are cleared.';
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

export function pixelReading(kind,label,pct,tempC = null, dom = document) {
  function el(tag, className, text) {
    const node = dom.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  const valid=Number.isFinite(pct)&&pct>=0&&pct<=100;
  const patterns={ram:['0000000000','0000000000','0111111110','0101010110','0111111110','0010101000','0000000000','0000000000','0000000000'],gpu:['0000000000','0111111110','0100110010','0101001010','0100110010','0111111110','0010101000','0000000000','0000000000'],cpu:['0010101000','0111111110','1100000011','0101111010','1101001011','0101111010','1100000011','0111111110','0010101000']};
  const line=el('div','pixel-reading'),icon=el('span','pixel-icon');icon.setAttribute?.('aria-hidden','true');
  for(const bit of patterns[kind].join(''))icon.append(el('i',bit==='1'?'is-on':null));
  const copy=el('div','pixel-reading-copy'),head=el('div','pixel-reading-head');
  head.append(el('span',null,label),el('strong',null,valid?`${Math.round(pct)}%`:'Unknown'));
  const bar=el('div','pixel-reading-bar');bar.setAttribute?.('aria-hidden','true');
  for(let i=0;i<10;i++)bar.append(el('i',valid&&i<Math.ceil(pct/10)?'is-on':null));
  let visual = icon;
  if (kind === 'gpu' || kind === 'cpu') {
    const measured = Number.isFinite(tempC) && tempC >= 0 && tempC <= 150;
    visual = el('span', 'thermal-gauge');
    if (measured) {
      const segments = Math.min(8, Math.ceil(tempC * 8 / 100));
      visual.className += ' thermal-' + segments;
      visual.title = 'Temperature scale 0–100 °C';
    }
    visual.append(icon);
    copy.append(head, bar, el('small', 'thermal-caption',
      measured ? Math.round(tempC) + ' °C' : 'Temperature unavailable'));
  } else {
    copy.append(head, bar);
  }
  line.append(visual, copy);
  return line;
}
