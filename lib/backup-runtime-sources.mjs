import {createHash} from 'node:crypto';
import {readFileSync,readdirSync,lstatSync,realpathSync} from 'node:fs';
import {resolve,relative,isAbsolute,extname,sep} from 'node:path';

const digest=path=>createHash('sha256').update(readFileSync(path)).digest('hex');
const integrationExtensions=new Set(['.mjs','.js','.cjs','.py','.ps1','.vbs','.cmd']);
const sourceDirectories=new Set(['public','lib','shared','config','scripts','integrations']);
const samePath=(a,b)=>process.platform==='win32'?a.toLowerCase()===b.toLowerCase():a===b;

function sourcePath(root,name,directory=false){
  if(typeof name!=='string'||isAbsolute(name))throw Error('Archive source must be a relative app path.');
  const target=resolve(root,name),local=relative(root,target);
  if(!local||local==='..'||local.startsWith('..'+sep)||isAbsolute(local))throw Error('Archive source outside app root.');
  let current=root,info;
  const parts=local.split(sep);
  for(let i=0;i<parts.length;i++){
    current=resolve(current,parts[i]);info=lstatSync(current);
    if(info.isSymbolicLink())throw Error('Source link refused: '+name);
    if(i<parts.length-1&&!info.isDirectory())throw Error('Source parent must be a directory.');
  }
  if(directory?!info.isDirectory():!info.isFile())throw Error(directory?'Source must be a directory.':'Source must be a regular file.');
  return target;
}

export function collectRuntimeBackupSources(root,initialEntries,{profilePath,profileSha256}={}){
  root=resolve(root);
  if(!lstatSync(root).isDirectory()||lstatSync(root).isSymbolicLink()||!samePath(root,realpathSync.native(root)))throw Error('Linked or non-directory app root refused.');
  const entries=new Set();
  for(const name of initialEntries)entries.add(relative(root,sourcePath(root,name)).split(sep).join('/'));
  for(const item of readdirSync(sourcePath(root,'integrations',true),{withFileTypes:true})){
    if(item.isSymbolicLink())throw Error('Integration source symlink refused: '+item.name);
    if(item.isFile()&&integrationExtensions.has(extname(item.name).toLowerCase()))entries.add('integrations/'+item.name);
  }
  let coverage={provided:false};
  if(profilePath){
    if(!/^[a-f0-9]{64}$/.test(profileSha256||'')||digest(profilePath)!==profileSha256)throw Error('Exact runtime profile hash required.');
    const profile=JSON.parse(readFileSync(profilePath,'utf8'));
    if(typeof profile?.workspace!=='string'||!isAbsolute(profile.workspace)||!samePath(resolve(profile.workspace),root)||!profile.sourceHashes||Array.isArray(profile.sourceHashes))throw Error('Runtime profile does not match this app root.');
    const required=[];
    for(const [source,want] of Object.entries(profile.sourceHashes)){
      if(!isAbsolute(source))throw Error('Runtime source paths must be absolute.');
      const name=relative(root,resolve(source)).split(sep).join('/');
      if(name==='..'||name.startsWith('../')||isAbsolute(name))continue;
      if(!sourceDirectories.has(name.split('/')[0])&&!['server.mjs','serve.mjs','package.json'].includes(name))throw Error('Runtime manifest selects a non-source app path.');
      const target=sourcePath(root,name);
      if(!/^[a-f0-9]{64}$/.test(want)||digest(target)!==want)throw Error('Declared runtime source changed: '+name);
      entries.add(name);required.push(name);
    }
    if(!required.length)throw Error('Runtime profile declared no app source files.');
    coverage={provided:true,profileSha256,requiredAppFiles:required.length,allIncluded:true,profileOrCredentialsArchived:false};
  }
  return {entries:[...entries].sort(),coverage};
}
