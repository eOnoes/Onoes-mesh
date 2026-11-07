import {spawn} from 'node:child_process';
import {once} from 'node:events';
export async function canonicalMindFixture(source){
 if(!source)throw Error('Set MESH_MIND_SOURCE to the canonical Onoes-Mind checkout for this explicit integration test.');
 const code=`import sys,json\nsys.path.insert(0,sys.argv[1])\nfrom onoes_mind import Ledger\nfrom onoes_mind.recall_http import RecallServer\nl=Ledger()\nfor p in ('echo','tripp','operator'): l.create_principal(p); l.issue_credential(p,p+'-synthetic-mesh-token')\nfor p,claim in [('echo','meshfixture Echo private'),('tripp','meshfixture HIDDEN Tripp private'),('operator','meshfixture shared <script>not executable</script>')]:\n l.remember(p+'-synthetic-mesh-token',{'event_id':p+'-one','kind':'project_fact','claim':claim,'project_id':'mesh-recall-fixture','requested_visibility':'shared' if p=='operator' else 'private','evidence_refs':[{'type':'fixture','ref':'synthetic-memory.md','content_hash':'sha256:synthetic'}]})\ns=RecallServer(l);s.start()\nprint(json.dumps({'baseUrl':'http://127.0.0.1:'+str(s.address[1]),'token':'echo-synthetic-mesh-token'}),flush=True)\ntry: sys.stdin.readline()\nfinally: s.close();l.close()\n`;
 const child=spawn('C:/Python314/python.exe',['-B','-c',code,source],{windowsHide:true,stdio:['pipe','pipe','pipe']});const closed=once(child,'close');let output='',errors='';child.stderr.on('data',b=>errors+=b);
 let timer;
 try{
  const info=await new Promise((resolve,reject)=>{timer=setTimeout(()=>reject(Error('Canonical fixture startup timed out')),5000);child.once('error',reject);child.once('exit',()=>reject(Error('Canonical fixture exited before startup')));child.stdout.on('data',b=>{output+=b;if(output.length>4096)return reject(Error('Fixture output exceeded bound'));const line=output.split('\n').map(line=>line.trim()).find(x=>x.startsWith('{')&&x.endsWith('}'));if(line)resolve(JSON.parse(line));});});
  return {...info,pid:child.pid,async close(){child.stdin.end('stop\n');const result=await Promise.race([closed,new Promise(resolve=>setTimeout(()=>resolve(null),4000).unref())]);if(!result){child.kill();await closed;throw Error('Owned fixture did not stop gracefully');}if(result[0]!==0)throw Error('Owned canonical fixture failed');}};
 }catch(error){child.kill();await closed.catch(()=>{});throw error;}finally{clearTimeout(timer);}
}
