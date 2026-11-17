import {createHash} from 'node:crypto';
import {readFileSync,readdirSync} from 'node:fs';
import {resolve,relative,isAbsolute,extname,sep} from 'node:path';

const digest=path=>createHash('sha256').update(readFileSync(path)).digest('hex');
const integrationExtensions=new Set(['.mjs','.js','.cjs','.py','.ps1','.vbs','.cmd']);
const sourceDirectories=new Set(['public','lib','shared','config','scripts','integrations']);

export function collectRuntimeBackupSources(root,initialEntries,{profilePath,profileSha256}={}){
  root=resolve(root);
  const entries=new Set(initialEntries);
  for(const item of readdirSync(resolve(root,'integrations'),{withFileTypes:true})){
    if(item.isSymbolicLink())throw Error('Integration source symlink refused: '+item.name);
    if(item.isFile()&&integrationExtensions.has(extname(item.name).toLowerCase()))entries.add('integrations/'+item.name);
  }
  let coverage={provided:false};
  if(profilePath){
    if(!/^[a-f0-9]{64}$/.test(profileSha256||'')||digest(profilePath)!==profileSha256)throw Error('Exact runtime profile hash required.');
    const profile=JSON.parse(readFileSync(profilePath,'utf8'));
    if(typeof profile.workspace!=='string'||resolve(profile.workspace).toLowerCase()!==root.toLowerCase()||!profile.sourceHashes||Array.isArray(profile.sourceHashes))throw Error('Runtime profile does not match this app root.');
    const required=[];
    for(const [source,want] of Object.entries(profile.sourceHashes)){
      const name=relative(root,resolve(source)).split(sep).join('/');
      if(name==='..'||name.startsWith('../')||isAbsolute(name))continue;
      if(!sourceDirectories.has(name.split('/')[0])&&!['server.mjs','serve.mjs','package.json'].includes(name))throw Error('Runtime manifest selects a non-source app path.');
      if(!/^[a-f0-9]{64}$/.test(want)||digest(source)!==want)throw Error('Declared runtime source changed: '+name);
      entries.add(name);required.push(name);
    }
    if(!required.length)throw Error('Runtime profile declared no app source files.');
    coverage={provided:true,profileSha256,requiredAppFiles:required.length,allIncluded:true,profileOrCredentialsArchived:false};
  }
  return {entries:[...entries].sort(),coverage};
}
