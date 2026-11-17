// Frozen local controller code only. No app-store, task or process mutation.
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
import {dirname,isAbsolute,join,relative,resolve,sep} from 'node:path';
import {existsSync,lstatSync,mkdirSync,readFileSync,readdirSync,realpathSync,writeFileSync} from 'node:fs';

export const legacyControllerCodeFiles=Object.freeze([
  'integrations/legacy-recovery-operator.mjs','integrations/legacy-recovery-plan.mjs',
  'lib/command-execution.mjs','lib/command-proposals.mjs','lib/database-identity.mjs',
  'lib/legacy-controller-bundle.mjs','lib/native-writer-observation.mjs','lib/nims-store.mjs',
  'lib/pc-recovery-evidence.mjs','lib/task-store.mjs','lib/windows-native-maintenance.mjs',
  'lib/workroom-assignment.mjs','lib/workroom-automation-store.mjs','lib/workroom-card-state.mjs',
  'lib/workroom-claim-policy.mjs','lib/workroom-dispatch-barrier.mjs','lib/workroom-flow.mjs',
  'lib/workroom-legacy-authorization.mjs','lib/workroom-legacy-console.mjs','lib/workroom-legacy-evidence.mjs',
  'lib/workroom-legacy-recovery.mjs','lib/workroom-local-sessions.mjs','lib/workroom-native-receipts.mjs',
  'lib/workroom-plan.mjs','lib/workroom-rook.mjs','lib/workroom-updates.mjs','lib/workroom-writer-states.mjs',
  'lib/workroom.mjs','public/lead-policy.mjs',
]);
const roots=['node_modules/koffi/','node_modules/@koromix/koffi-win32-x64/'];
const digest=body=>createHash('sha256').update(body).digest('hex');
const requireValue=(ok,message)=>{if(!ok)throw Error(message);};
const key=p=>process.platform==='win32'?p.toLowerCase():p;
const physical=p=>{
  requireValue(typeof p==='string'&&isAbsolute(p),'An absolute controller path is required.');
  const result=realpathSync.native(p);
  requireValue(key(result)===key(resolve(p))&&!lstatSync(p).isSymbolicLink(),'Controller aliases are refused.');
  return result;
};
function bytes(path,max=16777216){
  physical(path);const before=lstatSync(path,{bigint:true});
  requireValue(before.isFile()&&before.size<=BigInt(max),'An ordinary bounded controller file is required.');
  const body=readFileSync(path),after=lstatSync(path,{bigint:true});
  requireValue(before.dev===after.dev&&before.ino===after.ino&&before.birthtimeNs===after.birthtimeNs&&before.size===after.size,'Controller file changed while reading.');
  return body;
}
function filesUnder(root){
  physical(root);const paths=[];
  for(const item of readdirSync(root,{withFileTypes:true})){
    const path=join(root,item.name);physical(path);
    requireValue(!item.isSymbolicLink(),'Controller links are refused.');
    if(item.isDirectory())paths.push(...filesUnder(path));
    else{requireValue(item.isFile(),'Unexpected controller file kind.');paths.push(path);}
  }
  return paths;
}
const runtimeFile=path=>/\.(?:cjs|mjs|js|json|node)$/i.test(path)||/^licen[sc]e(?:\..*)?$/i.test(path.split(/[\\/]/).at(-1));
const rootFiles=[...legacyControllerCodeFiles,'config/commands.json','config/nodes.json','package.json','package-lock.json'];

