import nodeTest from 'node:test';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {existsSync,readFileSync,realpathSync,rmSync,writeFileSync} from 'node:fs';
import {join,resolve,sep} from 'node:path';
import {execFileSync} from 'node:child_process';
import {prepareFrozenLegacyController,bindFrozenLegacyController,legacyControllerCodeFiles} from '../lib/legacy-controller-bundle.mjs';
const test=process.platform==='win32'&&process.arch==='x64'?nodeTest:nodeTest.skip;
function fixture(){
 const sourceRoot=realpathSync.native(resolve('.')),data=realpathSync.native(join(sourceRoot,'data'));
 const destinationRoot=join(data,'mesh-legacy-controller-test-'+randomUUID());
 const bundle=prepareFrozenLegacyController({sourceRoot,destinationRoot});
 return {sourceRoot,destinationRoot,bundle,close(){
  const target=realpathSync.native(destinationRoot);assert.ok(target.startsWith(data+sep));assert.ok(target.split(sep).at(-1).startsWith('mesh-legacy-controller-test-'));
  rmSync(target,{recursive:true});
 }};
}
test('a separate frozen controller has its complete code and native package with no links to mutable node_modules',()=>{
 const f=fixture();
 try{
  const files=bindFrozenLegacyController(f.bundle.descriptor,f.bundle.entry);
  const manifest=JSON.parse(readFileSync(f.bundle.descriptor.path,'utf8'));
  assert.ok(legacyControllerCodeFiles.every(p=>manifest.files.some(x=>x.path===p)));
  assert.ok(manifest.files.some(x=>x.path.endsWith('koffi.node')));
  assert.equal(Object.keys(files).length,manifest.files.length+2);
  assert.equal(f.bundle.activated,false);
  assert.throws(()=>prepareFrozenLegacyController({sourceRoot:f.sourceRoot,destinationRoot:f.destinationRoot}),/new controller folder/);
 }finally{f.close();}
});
test('changed descriptor, wrong entry, missing code and extra unreviewed code all refuse binding',()=>{
 const f=fixture();
 try{
  assert.throws(()=>bindFrozenLegacyController({...f.bundle.descriptor,sha256:'0'.repeat(64)},f.bundle.entry),/manifest changed/);
  assert.throws(()=>bindFrozenLegacyController(f.bundle.descriptor,join(f.sourceRoot,'integrations/legacy-recovery-operator.mjs')),/runtime binding/);
  const source=join(f.destinationRoot,'lib/workroom-legacy-evidence.mjs'),original=readFileSync(source);
  writeFileSync(source,Buffer.concat([original,Buffer.from('\n// changed\n')]));
  assert.throws(()=>bindFrozenLegacyController(f.bundle.descriptor,f.bundle.entry),/source changed/);writeFileSync(source,original);
  const extra=join(f.destinationRoot,'unreviewed.mjs');writeFileSync(extra,'throw Error("unreviewed")');
  assert.throws(()=>bindFrozenLegacyController(f.bundle.descriptor,f.bundle.entry),/Unreviewed controller/);
 }finally{f.close();}
});
test('fresh child imports the frozen controller and uses its own native addon and real disposable read barriers',()=>{
 const f=fixture();
 try{
  const code=`import {pathToFileURL} from 'node:url';import {createRequire} from 'node:module';
   import {join,sep} from 'node:path';import {realpathSync,mkdtempSync,writeFileSync,rmSync} from 'node:fs';
   import {tmpdir} from 'node:os';import {createServer} from 'node:net';
   const root=${JSON.stringify(f.destinationRoot)},descriptor=${JSON.stringify(f.bundle.descriptor)},entry=${JSON.stringify(f.bundle.entry)};
   await import(pathToFileURL(entry));
   const {bindFrozenLegacyController}=await import(pathToFileURL(join(root,'lib/legacy-controller-bundle.mjs')));
   const native=await import(pathToFileURL(join(root,'lib/windows-native-maintenance.mjs')));
   const sources=bindFrozenLegacyController(descriptor,entry);
   const base=realpathSync.native(tmpdir()),dir=realpathSync.native(mkdtempSync(join(base,'mesh-frozen-native-')));
   if(!dir.startsWith(base+sep))throw Error('Unsafe temp path');
   const lock=join(dir,'gateway.lock');writeFileSync(lock,'Synthetic lock');let lease,barrier;
   try{
    const seed=createServer();await new Promise(r=>seed.listen(0,'127.0.0.1',r));const port=seed.address().port;await new Promise(r=>seed.close(r));
    if([3081,4123,4320,8452,8453,8642,8787,8098,18090,18091].includes(port))throw Error('Protected fixture port');
    lease=await native.holdWindowsNativeMaintenance({profileLocks:[lock],endpoints:[['127.0.0.1',port],['::1',port]]});
    barrier=await native.holdWindowsFileReadBarrier([...new Set(Object.values(sources))]);
    const req=createRequire(join(root,'package.json')),cached=Object.keys(req.cache);
    if(!cached.some(p=>p.endsWith('koffi.node'))||!cached.every(p=>p.toLowerCase().startsWith((root+sep).toLowerCase())))throw Error('Native dependency escaped bundle');
    console.log(JSON.stringify({nativeVersion:req('koffi').version,allNativeLoadsInsideBundle:true,readBarrierFiles:Object.keys(sources).length,liveStoreOpened:false}));
   }finally{barrier?.release();lease?.release();rmSync(dir,{recursive:true});}`;
  const env={...process.env};delete env.NODE_OPTIONS;delete env.NODE_PATH;
  const output=execFileSync(process.execPath,['--input-type=module','-e',code],{cwd:f.sourceRoot,env,windowsHide:true,timeout:15000,encoding:'utf8'});
  const result=JSON.parse(output.trim());assert.equal(result.nativeVersion,'3.3.8');assert.equal(result.allNativeLoadsInsideBundle,true);assert.equal(result.liveStoreOpened,false);
 }finally{f.close();}
});
