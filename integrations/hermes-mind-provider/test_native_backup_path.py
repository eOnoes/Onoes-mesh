"""End-to-end NativePhases.backup path-identity tests; no real process, task, database or backup."""
import hashlib,json,os,sys,tempfile,unittest
from pathlib import Path
import cloud_phase_runner as runner

ARCHIVE_BYTES=b'harmless archive payload'
ARCHIVE_SHA=hashlib.sha256(ARCHIVE_BYTES).hexdigest()
UNSET=object()


class FakeQualify:
    """Stand-in for onoes_mind.enrollment_store.qualify_private_storage: Path plus kind checks."""
    def __init__(self):self.calls=[]
    def __call__(self,path,*,kind=None):
        self.calls.append(kind)
        target=Path(path)
        if kind=='file':
            assert target.is_file(),str(target)
        else:
            assert kind is None and target.is_dir(),str(target)
        return target


class BackupPathTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve(strict=True)
        (self.root/'evidence').mkdir()
        self.entry=self.root/'project_backup_entry.py'
        self.entry.write_bytes(b'harmless entry')
        self.archive=self.root/'archive.zip';self.archive.write_bytes(ARCHIVE_BYTES)
        self.profile=self.root/'profile.json';self.approval=self.root/'approval.json'
        self.approval.write_bytes(b'{}')
        self.result_path=self.root/'native-result.json'
        self.attempt_path=self.root/'native-attempt.json'

    def _plan(self,encrypted_backup):
        self.profile.write_text(json.dumps({'archiveCredentialMode':'windows-local',
            'resultPath':str(self.result_path),'attemptPath':str(self.attempt_path),
            'encryptedBackup':encrypted_backup},sort_keys=True))
        return {'schema':'onoes-cloud-install-window/v1','agentId':'cyony','readerPrincipal':'context-cyony',
            'sharedProject':'onoes-mesh','modelCalls':0,'maintenanceTask':'ONOes Mesh Workroom Recovery',
            'python':sys.executable,'pythonSha256':hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
            'backups':{'before':{'entryPath':str(self.entry),'entrySha256':hashlib.sha256(self.entry.read_bytes()).hexdigest(),
                'profilePath':str(self.profile),'profileSha256':hashlib.sha256(self.profile.read_bytes()).hexdigest(),
                'approvalPath':str(self.approval),'approvalSha256':hashlib.sha256(self.approval.read_bytes()).hexdigest(),
                'resultPath':str(self.result_path),'attemptPath':str(self.attempt_path)}}}

    def _run(self,encrypted_backup,*,status='backup_complete_inactive',profile_sha=UNSET,
            rehearsal='PASS',service_started=False,archive=UNSET,archive_sha=UNSET):
        self.assertFalse(self.result_path.exists());self.assertFalse(self.attempt_path.exists())
        phase=runner.NativePhases.__new__(runner.NativePhases)
        phase.plan=self._plan(encrypted_backup);phase.evidence=self.root/'evidence'
        self.calls=[]
        profile_sha=runner.digest(self.profile) if profile_sha is UNSET else profile_sha
        archive=str(self.archive) if archive is UNSET else archive
        archive_sha=ARCHIVE_SHA if archive_sha is UNSET else archive_sha
        def fake_execute_once(argv,*,evidence,label,stdin=None,private_stdout=False,timeout=180):
            self.calls.append({'argv':argv,'label':label,'private_stdout':private_stdout,'timeout':timeout})
            payload=dict(status=status,profileSha256=profile_sha,archiveRehearsal=rehearsal,
                serviceStarted=service_started,archive=archive,archiveSha256=archive_sha)
            with open(str(self.result_path),'xb') as stream:
                stream.write(json.dumps(payload,sort_keys=True).encode('utf-8'))
            return b'prose only'
        fake=FakeQualify()
        real_execute=runner.execute_once
        fake_module=__import__('types').ModuleType('onoes_mind.enrollment_store')
        fake_module.qualify_private_storage=fake
        fake_package=__import__('types').ModuleType('onoes_mind')
        fake_package.enrollment_store=fake_module
        saved={'onoes_mind':sys.modules.get('onoes_mind'),
            'onoes_mind.enrollment_store':sys.modules.get('onoes_mind.enrollment_store')}
        sys.modules['onoes_mind']=fake_package;sys.modules['onoes_mind.enrollment_store']=fake_module
        runner.execute_once=fake_execute_once
        try:
            result=phase.backup('before',label='backup-before')
        finally:
            runner.execute_once=real_execute
            for name,old in saved.items():
                if old is None:sys.modules.pop(name,None)
                else:sys.modules[name]=old
        return result

    def _check_transport(self):
        self.assertEqual(len(self.calls),1)
        call=self.calls[0]
        self.assertEqual(call['argv'][0],sys.executable)
        self.assertEqual(call['argv'][3],str(self.entry))
        self.assertEqual(call['argv'][4],'--profile')
        self.assertEqual(call['label'],'backup-before')
        self.assertIs(call['private_stdout'],True)
        self.assertEqual(call['timeout'],600)

    def test_expected_slash_reported_backslash_passes_on_windows(self):
        if os.name!='nt':self.skipTest('Windows slash spelling case')
        result=self._run(str(self.archive).replace('\\','/'),archive=str(self.archive))
        self.assertEqual(result['status'],'backup_complete_inactive');self._check_transport()

    def test_case_variation_passes_on_windows(self):
        if os.name!='nt':self.skipTest('Windows case-insensitive spelling')
        varied=str(self.root/'ARCHIVE.ZIP')
        self.assertNotEqual(varied,str(self.archive))
        result=self._run(str(self.archive),archive=varied)
        self.assertEqual(result['archive'],varied);self._check_transport()

    def test_sibling_filename_same_hash_refuses(self):
        sibling=self.root/'other.zip';sibling.write_bytes(ARCHIVE_BYTES)
        with self.assertRaises(runner.PhaseTransportHeld):self._run(str(self.archive),archive=str(sibling))

    def test_wrong_directory_refuses(self):
        other=self.root/'sub';other.mkdir();other.joinpath('archive.zip').write_bytes(ARCHIVE_BYTES)
        expected=str(self.archive);wrong=str(other/'archive.zip')
        with self.assertRaises(runner.PhaseTransportHeld):self._run(expected,archive=wrong)
    def test_wrong_expected_directory_refuses(self):
        other=self.root/'sub';other.mkdir();other.joinpath('archive.zip').write_bytes(ARCHIVE_BYTES)
        with self.assertRaises(runner.PhaseTransportHeld):self._run(str(other/'archive.zip'),archive=str(self.archive))

    def test_wrong_drive_refuses_before_reading_unintended_file(self):
        if os.name!='nt':self.skipTest('Windows drive letter')
        drive=os.path.splitdrive(str(self.root))[0]
        wrong='C:' if drive.upper()!='C:' else 'D:'
        with self.assertRaises(runner.PhaseTransportHeld):self._run(str(self.archive),archive=wrong+str(self.archive)[2:])

    def test_relative_reported_path_refuses(self):
        with self.assertRaises(runner.PhaseTransportHeld):self._run(str(self.archive),archive='archive.zip')

    def test_relative_expected_path_refuses(self):
        with self.assertRaises(runner.PhaseTransportHeld):self._run('archive.zip',archive=str(self.archive))

    def test_parent_traversal_refuses(self):
        with self.assertRaises(runner.PhaseTransportHeld):self._run(str(self.archive),archive=str(self.root)+'\\sub\\..\\archive.zip')

    def test_expected_parent_traversal_refuses(self):
        with self.assertRaises(runner.PhaseTransportHeld):self._run(str(self.root)+'\\sub\\..\\archive.zip',archive=str(self.archive))

    def test_nonstring_reported_refuses(self):
        with self.assertRaises(runner.PhaseTransportHeld):self._run(str(self.archive),archive=123)

    def test_nonstring_expected_refuses(self):
        with self.assertRaises(runner.PhaseTransportHeld):self._run(123,archive=str(self.archive))

    def test_none_reported_refuses(self):
        with self.assertRaises(runner.PhaseTransportHeld):self._run(str(self.archive),archive=None)

    def test_none_expected_refuses(self):
        with self.assertRaises(runner.PhaseTransportHeld):self._run(None,archive=str(self.archive))

    def test_wrong_status_refuses(self):
        with self.assertRaises(runner.PhaseTransportHeld):self._run(str(self.archive),status='backup_complete')

    def test_wrong_profile_hash_refuses(self):
        with self.assertRaises(runner.PhaseTransportHeld):self._run(str(self.archive),profile_sha='0'*64)

    def test_bad_rehearsal_refuses(self):
        with self.assertRaises(runner.PhaseTransportHeld):self._run(str(self.archive),rehearsal='FAIL')

    def test_service_started_refuses(self):
        with self.assertRaises(runner.PhaseTransportHeld):self._run(str(self.archive),service_started=True)

    def test_bad_archive_hash_refuses(self):
        with self.assertRaises(runner.PhaseTransportHeld):self._run(str(self.archive),archive_sha='1'*64)


if __name__=='__main__':unittest.main()
