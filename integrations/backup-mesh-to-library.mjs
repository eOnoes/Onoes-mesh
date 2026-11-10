import {existsSync,mkdirSync,readdirSync,readFileSync,writeFileSync,renameSync,copyFileSync} from 'node:fs';
import {resolve,join,dirname,relative,isAbsolute} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createHash,randomUUID} from 'node:crypto';
import {execFileSync} from 'node:child_process';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const library=resolve(process.argv[2]||'E:/App-Backups');
const app=join(library,'ONOes-Mesh');mkdirSync(app,{recursive:true});
const writeNew=(path,text)=>{try{writeFileSync(path,text,{flag:'wx'});}catch(e){if(e.code!=='EEXIST')throw e;}};
const schema='onoes-mesh-backup-library/v1',marker=join(app,'BACKUP-LIBRARY.json');
if(existsSync(marker)&&JSON.parse(readFileSync(marker,'utf8')).schema!==schema)throw Error('Existing backup-library identity does not match Mesh.');
writeNew(marker,JSON.stringify({schema,app:'ONOes-Mesh',scope:'App source and Workroom data',createdAt:new Date().toISOString()},null,2));
writeNew(join(library,'READ-ME-FIRST.txt'),`APP BACKUP LIBRARY\n\nEach app gets its own clearly named folder here. Each backup goes in a NEW dated folder; never overwrite a previous backup.\n\nCurrent app: ONOes-Mesh\nOpen ONOes-Mesh/LATEST.txt to find the latest verified backup and restore guide.\n\nFor future apps use: <App name>/<UTC date and time>/<clearly named component or data files>. Include BACKUP-INFO.txt, RESTORE.txt and a manifest with checksums. A backup is complete only after verification passes.\n\nThis is a backup location on this PC. Off-device backup remains a separate future step. Other apps are not automatically backed up by creating this root folder.\n`);
const id=randomUUID(),at=new Date(),stamp=at.toISOString().replace('T','_').replace(/[:.]/g,'-').replace('Z','_UTC');
const directory=join(app,stamp+'_'+id.slice(0,8));mkdirSync(directory);
const source=join(root,'data/workroom-preview/tasks.sqlite');
const receipt=JSON.parse(execFileSync(process.execPath,[join(root,'integrations/workroom-backup.mjs'),source,join(directory,'Workroom-data')],{cwd:root,encoding:'utf8',maxBuffer:1048576}));
if(receipt.integrity!=='ok'||receipt.foreignKeys!=='ok'||receipt.restore!=='PASS')throw Error('Data verification did not pass. No latest pointer updated.');
const entries=[];
function walk(path){for(const item of readdirSync(join(root,path),{withFileTypes:true})){const name=path+'/'+item.name;if(item.isSymbolicLink())throw Error('Source symlink refused: '+name);if(item.name==='__pycache__'||/\.py[co]$/i.test(item.name))continue;if(item.isDirectory())walk(name);else if(item.isFile())entries.push(name);}}
for(const name of ['public','lib','shared','config','scripts'])if(existsSync(join(root,name)))walk(name);
for(const name of ['.gitattributes','package.json','package-lock.json','VERSION','server.mjs','serve.mjs','README.md','RELEASE-OPERATIONS.md','PROJECT-LEAD-POLICY.md','BUGS.md','MESH-REPO-INDEX.md','WORKROOM-AB-CHECKPOINT.md','APP03-SOURCE-CONTEXT.json','APP03-CONTRACT.json','integrations/restart-workroom-preview.ps1','integrations/relay-service.ps1','integrations/prepare-nemotron-supervisor.mjs','integrations/install-workroom-recovery.ps1','integrations/ensure-workroom-hidden.vbs','integrations/workroom-backup.mjs','integrations/backup-mesh-to-library.mjs','integrations/windows_writer_fence.py','integrations/hermes_writer_scope.py','integrations/prepare_hermes_writer_scope.py','integrations/hermes-writer-scope.patch','integrations/verify-live-release.mjs','integrations/verify-nims-connection.mjs','integrations/verify-automatic-team.mjs','integrations/verify-automatic-team-correction.mjs','integrations/pin-update.json','integrations/PROCESS-OWNERSHIP.md','integrations/RELAY-AVAILABILITY-REVIEW.md','integrations/relay-availability.patch','data/workroom-preview/recovery-task.xml'])if(existsSync(join(root,name)))entries.push(name);
for(const item of readdirSync(join(root,'test'),{withFileTypes:true}))if(item.isFile()&&/\.(mjs|js|py)$/.test(item.name))entries.push('test/'+item.name);
for(const name of ['integrations/relay_writer_observation.py','integrations/prepare_relay_writer_observation.py','integrations/relay-writer-observation.patch'])entries.push(name);
for(const name of ['integrations/qualify_hermes_runtime.py','integrations/hermes-runtime-qualification.json'])entries.push(name);
entries.push('integrations/verify-native-installed-profile.py');
for(const name of ['integrations/native_gateway_transport.py','integrations/native-gateway-transport-qualification.json','integrations/native-server-binding-qualification.json'])entries.push(name);
for(const name of ['integrations/guide-team-pilot.mjs','integrations/guide-team-pilot-qualification.json','integrations/native-header-fixture-qualification.json'])entries.push(name);
for(const name of ['integrations/native-codex_headers-startup.patch','integrations/native-version_info-startup.patch','integrations/native-header-startup-qualification.json','integrations/native-startup-batch-qualification.json','integrations/verify_native_request_headers.py'])entries.push(name);
for(const name of ['integrations/guide-team-live-qualification.json','integrations/prepare_native_process_capability.py','integrations/native-process-scope-capability.patch','integrations/native-process-capability-qualification.json','test/fixtures/native-process-lookup.py'])entries.push(name);
for(const name of ['integrations/prepare-native-worker-maintenance.py','integrations/NATIVE-WORKER-MAINTENANCE.md','integrations/native-worker-maintenance-qualification.json'])entries.push(name);
entries.push('integrations/workroom-backup-qualification.json');
entries.push('integrations/guide-team-post-maintenance-qualification.json');
entries.sort();
// Keep the operational contracts with the UI/code they describe.
for(const name of ['MIND-CONTRACT.md','RELAY-INTEGRATION.md','MESH-QUICK-START.md'])if(existsSync(join(root,name)))entries.push(name);
entries.sort();
const hash=path=>createHash('sha256').update(readFileSync(path)).digest('hex');
const files=entries.map(path=>({path,sha256:hash(join(root,path))}));
const archive=join(directory,'Mesh-app-source.zip');
execFileSync('tar.exe',['-a','-cf',archive,'-C',root,'--',...entries],{cwd:root,stdio:'pipe'});
const extraction=join(root,'data/backup-source-verification',id);mkdirSync(extraction,{recursive:true});
const listing=execFileSync('tar.exe',['-tf',archive],{encoding:'utf8'}).trim().split(/\r?\n/);
for(const entry of listing){const target=resolve(extraction,entry);const rel=relative(extraction,target);if(isAbsolute(entry)||rel.startsWith('..')||isAbsolute(rel))throw Error('Unsafe archive entry refused.');}
execFileSync('tar.exe',['-xf',archive,'-C',extraction],{stdio:'pipe'});
for(const file of files)if(hash(join(extraction,file.path))!==file.sha256)throw Error('Extracted source hash mismatch: '+file.path);
for(const file of ['server.mjs','serve.mjs','public/app.js','public/chat.mjs','public/relay-conversation.mjs','public/mind-workspace.mjs'])execFileSync(process.execPath,['--check',join(extraction,file)],{stdio:'pipe'});
// Exercise the restored source against a COPY of the E: data snapshot.
const restoredData=join(extraction,'data','backup-http-rehearsal');mkdirSync(restoredData,{recursive:true});copyFileSync(receipt.snapshot,join(restoredData,'tasks.sqlite'),1);
const {startApp}=await import(pathToFileURL(join(extraction,'server.mjs')).href);
const restoredApp=await startApp({dataDir:'data/backup-http-rehearsal',relayEnabled:false});
try{
  let response=await fetch(restoredApp.url+'/api/workroom');if(response.status!==401)throw Error('Restored app did not enforce admission.');
  const origin=restoredApp.url;response=await fetch(origin+'/api/trial-session/bootstrap',{method:'POST',headers:{Origin:origin,'Content-Type':'application/json'},body:'{}'});if(response.status!==201)throw Error('Restored app bootstrap failed.');
  const session=await response.json(),headers={Origin:origin,Cookie:response.headers.get('set-cookie').split(';')[0],'X-Trial-CSRF':session.csrfToken};
  response=await fetch(origin+'/api/workroom',{headers});if(response.status!==200)throw Error('Restored app could not read saved tasks.');const taskBody=await response.json();if(taskBody.tasks.length!==receipt.taskCount)throw Error('Restored source/data task count mismatch.');
  for(const file of ['chat.mjs','relay-conversation.mjs','mind-workspace.mjs']){
    const asset=await fetch(origin+'/'+file,{headers});if(asset.status!==200||await asset.text()!==readFileSync(join(extraction,'public',file),'utf8'))throw Error('Restored UI module did not match its source: '+file);
  }
  await fetch(origin+'/api/trial-session/logout',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:'{}'});
}finally{await restoredApp.close();}
const restore=`RESTORE ONOes-Mesh / Workroom\n\nData snapshot: Workroom-data/tasks.sqlite\nApp source: Mesh-app-source.zip\nVerification: manifest.json and Workroom-data/receipt.json\n\nTo restore data on this PC:\n1. Verify the tasks.sqlite SHA256 against the receipt/manifest (PowerShell: Get-FileHash -Algorithm SHA256).\n2. In the Mesh source folder, run: powershell -NoProfile -File integrations/restart-workroom-preview.ps1 -Action Stop\n   This intentionally pauses Mesh automatic recovery. Do not stop other apps.\n3. Preserve the CURRENT tasks.sqlite and any tasks.sqlite-wal / tasks.sqlite-shm together in a separate dated safety folder. Keep recovery-paused in data/workroom-preview in place. Do not mix old WAL/SHM files with the replacement database.\n4. Copy this backup's Workroom-data/tasks.sqlite to:\n   ${source}\n5. Run the named launcher with -Action Start, then open the private Workroom link and check cards, reports and reviews. Start resumes automatic recovery.\n\nTo recover app source:\nExtract Mesh-app-source.zip into a NEW folder, not over an existing working copy. It contains the matching app source, operational scripts and root-level test sources. Keep the existing working copy as a safety copy. Use a compatible Node24 runtime. For a moved checkout, review paths in the launcher and reinstall its named recovery task deliberately. The current backup targets the active mesh-workroom-ab checkout.\n\nExternal runtime dependencies such as the existing Relay service/configuration and AI model files need their own app-specific backup. They are not part of this Mesh source/data snapshot.\n\nThe live database has NOT been replaced by creating or verifying this backup. restore-rehearsal.sqlite is a verification copy, not the primary restore snapshot.\n`;
writeFileSync(join(directory,'RESTORE.txt'),restore);
writeFileSync(join(directory,'BACKUP-INFO.txt'),`ONOes-Mesh — APP SOURCE + WORKROOM DATA\n\nCreated (Chicago): ${at.toLocaleString('en-US',{timeZone:'America/Chicago'})}\nCreated (UTC): ${at.toISOString()}\nSaved tasks: ${receipt.taskCount}\nSource files: ${files.length}\n\nWorkroom-data/tasks.sqlite: saved tasks, goals/checklists, reviews, task messages and recorded native outcomes.\nMesh-app-source.zip: matching app source and operational scripts.\nRESTORE.txt: human restore instructions.\nmanifest.json: exact paths, file hashes and verification results.\n\nSQLite integrity, foreign keys and isolated application-migration restore: PASS.\nSource archive extracted, every included file hash compared and startup-script syntax checked: PASS.\nRestored source started with a COPY of the backed-up database; admission guard and all saved tasks verified through HTTP: PASS.\n\nBackup root: ${library}\nThis is a second-drive backup on this PC; it does not yet provide off-device protection.\n`);
const manifest={schema:'onoes-mesh-backup/v1',app:'ONOes-Mesh',createdAt:at.toISOString(),sourceRoot:root,directory,scope:['Mesh app source','Workroom SQLite data'],taskCount:receipt.taskCount,sourceFiles:files,archives:{source:{file:'Mesh-app-source.zip',sha256:hash(archive)},data:{file:'Workroom-data/tasks.sqlite',sha256:hash(receipt.snapshot)}},verification:{sqliteIntegrity:receipt.integrity,foreignKeys:receipt.foreignKeys,isolatedDataRestore:receipt.restore,sourceExtraction:'PASS',sourceHashes:'PASS',sourceSyntax:'PASS',restoredSourceHTTP:'PASS'},offDevice:false};
writeFileSync(join(directory,'manifest.json'),JSON.stringify(manifest,null,2));
const latestPath=join(app,'LATEST.json');
if(existsSync(latestPath)&&JSON.parse(readFileSync(latestPath,'utf8')).schema!=='onoes-mesh-latest/v1')throw Error('Unknown latest pointer; backup retained without replacing it.');
const latest={schema:'onoes-mesh-latest/v1',directory,createdAt:manifest.createdAt,manifest:join(directory,'manifest.json'),restoreGuide:join(directory,'RESTORE.txt'),taskCount:receipt.taskCount,verified:true};
const temporary=latestPath+'.'+id+'.tmp';writeFileSync(temporary,JSON.stringify(latest,null,2),{flag:'wx'});renameSync(temporary,latestPath);
writeFileSync(join(app,'LATEST.txt'),`LATEST VERIFIED ONOes-Mesh BACKUP\n\n${directory}\n\nCreated (Chicago): ${at.toLocaleString('en-US',{timeZone:'America/Chicago'})}\nSaved tasks: ${receipt.taskCount}\nContents: Workroom data and matching Mesh app source.\n\nOpen BACKUP-INFO.txt and RESTORE.txt in that folder.\nVerification passed; previous dated backups are retained.\n`);
writeFileSync(join(root,'..','workroom-backup-latest.json'),JSON.stringify(receipt,null,2));
writeFileSync(join(root,'..','mesh-library-backup-latest.json'),JSON.stringify(latest,null,2));
console.log(JSON.stringify({...latest,sourceFiles:files.length,verification:manifest.verification},null,2));
