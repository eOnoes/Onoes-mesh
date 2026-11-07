// Fixed nvidia-smi --query-gpu projection; device totals, never model attribution.
export function parseGpuMetrics(output){
  if(typeof output!=='string'||output.length>4096)return null;
  const rows=output.trim().split(/\r?\n/).filter(Boolean);
  if(rows.length!==1)return null; // Do not silently blend/select multiple GPUs.
  const fields=rows[0].split(',').map(value=>value.trim());
  if(fields.length!==10||!fields[0]||fields[0].length>256)return null;
  const number=(index,max=Infinity)=>{
    const raw=fields[index];if(!/^\d+(?:\.\d+)?$/.test(raw))return null;
    const value=Number(raw);return Number.isFinite(value)&&value<=max?value:null;
  };
  const total=number(2)>0?number(2):null;
  let used=number(1);if(total!==null&&used!==null&&used>total)used=null;
  return {name:fields[0],scope:'device',attribution:'unverified',
    vramUsedMiB:used,vramTotalMiB:total,vramPct:used!==null&&total!==null?Math.round(1000*used/total)/10:null,
    utilPct:number(3,100),powerW:number(4),powerLimitW:number(5)>0?number(5):null,
    tempC:number(6),fanPct:number(7,100),clockMHz:number(8),memClockMHz:number(9)};
}
