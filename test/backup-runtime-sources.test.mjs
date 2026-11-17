import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdtempSync,mkdirSync,writeFileSync,readFileSync,rmSync,realpathSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve,sep} from 'node:path';
import {collectRuntimeBackupSources} from '../lib/backup-runtime-sources.mjs';

const hash=path=>createHash('sha256').update(readFileSync(path)).digest('hex');
function fixture(t){
  const directory=realpathSync.native(mkdtempSync(join(tmpdir(),'mesh-backup-runtime-')));
  const root=join(directory,'app');mkdirSync(join(root,'integrations','nested'),{recursive:true});mkdirSync(join(root,'data'));
  const files={'server.mjs':'export const app = true;','package.json':'{"type":"module"}','integrations/new-project-bridge.mjs':'export const bridge = true;','integrations/reader.py':'# reader source','integrations/nested/adapter.mjs':'export const adapter = true;','integrations/notes.txt':'not runtime code','data/private.json':'{"synthetic":true}'};
  for(const [path,body]of Object.entries(files))writeFileSync(join(root,path),body);
  const profilePath=join(directory,'runtime-profile.json');
  function profile(overrides={}){
    const sourceHashes=Object.fromEntries(['server.mjs','package.json','integrations/nested/adapter.mjs'].map(p=>[join(root,p),hash(join(root,p))]));
    writeFileSync(profilePath,JSON.stringify({workspace:root,sourceHashes,...overrides}));return {profilePath,profileSha256:hash(profilePath)};
  }
  t.after(()=>{const parent=realpathSync.native(tmpdir())+sep;if(!directory.startsWith(parent)||!directory.split(sep).at(-1).startsWith('mesh-backup-runtime-'))throw Error('Fixture cleanup leaves its owned root');rmSync(directory,{recursive:true});});
  return {root,profilePath,profile};
}
test('new root-level bridge and Python runtime sources are included without another hand-maintained entry',t=>{
  const f=fixture(t),initial=['server.mjs'];const result=collectRuntimeBackupSources(f.root,initial);
  assert(result.entries.includes('integrations/new-project-bridge.mjs'));assert(result.entries.includes('integrations/reader.py'));assert(!result.entries.includes('integrations/notes.txt'));assert.deepEqual(initial,['server.mjs']);assert.equal(result.coverage.provided,false);
});
test('an exact pinned profile adds nested dependencies and package metadata, without archiving the profile',t=>{
  const f=fixture(t);const result=collectRuntimeBackupSources(f.root,['server.mjs','server.mjs'],f.profile());
  assert(result.entries.includes('integrations/nested/adapter.mjs'));assert(result.entries.includes('package.json'));assert.equal(result.entries.filter(x=>x==='server.mjs').length,1);assert(!result.entries.includes('runtime-profile.json'));assert.equal(result.coverage.requiredAppFiles,3);assert.equal(result.coverage.profileOrCredentialsArchived,false);
});
test('changed profile bytes, another workspace, and stale declared source are rejected',t=>{
  const f=fixture(t),ref=f.profile();writeFileSync(f.profilePath,readFileSync(f.profilePath)+' ');assert.throws(()=>collectRuntimeBackupSources(f.root,[],ref),/Exact runtime profile/);
  assert.throws(()=>collectRuntimeBackupSources(f.root,[],f.profile({workspace:join(f.root,'different')})),/does not match/);
  const current=f.profile();writeFileSync(join(f.root,'server.mjs'),'changed source');assert.throws(()=>collectRuntimeBackupSources(f.root,[],current),/Declared runtime source changed/);
});
test('data files cannot be admitted as source and external dependencies are excluded from this app archive',t=>{
  const f=fixture(t);assert.throws(()=>collectRuntimeBackupSources(f.root,[],f.profile({sourceHashes:{[join(f.root,'data/private.json')]:hash(join(f.root,'data/private.json'))}})),/non-source app path/);
  const external=join(resolve(f.root,'..'),'external-memory.json');writeFileSync(external,'synthetic external data');
  const ref=f.profile({sourceHashes:{[join(f.root,'server.mjs')]:hash(join(f.root,'server.mjs')),[external]:hash(external)}});const result=collectRuntimeBackupSources(f.root,[],ref);assert(!result.entries.some(x=>x.includes('external-memory')));assert.equal(result.coverage.requiredAppFiles,1);
});