export function prepareFrozenLegacyController({sourceRoot,destinationRoot}){
  requireValue(process.platform==='win32'&&process.arch==='x64','Qualified Windows x64 controller required.');
  sourceRoot=physical(sourceRoot);const data=physical(join(sourceRoot,'data'));
  requireValue(isAbsolute(destinationRoot)&&key(resolve(destinationRoot)).startsWith(key(data+sep))&&
    /^mesh-legacy-controller-[A-Za-z0-9-]+$/.test(relative(data,destinationRoot))&&!existsSync(destinationRoot),
  'Use a new controller folder directly inside workspace data.');
  const req=createRequire(join(sourceRoot,'package.json'));
  const koffi=dirname(realpathSync.native(req.resolve('koffi')));
  const native=dirname(realpathSync.native(createRequire(join(koffi,'package.json')).resolve('@koromix/koffi-win32-x64')));
  for(const pkg of [koffi,native])requireValue(JSON.parse(bytes(join(pkg,'package.json'))).version==='3.3.8','Reviewed Koffi package version required.');
  const inputs=rootFiles.map(path=>[path,join(sourceRoot,path)]);
  for(const [index,pkg]of [koffi,native].entries())for(const path of filesUnder(pkg).filter(runtimeFile))
    inputs.push([roots[index]+relative(pkg,path).split(sep).join('/'),path]);
  requireValue(inputs.length<=96,'Controller file set exceeds its reviewed bound.');
  mkdirSync(destinationRoot);destinationRoot=physical(destinationRoot);
  const files=[];
  for(const [path,source]of inputs){
    const body=bytes(source),target=join(destinationRoot,path);mkdirSync(dirname(target),{recursive:true});
    writeFileSync(target,body,{flag:'wx'});requireValue(digest(bytes(target))===digest(body)&&digest(bytes(source))===digest(body),'Controller copy changed.');
    files.push({path,sha256:digest(body)});
  }
  const node=physical(process.execPath);
  const manifest={schema:'mesh/legacy-controller-bundle/v1',root:destinationRoot,sourceRoot,platform:process.platform,arch:process.arch,
    entry:'integrations/legacy-recovery-operator.mjs',node:{path:node,sha256:digest(bytes(node,134217728))},files:files.sort((a,b)=>a.path.localeCompare(b.path))};
  const path=join(destinationRoot,'CONTROLLER-MANIFEST.json');writeFileSync(path,JSON.stringify(manifest,null,2)+'\n',{flag:'wx'});
  const descriptor={path,sha256:digest(bytes(path))};
  bindFrozenLegacyController(descriptor,join(destinationRoot,manifest.entry));
  return {descriptor,entry:join(destinationRoot,manifest.entry),files:files.length,activated:false};
}

export function bindFrozenLegacyController(descriptor,actualEntry){
  requireValue(descriptor&&Object.keys(descriptor).sort().join(',')==='path,sha256'&&/^[a-f0-9]{64}$/.test(descriptor.sha256),'Exact controller manifest and SHA256 required.');
  const raw=bytes(descriptor.path,1048576);requireValue(digest(raw)===descriptor.sha256,'Controller manifest changed.');
  const m=JSON.parse(raw);const root=physical(m.root);
  requireValue(m.schema==='mesh/legacy-controller-bundle/v1'&&m.platform===process.platform&&m.arch===process.arch&&
    m.platform==='win32'&&m.arch==='x64'&&key(physical(descriptor.path))===key(join(root,'CONTROLLER-MANIFEST.json'))&&
    m.entry==='integrations/legacy-recovery-operator.mjs'&&key(physical(actualEntry))===key(join(root,m.entry))&&
    key(physical(process.execPath))===key(m.node?.path)&&digest(bytes(process.execPath,134217728))===m.node.sha256&&
    Array.isArray(m.files)&&m.files.length<=96,'Controller runtime binding changed.');
  for(const [name,value]of Object.entries(process.env))if(value&&(['NODE_OPTIONS','NODE_PATH'].includes(name.toUpperCase())||name.toUpperCase().startsWith('KOFFI_')))
    throw Error('Controller loader overrides are refused.');
  const seen=new Set(),sources={frozenControllerManifest:descriptor.path,frozenControllerNode:physical(process.execPath)};
  for(const [index,file]of m.files.entries()){
    requireValue(typeof file.path==='string'&&/^[A-Za-z0-9_@./-]+$/.test(file.path)&&
      !file.path.split('/').some(p=>!p||p==='.'||p==='..')&&!seen.has(file.path)&&
      (rootFiles.includes(file.path)||roots.some(p=>file.path.startsWith(p)&&runtimeFile(file.path)))&&/^[a-f0-9]{64}$/.test(file.sha256),'Invalid controller file manifest.');
    const path=join(root,file.path);requireValue(digest(bytes(path))===file.sha256,'Frozen controller source changed.');
    seen.add(file.path);sources['frozenControllerFile'+String(index).padStart(3,'0')]=path;
  }
  requireValue(rootFiles.every(p=>seen.has(p))&&seen.has('node_modules/koffi/package.json')&&
    seen.has('node_modules/@koromix/koffi-win32-x64/win32_x64/koffi.node'),'Incomplete controller code/native closure.');
  const actual=filesUnder(root).map(p=>relative(root,p).split(sep).join('/')).filter(p=>p!=='CONTROLLER-MANIFEST.json');
  requireValue(actual.length===seen.size&&actual.every(p=>seen.has(p)),'Unreviewed controller files appeared.');
  return sources;
}
