"""Actual Windows ACL action in owned TEMP; live targets get only later preview."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0,'D:/Dev/Onoes-Mind')
from onoes_mind.enrollment_store import qualify_private_storage
from test_persistent_authority import PRIVATE_ACL

SCRIPT=Path(__file__).with_name('prepare_storage.ps1').resolve()


@unittest.skipUnless(sys.platform=='win32','Windows private storage')
class PrivateStorageActionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name).resolve()
        self.addCleanup(self.cleanup)
        self.shell=shutil.which('pwsh');self.assertTrue(self.shell)
        self.existing=self.root/'existing-data';self.existing.mkdir()
        acl=self.root/'fixture-acl.ps1';acl.write_text(PRIVATE_ACL)
        self.run_shell(['-File',str(acl),'-Path',str(self.existing)],check=True)
        self.owner=self.run_shell(['-Command','[Security.Principal.WindowsIdentity]::GetCurrent().User.Value']).stdout.strip()
        self.anchor=self.root/'private-anchor';self.anchor.mkdir()
        self.public=self.root/'ciphertext-anchor';self.public.mkdir()
        self.private=[self.anchor/'new-root',self.anchor/'new-root/journal',self.anchor/'staging']
        self.encrypted=[self.public/'milestones']
        self.plan=dict(schema='onoes-mind-private-folder-plan/v1',ownerSid=self.owner,
            existingDataDirectory=str(self.existing),privateAnchors=[str(self.anchor)],encryptedAnchor=str(self.public),
            privateDirectories=list(map(str,self.private)),encryptedDirectories=list(map(str,self.encrypted)))
        self.plan_path=self.root/'plan.json'

    def cleanup(self):
        self.assertEqual(Path(self.temp.name).resolve(),self.root)
        self.temp.cleanup()

    def run_shell(self,args,check=False):
        return subprocess.run([self.shell,'-NoProfile','-NonInteractive',*args],capture_output=True,text=True,
            timeout=60,check=check,creationflags=subprocess.CREATE_NO_WINDOW)

    def write_plan(self):
        data=(json.dumps(self.plan,indent=2)+'\n').encode();self.plan_path.write_bytes(data)
        return hashlib.sha256(data).hexdigest()

    def run_action(self,*args,digest=None):
        fingerprint=self.write_plan()
        return self.run_shell(['-File',str(SCRIPT),'-PlanPath',str(self.plan_path),'-ExpectedPlanSha256',digest or fingerprint,*args])

    def none_created(self):
        for path in self.private+self.encrypted:self.assertFalse(path.exists(),str(path))
        self.assertEqual(list(self.existing.iterdir()),[])

    def test_preview_creates_nothing(self):
        result=self.run_action();self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(result.stdout);self.assertFalse(report['applied']);self.none_created()

    def test_apply_whatif_creates_nothing(self):
        result=self.run_action('-Apply','-WhatIf');self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(result.stdout[result.stdout.index('{'):]);self.assertFalse(report['applied']);self.none_created()

    def test_actual_apply_qualifies_all_new_private_folders_and_preserves_existing_data(self):
        before=self.existing.stat();result=self.run_action('-Apply')
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(result.stdout);self.assertTrue(report['applied']);self.assertFalse(report['keysOrDatabase'])
        for path in self.private:self.assertEqual(qualify_private_storage(path),path)
        self.assertTrue(self.encrypted[0].is_dir())
        self.assertEqual((self.existing.stat().st_dev,self.existing.stat().st_ino),(before.st_dev,before.st_ino))
        self.assertEqual(list(self.existing.iterdir()),[])
        self.assertEqual(qualify_private_storage(self.existing),self.existing)

    def test_existing_target_and_its_permissions_are_untouched(self):
        occupied=self.private[-1];occupied.mkdir();marker=occupied/'keep.txt';marker.write_text('preserve')
        sddl=lambda:self.run_shell(['-Command',"(Get-Acl -LiteralPath '"+str(occupied)+"').Sddl"]).stdout.strip()
        before=sddl();result=self.run_action('-Apply')
        self.assertNotEqual(result.returncode,0);self.assertEqual(sddl(),before)
        self.assertEqual(marker.read_text(),'preserve');self.assertFalse(self.private[0].exists())

    def test_wrong_owner_refuses_before_changes(self):
        self.plan['ownerSid']='S-1-5-21-1-2-3-9999'
        self.assertNotEqual(self.run_action('-Apply').returncode,0);self.none_created()

    def test_wrong_plan_fingerprint_refuses_before_changes(self):
        self.assertNotEqual(self.run_action('-Apply',digest='0'*64).returncode,0);self.none_created()

    def test_outside_anchor_refuses_before_changes(self):
        self.plan['privateDirectories'].append(str(self.root/'outside-anchor'))
        self.assertNotEqual(self.run_action('-Apply').returncode,0);self.none_created()
        self.assertFalse((self.root/'outside-anchor').exists())

    def test_junction_ancestor_refuses_before_changes(self):
        link=self.root/'junction'
        self.run_shell(['-Command',"New-Item -ItemType Junction -Path '"+str(link)+"' -Target '"+str(self.anchor)+"' | Out-Null"],check=True)
        self.plan['privateAnchors']=[str(link)]
        self.plan['privateDirectories']=[str(link/'new-private')]
        self.assertNotEqual(self.run_action('-Apply').returncode,0)
        self.assertFalse((self.anchor/'new-private').exists());self.none_created()

    def test_exfat_private_target_refuses_before_any_changes(self):
        anchor=Path('E:/App-Backups/Onoes-Mesh')
        target=anchor/('Never-create-private-NTFS-test-'+str(uuid.uuid4()))
        self.plan['privateAnchors'].append(str(anchor));self.plan['privateDirectories'].append(str(target))
        result=self.run_action('-Apply','-WhatIf')
        self.assertNotEqual(result.returncode,0);self.assertIn('NTFS',result.stderr)
        self.assertFalse(target.exists());self.none_created()


if __name__=='__main__':unittest.main()
