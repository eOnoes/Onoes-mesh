"""Backup-work folder tests; only owned temporary NTFS directories change."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT=Path(__file__).resolve().parent/'prepare_project_backup_storage.ps1'

@unittest.skipUnless(os.name=='nt','Windows folder ownership checks')
class BackupFolderTests(unittest.TestCase):
    def setUp(self):
        import sys
        sys.path.insert(0,str(SCRIPT.parent/'mind-recovery-candidate'))
        from test_persistent_authority import PRIVATE_ACL
        self.temp=tempfile.TemporaryDirectory(prefix='mind-backup-folder-test-');self.root=Path(self.temp.name).resolve()
        self.addCleanup(self.cleanup)
        self.pwsh=shutil.which('pwsh');acl=self.root/'fixture-private.ps1';acl.write_text(PRIVATE_ACL)
        self.data=self.root/'data';self.ops=self.root/'ops'
        for p in (self.data,self.ops):
            p.mkdir();subprocess.run([self.pwsh,'-NoProfile','-NonInteractive','-File',str(acl),'-Path',str(p)],capture_output=True,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
        self.marker=self.data/'existing-initialized-data.txt';self.marker.write_bytes(b'Keep initialized data exactly\r\n')
        sid=subprocess.run([self.pwsh,'-NoProfile','-NonInteractive','-Command','[Security.Principal.WindowsIdentity]::GetCurrent().User.Value'],capture_output=True,text=True,check=True,creationflags=subprocess.CREATE_NO_WINDOW).stdout.strip()
        home=self.ops/'First-sync';targets=[home]
        for name in ('Before-write','After-write'):
            phase=home/name;targets.extend([phase,*[phase/n for n in ('Snapshot','Archive-stage','Archive-rehearsal')]])
        self.targets=targets;self.plan=dict(schema='onoes-mind-backup-work-folder-plan/v1',ownerSid=sid,
            existingDataDirectory=str(self.data),privateAnchor=str(self.ops),privateDirectories=[str(p) for p in targets])
        self.plan_file=self.root/'plan.json';self.write()
        self.before_acl=self.acls()

    def cleanup(self):
        self.assertEqual(self.root.parent,Path(tempfile.gettempdir()).resolve());self.assertTrue(self.root.name.startswith('mind-backup-folder-test-'));self.temp.cleanup()

    def write(self,value=None):
        self.plan_file.write_text(json.dumps(self.plan if value is None else value),encoding='utf-8');self.sha=hashlib.sha256(self.plan_file.read_bytes()).hexdigest()

    def acls(self):
        command='@(' + ','.join("(Get-Acl -LiteralPath '"+str(p).replace("'","''")+"').Sddl" for p in (self.data,self.ops)) + ') | ConvertTo-Json'
        return subprocess.run([self.pwsh,'-NoProfile','-NonInteractive','-Command',command],capture_output=True,text=True,check=True,creationflags=subprocess.CREATE_NO_WINDOW).stdout

    def call(self,*args,sha=None):
        return subprocess.run([self.pwsh,'-NoProfile','-NonInteractive','-File',str(SCRIPT),'-PlanPath',str(self.plan_file),'-ExpectedPlanSha256',sha or self.sha,*args],capture_output=True,text=True,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)

    def unchanged(self):
        self.assertEqual(self.marker.read_bytes(),b'Keep initialized data exactly\r\n');self.assertEqual(self.acls(),self.before_acl)

    def test_preview_and_whatif_preserve_nonempty_initialized_data_and_create_nothing(self):
        for args in ((),('-Apply','-WhatIf')):
            result=self.call(*args);self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('"applied": false',result.stdout);self.assertFalse(self.targets[0].exists());self.unchanged()

    def test_exact_apply_creates_only_nine_private_folders_and_preserves_existing_acls(self):
        result=self.call('-Apply');self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(result.stdout);self.assertTrue(report['applied']);self.assertEqual(len(report['privateDirectories']),9)
        self.assertTrue(all(p.is_dir() for p in self.targets));self.unchanged()
        self.assertEqual({p.relative_to(self.ops).as_posix() for p in self.ops.rglob('*')}, {p.relative_to(self.ops).as_posix() for p in self.targets})
        second=self.call('-Apply');self.assertNotEqual(second.returncode,0);self.unchanged()

    def test_wrong_owner_hash_duplicate_outside_and_existing_target_refuse(self):
        result=self.call('-Apply',sha='0'*64);self.assertNotEqual(result.returncode,0)
        for kind in ('owner','duplicate','outside','existing'):
            bad=copy.deepcopy(self.plan)
            if kind=='owner':bad['ownerSid']='S-1-5-21-1-2-3-9999'
            elif kind=='duplicate':bad['privateDirectories'].append(bad['privateDirectories'][0])
            elif kind=='outside':bad['privateDirectories'][0]=str(self.root/'outside')
            else:bad['privateDirectories'][0]=str(self.ops)
            self.write(bad);result=self.call('-Apply');self.assertNotEqual(result.returncode,0,kind)
            self.assertFalse(self.targets[0].exists());self.unchanged()

if __name__=='__main__':unittest.main()
