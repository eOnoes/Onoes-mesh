// Attest the established IPv4 socket before HTTP receives it or writes headers.
// https://learn.microsoft.com/windows/win32/api/iphlpapi/nf-iphlpapi-getextendedtcptable
// https://learn.microsoft.com/windows/win32/api/tcpmib/ns-tcpmib-mib_tcprow_owner_pid
import net from 'node:net';
import path from 'node:path';

class PeerError extends Error {
  constructor(held=false){super('Project service connection identity unavailable or refused.');this.projectSyncHeld=held;this.projectSyncLocalBinding=held;}
}
const require=(ok,held=false)=>{if(!ok)throw new PeerError(held);};
export function validateProjectPeer(peer){
  require(peer?.constructor===Object&&Object.keys(peer).sort().join(',')==='creationTicks,pid,profileSha256,runId'&&
    Number.isSafeInteger(peer.pid)&&peer.pid>0&&peer.pid<=0xffffffff&&
    typeof peer.creationTicks==='string'&&/^[1-9][0-9]{0,19}$/.test(peer.creationTicks)&&BigInt(peer.creationTicks)<2n**64n&&
    typeof peer.runId==='string'&&/^[a-f0-9]{32}$/.test(peer.runId)&&
    typeof peer.profileSha256==='string'&&/^[a-f0-9]{64}$/.test(peer.profileSha256),true);
  return Object.freeze({...peer});
}
let pendingApi;
function api(){
  if(!pendingApi)pendingApi=(async()=>{
    require(process.platform==='win32');
    const {default:koffi}=await import('koffi');
    const kernel=koffi.load('kernel32.dll');
    const directory=kernel.func('uint32_t __stdcall GetSystemDirectoryW(void *buffer, uint32_t size)');
    const text=Buffer.alloc(65536),length=directory(text,32768);
    require(length>0&&length<32768);const system=text.subarray(0,length*2).toString('utf16le');
    require(path.win32.isAbsolute(system));
    const ip=koffi.load(path.win32.join(system,'iphlpapi.dll'));
    return {kernel,ip,
      open:kernel.func('void * __stdcall OpenProcess(uint32_t access, int inherit, uint32_t pid)'),
      close:kernel.func('int __stdcall CloseHandle(void *handle)'),
      wait:kernel.func('uint32_t __stdcall WaitForSingleObject(void *handle, uint32_t timeout)'),
      times:kernel.func('int __stdcall GetProcessTimes(void *handle, void *created, void *exited, void *kernelTime, void *userTime)'),
      tcp:ip.func('uint32_t __stdcall GetExtendedTcpTable(void *table, void *size, int order, uint32_t family, int tableClass, uint32_t reserved)')};
  })();
  return pendingApi;
}
function stamp(a,handle){
  require(a.wait(handle,0)===258);
  const created=Buffer.alloc(8),rest=Array.from({length:3},()=>Buffer.alloc(8));
  require(a.times(handle,created,...rest)!==0);return created.readBigUInt64LE().toString();
}
export async function projectProcessCreationTicks(pid){
  const a=await api(),handle=a.open(0x1000|0x100000,0,pid);require(handle);
  try{return stamp(a,handle);}finally{a.close(handle);}
}
function socketOwner(a,socket){
  for(let attempt=0;attempt<3;attempt++){
    const size=Buffer.alloc(4);require(a.tcp(null,size,0,2,5,0)===122);
    const n=size.readUInt32LE();require(n>=4&&n<=16*1024*1024);
    const table=Buffer.alloc(n),status=a.tcp(table,size,0,2,5,0);
    if(status===122)continue;
    require(status===0&&size.readUInt32LE()<=n);
    const count=table.readUInt32LE();require(count<=Math.floor((n-4)/24));
    for(let i=0;i<count;i++){
      const at=4+i*24;
      if(table.readUInt32LE(at)===5&&table.subarray(at+4,at+8).equals(Buffer.from([127,0,0,1]))&&
        table.subarray(at+12,at+16).equals(Buffer.from([127,0,0,1]))&&
        table.readUInt16BE(at+8)===socket.remotePort&&table.readUInt16BE(at+16)===socket.localPort)
        return table.readUInt32LE(at+20);
    }
    throw new PeerError();
  }
  throw new PeerError();
}
export async function openProjectPeerSocket(peer,port,{signal}={}){
  peer=validateProjectPeer(peer);require(Number.isSafeInteger(port)&&port>0&&port<65536,true);
  let socket;
  try{
    const a=await api();require(!signal?.aborted);
    socket=net.createConnection({host:'127.0.0.1',port,family:4,...(signal?{signal}:{})});
    let failure;
    socket.on('error',error=>{failure=error;});
    await new Promise((resolve,reject)=>{socket.once('connect',resolve);socket.once('error',reject);});
    require(!failure&&!socket.destroyed&&!signal?.aborted&&socket.remoteAddress==='127.0.0.1'&&socket.localAddress==='127.0.0.1');
    const handle=a.open(0x1000|0x100000,0,peer.pid);require(handle);
    try{
      require(stamp(a,handle)===peer.creationTicks,true);
      require(socketOwner(a,socket)===peer.pid,true);
      require(stamp(a,handle)===peer.creationTicks,true);
    }finally{a.close(handle);}
    require(!failure&&!socket.destroyed&&!signal?.aborted);
    return socket;
  }catch(error){socket?.destroy();if(error instanceof PeerError)throw error;throw new PeerError();}
}
