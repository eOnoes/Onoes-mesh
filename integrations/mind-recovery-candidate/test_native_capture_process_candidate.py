"""Actual Windows capture launch; opt-in copied workspace, no Mind store."""
from contextlib import ExitStack, closing
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import mesh_launch_candidate as launch
import recall_process_candidate as roles
from test_project_mesh_input_candidate import admitted_http, edited_card

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mesh_launcher_window import MeshLauncherWindow
from mesh_native_recovery import archive_retired_mesh_attempt, identified_native_attempt


@unittest.skipUnless(os.name=='nt' and os.environ.get('MESH_NATIVE_CAPTURE_WORKSPACE'),
                     'Explicit isolated Windows capture workspace required')
class CaptureProcessTests(unittest.TestCase):
    def test_cold_launch_without_memory_access_keeps_edits_across_owned_restart(self):
        workspace=Path(os.environ['MESH_NATIVE_CAPTURE_WORKSPACE']).resolve()
        self.assertEqual(workspace,launch.ROOT)
        self.assertTrue(workspace.parent.name.startswith('mesh-native-capture-'))
        receipt=workspace.parent/'workroom-ab-preview-process.json'
        self.assertFalse(receipt.exists())
        private=workspace.parent/'synthetic-private';private.mkdir()
        pwsh=Path(shutil.which('pwsh')).resolve()
        acl=r"""$p=$args[0];$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User;
$a=[Security.AccessControl.DirectorySecurity]::new();$a.SetOwner($sid);$a.SetAccessRuleProtection($true,$false);
foreach($id in @($sid.Value,'S-1-5-18','S-1-5-32-544')){
$s=[Security.Principal.SecurityIdentifier]::new($id);
$r=[Security.AccessControl.FileSystemAccessRule]::new($s,'FullControl','ContainerInherit,ObjectInherit','None','Allow');$a.AddAccessRule($r)}
Set-Acl -LiteralPath $p -AclObject $a;Write-Output $sid.Value"""
        # Pass the path as a structured argument to a fixed script, not shell text.
        acl_script=workspace.parent/'private-fixture.ps1';acl_script.write_text(acl,encoding='utf-8')
        secured=subprocess.run([str(pwsh),'-NoLogo','-NoProfile','-NonInteractive','-File',str(acl_script),str(private)],
            capture_output=True,text=True,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
        sid=secured.stdout.strip();self.assertTrue(sid.startswith('S-1-'))
        data=workspace/'data'/'offline-capture';data.mkdir(parents=True);database=data/'tasks.sqlite'
        node=Path(shutil.which('node')).resolve()
        source="""import {openTaskStore} from './lib/task-store.mjs';
import {createWorkroomProjectSyncCandidate} from './integrations/workroom-project-sync-candidate.mjs';
import {statSync,realpathSync} from 'node:fs';
let capture;const file=process.argv[1];
const store=openTaskStore(file,{projectSyncFactory:c=>capture=createWorkroomProjectSyncCandidate(c,{storeId:'synthetic-capture-store',initialize:true})});
const card=store.create({title:'Cold offline card',description:'PRIVATE-DO-NOT-SHARE',owner:'nims'});
const link={cardId:card.id,projectId:'synthetic-project',approvalRef:'fixture:offline',fields:['title','stage']};
capture.link(link);store.close();const s=statSync(file,{bigint:true});
console.log(JSON.stringify({link,source:{databasePath:realpathSync(file),fileDevice:String(s.dev),fileInode:String(s.ino)}}));"""
        initialized=subprocess.run([str(node),'--input-type=module','-e',source,str(database)],cwd=workspace,
            capture_output=True,text=True,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
        initialized=json.loads(initialized.stdout)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        gate=private/'synthetic-gate.txt';gate.write_text('synthetic-offline-fixture-gate',encoding='utf-8')
        settings={key:'0' for key in launch.SETTINGS};settings.update(MESH_PREVIEW_PORT=str(port),
            MESH_DATA_DIR='data/offline-capture',MESH_RELAY_MODE='http',MESH_GATE_KEY_FILE=str(gate),MESH_TAILSCALE_HOST='synthetic.invalid')
        import onoes_mind
        runtime=dict(python=sys.executable,pwsh=str(pwsh),mindSource=str(Path(onoes_mind.__file__).resolve().parents[1]))
        profile=private/'capture-profile.json';approval=private/'capture-approval.json'
        p=dict(schema=launch.CAPTURE_SCHEMA,workspace=str(workspace),pythonExecutable=sys.executable,
            nodeExecutable=str(node),pythonSha256=launch.digest(sys.executable),nodeSha256=launch.digest(node),
            runtime=runtime,ownerSid=sid,pwshSha256=launch.digest(pwsh),
            sourceHashes={str(path):launch.digest(path) for path in launch.capture_source_paths(runtime)},settings=settings,
            attemptPath=str(private/'capture-attempt.json'),stdoutPath=str(private/'capture-out.log'),stderrPath=str(private/'capture-err.log'),
            projectCapture=dict(schema='onoes-mesh-native-project-capture/v1',source=initialized['source'],
                storeId='synthetic-capture-store',links=[initialized['link']]))
        roles.private_new_json(profile,p);sha=launch.digest(profile)
        approved=dict(schema='onoes-mesh-offline-capture-approval/v1',decision='approve_exact_workroom_offline_capture',
            ownerSid=sid,workspace=str(workspace),profileSha256=sha)
        roles.private_new_json(approval,approved)
        children=[]
        def cleanup():
            for child in children:
                if child.poll() is None:child.terminate()
                child.wait(timeout=30)
        self.addCleanup(cleanup)
        def events():
            with closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as db:
                return db.execute('SELECT eventId,payloadHash,state,receipt FROM mind_project_outbox ORDER BY sequence').fetchall()
        def address(child):
            deadline=time.monotonic()+60
            while time.monotonic()<deadline:
                self.assertIsNone(child.poll())
                for line in Path(p['stdoutPath']).read_text().splitlines():
                    try:row=json.loads(line)
                    except ValueError:continue
                    if row.get('event')=='mesh_listening' and row.get('pid')==child.pid:return row['url']
                time.sleep(.1)
            self.fail('Exact synthetic gateway did not become ready')
        def forbidden(*args,**kwargs):raise AssertionError('Offline startup accessed a Mind role')
        with ExitStack() as guards:
            for name in ('approved_profile','native_options','reader_state','terminal_proof'):
                guards.enter_context(patch.object(roles,name,side_effect=forbidden))
            with MeshLauncherWindow(workspace,launch.digest(workspace/'integrations/restart-workroom-preview.ps1')) as window:
                child,ticks,record=launch.launch_mesh(profile,sha,approval);children.append(child)
                request=admitted_http(address(child));token=request('/api/trial-session/bootstrap',{})['csrfToken']
                self.assertTrue(identified_native_attempt(record));self.assertEqual(record['mode'],'capture_only')
                window.publish_native_owner(child,ticks,profile,sha,previous_sha256=None)
                card=initialized['link']['cardId']
                opened=request('/api/workroom/'+card,csrf=token,method='GET');self.assertEqual(opened['memorySync']['state'],'offline')
                task=request('/api/tasks/'+card,csrf=token,method='GET')['task']
                request('/api/tasks/'+card,edited_card(task,'Saved during cold offline startup'),token,method='PATCH')
                saved=events();self.assertEqual(len(saved),2);self.assertTrue(all(row[2]=='pending' and row[3] is None for row in saved))
                attempt_before=Path(p['attemptPath']).read_bytes()
                with self.assertRaises(roles.RoleError):launch.launch_mesh(profile,sha,approval)
                self.assertIsNone(child.poll());self.assertEqual(Path(p['attemptPath']).read_bytes(),attempt_before)
                request('/api/trial-session/logout',{},token)
                child.terminate();child.wait(timeout=30)
                previous=launch.digest(receipt)
                archived=archive_retired_mesh_attempt(window,launch_module=launch,mesh_profile=profile,
                    mesh_sha256=sha,reader_approval=approval)
                self.assertTrue(archived['archived'])
                again,stamp,record=launch.launch_mesh(profile,sha,approval);children.append(again)
                request=admitted_http(address(again));token=request('/api/trial-session/bootstrap',{})['csrfToken']
                beforeimage=workspace/'data'/'capture-owner-before.json'
                window.publish_native_owner(again,stamp,profile,sha,previous_sha256=previous,beforeimage_path=beforeimage)
                self.assertEqual(launch.digest(beforeimage),previous)
                self.assertEqual(request('/api/tasks/'+card,csrf=token,method='GET')['task']['title'],'Saved during cold offline startup')
                self.assertEqual(request('/api/workroom/'+card,csrf=token,method='GET')['memorySync']['state'],'offline')
                self.assertEqual(events(),saved);request('/api/trial-session/logout',{},token)
                again.terminate();again.wait(timeout=30)
        proof=dict(schema='onoes-mesh-synthetic-native-capture-proof/v1',syntheticOnly=True,liveChanged=False,
            coldStartWithoutMemoryRoleAccess=True,ownedPublicationAndRetirement=True,duplicateLaunchRefused=True,
            editAndReopenPassed=True,originalPendingEventsUnchanged=True,noCredentialsInFrame=True,
            sourceHashes=p['sourceHashes'],pendingEventCount=2,profileSha256=sha)
        (workspace.parent/'CAPTURE-PROOF.json').write_text(json.dumps(proof,indent=2),encoding='utf-8')


if __name__=='__main__':unittest.main()
