import os from 'node:os';

export function sampleCpuTimes(readCpus=os.cpus) {
  try {
    const cpus=readCpus();
    if(!Array.isArray(cpus)||!cpus.length)return null;
    let idle=0,total=0;
    for(const cpu of cpus){
      const times=['user','nice','sys','idle','irq'].map(key=>cpu?.times?.[key]);
      if(times.some(value=>!Number.isFinite(value)||value<0))return null;
      idle+=cpu.times.idle;total+=times.reduce((sum,value)=>sum+value,0);
    }
    return Number.isFinite(idle)&&Number.isFinite(total)?{count:cpus.length,idle,total}:null;
  }catch{return null;}
}

export function cpuLoadPercent(before,after) {
  if(!before||!after||!Number.isInteger(before.count)||before.count<1||before.count!==after.count)return null;
  if([before.idle,before.total,after.idle,after.total].some(value=>!Number.isFinite(value)||value<0))return null;
  const total=after.total-before.total,idle=after.idle-before.idle;
  if(total<=0||idle<0||idle>total)return null;
  return Math.round(1000*(1-idle/total))/10;
}
