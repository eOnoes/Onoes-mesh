import {readFileSync,writeFileSync,mkdirSync,existsSync,copyFileSync} from 'node:fs';
import {createHash,randomUUID} from 'node:crypto';
import {dirname,join,resolve} from 'node:path';
import {fileURLToPath} from 'node:url';

// Preparation only: never writes the installed service or changes its task.
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const live='D:/DeepSeekHarness-TestingGrounds/Qwen3.8-Flash Testing/local-models';
const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
const expected={
  'local_supervisor.py':'719cb53c01eacc67da3a7f87162f68fb1ebb5038d25c870e5bb3ddb144f84f12',
  'supervisor_mesh_control.py':'7b823cd6a07fad21c7471142e999e3122d26c880cfbcd9c0f4acfe8cc6874116',
  'launch_local.py':'6fd787c304938a8b41a2ba74d58dcdd324ee28765bf1bb2e7105cf25e66db4a0',
};
const originals=Object.fromEntries(Object.entries(expected).map(([name,sha])=>{
  const bytes=readFileSync(join(live,name));
  if(hash(bytes)!==sha)throw Error('Installed source changed: '+name);
  return [name,bytes];
}));
const source=originals['local_supervisor.py'].toString('utf8');
const eol=source.includes('\r\n')?'\r\n':'\n';
const before=['        ready = self._wait_ready(child_port)','        self.loading = False'].join(eol);
if(source.split(before).length!==2)throw Error('Expected unique load-completion anchor');
const after=['        ready = self._wait_ready(child_port)',
  '        if ready:',
  '            # A native control load is activity even without a proxied chat.',
  '            self.last_used = time.monotonic()',
  '        self.loading = False'].join(eol);
const candidate=Buffer.from(source.replace(before,after));
const directory=join(root,'data/nemotron-supervisor-candidate',randomUUID());
mkdirSync(directory,{recursive:true});
writeFileSync(join(directory,'local_supervisor.py'),candidate,{flag:'wx'});
writeFileSync(join(directory,'supervisor_mesh_control.py'),originals['supervisor_mesh_control.py'],{flag:'wx'});
const executable='D:/models/nemotron/tools/llama-b11669-cuda12.4/llama-server.exe';
const executableSha256=hash(readFileSync(executable));
if(executableSha256!=='6a4635aeb35656153d4bfeeddf761d24ed84aada9c9108d580737cbed465141b')throw Error('Selected executable changed');
const manifest={schema:'mesh-nemotron-supervisor-candidate/v1',createdAt:new Date().toISOString(),directory,
  qualification:'PREPARED_ONLY_NOT_INSTALLED',modelId:'nemotron-3.5-bolt-74b-a9b',
  liveSource:join(live,'local_supervisor.py'),liveSourceSha256:expected['local_supervisor.py'],
  dependencySource:join(live,'launch_local.py'),dependencySha256:expected['launch_local.py'],
  executable,executableSha256,
  files:['local_supervisor.py','supervisor_mesh_control.py'].map(path=>({path,sha256:hash(readFileSync(join(directory,path)))})),
  change:'Renew idle timestamp on successful load before clearing loading; keep existing 90-minute idle policy.',
  remaining:['Isolated real ensure/watchdog regression','Explicit named-service maintenance approval',
    'Exact source-bound live requalification before ordinary controls are enabled'],
};
writeFileSync(join(directory,'manifest.json'),JSON.stringify(manifest,null,2),{flag:'wx'});
const pointer=join(root,'data/nemotron-supervisor-candidate-latest.json');
if(existsSync(pointer))copyFileSync(pointer,join(directory,'previous-candidate-pointer.json'));
writeFileSync(pointer,JSON.stringify(manifest,null,2));
console.log(JSON.stringify(manifest,null,2));
