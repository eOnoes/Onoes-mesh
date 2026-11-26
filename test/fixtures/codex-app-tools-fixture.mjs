import {createInterface} from 'node:readline';
let clientRequestDeclined=false;
const emit=value=>process.stdout.write(JSON.stringify({jsonrpc:'2.0',...value})+'\n');
createInterface({input:process.stdin}).on('line',line=>{
  const request=JSON.parse(line);
  if(request.error){clientRequestDeclined=request.error.code===-32601;return;}
  if(request.method==='initialize')emit({id:request.id,result:{protocolVersion:'2025-06-18',capabilities:{tools:{}},serverInfo:{name:'synthetic-only',version:'1'}}});
  if(request.method==='tools/list')emit({id:request.id,result:{tools:['list_projects','list_threads','read_thread'].map(name=>({name,inputSchema:{type:'object'}}))}});
  if(request.method==='tools/call'){
    // Server and client request IDs occupy independent JSON-RPC directions.
    emit({id:request.id,method:'sampling/createMessage',params:{synthetic:true}});
    setTimeout(()=>emit({id:request.id,result:{content:[{type:'text',text:JSON.stringify({clientRequestDeclined,callerThreadId:request.params._meta.codex_thread_id})}],isError:false}}),40);
  }
});
