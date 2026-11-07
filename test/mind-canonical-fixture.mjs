import {spawn} from 'node:child_process';
import {once} from 'node:events';
export async function canonicalMindFixture(source,{bound=false}={}){
 if(!source)throw Error('Set MESH_MIND_SOURCE to the canonical Onoes-Mind checkout for this explicit integration test.');
 const code=`import sys,json,tempfile
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from onoes_mind import Ledger
from onoes_mind.recall_http import RecallServer
from onoes_mind.recall_binding import RecallBinding,BoundRecallLedger,prepare_store_identity,prepare_mesh_principal,issue_mesh_recall_credential
folder=tempfile.TemporaryDirectory()
path=(Path(folder.name)/'synthetic-mesh.sqlite').resolve()
l=Ledger(path)
for p in ('echo','tripp','operator'): l.create_principal(p); l.issue_credential(p,p+'-synthetic-mesh-token')
for p,claim in [('echo','meshfixture Echo private'),('tripp','meshfixture HIDDEN Tripp private'),('operator','meshfixture shared <script>not executable</script>')]:
 l.remember(p+'-synthetic-mesh-token',{'event_id':p+'-one','kind':'project_fact','claim':claim,'project_id':'mesh-recall-fixture','requested_visibility':'shared' if p=='operator' else 'private','evidence_refs':[{'type':'fixture','ref':'synthetic-memory.md','content_hash':'sha256:synthetic'}]})
reader=l
token='echo-synthetic-mesh-token'
if sys.argv[2]=='bound':
 store_id=prepare_store_identity(l,environment='synthetic',authority_ref='fixture:owner')
 prepare_mesh_principal(l,scope_id='project/onoes-mind/shared')
 token=issue_mesh_recall_credential(l,token='service-synthetic-mesh-token')
 st=path.stat()
 binding=RecallBinding(str(path),store_id,'synthetic','fixture:owner','project/onoes-mind/shared',st.st_dev,st.st_ino,'fixture:custodian','fixture:revoke','fixture:review')
 reader=BoundRecallLedger(path,binding=binding)
s=RecallServer(reader);s.start()
print(json.dumps({'baseUrl':'http://127.0.0.1:'+str(s.address[1]),'token':token}),flush=True)
try: sys.stdin.readline()
finally:
 s.close()
 if reader is not l: reader.close()
 l.close();folder.cleanup()
`;
 const child=spawn('C:/Python314/python.exe',['-B','-c',code,source,bound?'bound':'unbound'],{windowsHide:true,stdio:['pipe','pipe','pipe']});const closed=once(child,'close');let output='',errors='';child.stderr.on('data',b=>errors+=b);
 let timer;
 try{
  const info=await new Promise((resolve,reject)=>{timer=setTimeout(()=>reject(Error('Canonical fixture startup timed out')),5000);child.once('error',reject);child.once('exit',()=>reject(Error('Canonical fixture exited before startup')));child.stdout.on('data',b=>{output+=b;if(output.length>4096)return reject(Error('Fixture output exceeded bound'));const line=output.split('\n').map(line=>line.trim()).find(x=>x.startsWith('{')&&x.endsWith('}'));if(line)resolve(JSON.parse(line));});});
  return {...info,pid:child.pid,async close(){child.stdin.end('stop\n');const result=await Promise.race([closed,new Promise(resolve=>setTimeout(()=>resolve(null),4000).unref())]);if(!result){child.kill();await closed;throw Error('Owned fixture did not stop gracefully');}if(result[0]!==0)throw Error('Owned canonical fixture failed');}};
 }catch(error){child.kill();await closed.catch(()=>{});throw error;}finally{clearTimeout(timer);}
}
