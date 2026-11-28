"""Deterministic tests for the sanitized failure-metadata overlay.

No real SSH, network, Mind service or child process is launched here. The
pinned child transport is mocked and qualify_private_storage is injected as a
fake, so only local TemporaryDirectory journals are written.
"""
import hashlib,json,subprocess,sys,types,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parent))
import cloud_phase_runner as runner


def valid_record_bytes(error_type='RuntimeError',frames=None,privacy='true'):
    if frames is None:frames='{"file":"service_manager.py","function":"stop","line":1}'
    return ('{"errorType":"%s","frames":[%s],"messagesAndLocalsExcluded":%s}'%(error_type,frames,privacy)).encode()


VALID_LINE=('{"errorType":"RuntimeError","frames":[{"file":"cloud_gateway_entry.py",'
    '"function":"main","line":42}],"messagesAndLocalsExcluded":true}')
VALID_LINE_2=('{"errorType":"TimeoutExpired","frames":[{"file":"service_manager.py",'
    '"function":"stop","line":7}],"messagesAndLocalsExcluded":true}')
SECRET_PROSE=('Traceback (most recent call last): token=super-secret-value '
    'local={"password":"hunter2"} path=/opt/data/private/owner-plan.json')


class ParseBasics(unittest.TestCase):
    def test_valid_record_beside_secret_like_prose_returns_only_sanitized_metadata(self):
        stderr=('\r\n'+SECRET_PROSE+'\r\n'+VALID_LINE+'\r\n'+SECRET_PROSE+'\r\n').encode()
        value=runner.parse_failure_metadata(stderr)
        self.assertIsNotNone(value)
        self.assertEqual(set(value),{'errorType','frames','messagesAndLocalsExcluded'})
        self.assertEqual(value['errorType'],'RuntimeError')
        self.assertEqual(value['messagesAndLocalsExcluded'],True)
        self.assertEqual(value['frames'],[{'file':'cloud_gateway_entry.py','function':'main','line':42}])
        rendered=repr(value)
        for fragment in ('secret','hunter2','Traceback','prose','/opt/data/private'):
            self.assertNotIn(fragment,rendered)

    def test_returned_frames_are_copies(self):
        value=runner.parse_failure_metadata(VALID_LINE.encode())
        value['frames'][0]['line']=999
        again=runner.parse_failure_metadata(VALID_LINE.encode())
        self.assertEqual(again['frames'][0]['line'],42)

    def test_valid_record_alone(self):
        value=runner.parse_failure_metadata(VALID_LINE.encode())
        self.assertEqual(value['errorType'],'RuntimeError')

    def test_all_allowed_error_types_accepted(self):
        for error_type in runner.FAILURE_METADATA_ERROR_TYPES:
            line=('{"errorType":"%s","frames":[{"file":"cloud_native_gateway.py",'
                '"function":"run_phase","line":1}],"messagesAndLocalsExcluded":true}')%error_type
            value=runner.parse_failure_metadata(line.encode())
            self.assertIsNotNone(value,error_type)
            self.assertEqual(value['errorType'],error_type)

    def test_frame_bounds_and_functions_accepted(self):
        frames=[{'file':'service_manager.py','function':'_write_gateway_desired_state','line':100000}]
        line=('{"errorType":"OSError","frames":%s,"messagesAndLocalsExcluded":true}'%
            ('['+','.join('{"file":"service_manager.py","function":"stop","line":%d}'%i
                for i in range(1,13))+']')).encode()
        self.assertEqual(len(runner.parse_failure_metadata(line)['frames']),12)
        self.assertEqual(frames[0]['line'],100000)


class ParseRejections(unittest.TestCase):
    def assert_none(self,stderr):self.assertIsNone(runner.parse_failure_metadata(stderr))

    def test_non_bytes_and_sentinel(self):
        self.assert_none(VALID_LINE)
        self.assert_none(None)
        self.assert_none(123)
        self.assert_none({'errorType':'RuntimeError'})

    def test_too_many_bytes(self):
        padding=b'#'*runner.FAILURE_METADATA_MAX_BYTES
        self.assert_none(padding+b'\n'+VALID_LINE.encode())

    def test_non_utf8_bytes(self):
        self.assert_none(b'\xff\xfe\x00'+VALID_LINE.encode())

    def test_overlong_line_rejected(self):
        padding=' '*runner.FAILURE_METADATA_MAX_LINE_CHARS
        self.assert_none((padding+VALID_LINE+'\n').encode())

    def test_overlong_unrelated_prose_does_not_invalidate_valid_line(self):
        padding='#'*runner.FAILURE_METADATA_MAX_LINE_CHARS
        stderr=(padding+'\n'+VALID_LINE+'\n').encode()
        self.assertLessEqual(len(stderr),runner.FAILURE_METADATA_MAX_BYTES)
        value=runner.parse_failure_metadata(stderr)
        self.assertIsNotNone(value)
        self.assertEqual(set(value),{'errorType','frames','messagesAndLocalsExcluded'})
        self.assertEqual(value['errorType'],'RuntimeError')
        self.assertEqual(value['frames'],[{'file':'cloud_gateway_entry.py','function':'main','line':42}])

    def test_malformed_json(self):
        self.assert_none(b'{"errorType":"RuntimeError",,,}\n')
        self.assert_none(b'{')

    def test_duplicate_json_keys(self):
        self.assert_none(('{"errorType":"RuntimeError","errorType":"ValueError","frames":'
            '[{"file":"service_manager.py","function":"stop","line":1}],'
            '"messagesAndLocalsExcluded":true}').encode())
        self.assert_none(('{"errorType":"RuntimeError","frames":[{"file":"service_manager.py",'
            '"function":"stop","line":1,"line":2}],"messagesAndLocalsExcluded":true}').encode())

    def test_non_dict_json(self):
        self.assert_none(b'[1,2,3]\n')
        self.assert_none(b'"RuntimeError"\n')
        self.assert_none(b'{}\n')

    def test_extra_and_missing_keys(self):
        self.assert_none(('{"errorType":"RuntimeError","frames":[{"file":"service_manager.py",'
            '"function":"stop","line":1}],"messagesAndLocalsExcluded":true,"message":"leak"}').encode())
        self.assert_none(b'{"errorType":"RuntimeError","messagesAndLocalsExcluded":true}\n')
        self.assert_none(('{"errorType":"RuntimeError","frames":[{"file":"service_manager.py",'
            '"function":"stop"}],"messagesAndLocalsExcluded":true}').encode())

    def test_privacy_flag_false_or_numeric(self):
        self.assert_none(('{"errorType":"RuntimeError","frames":[{"file":"service_manager.py",'
            '"function":"stop","line":1}],"messagesAndLocalsExcluded":false}').encode())
        self.assert_none(('{"errorType":"RuntimeError","frames":[{"file":"service_manager.py",'
            '"function":"stop","line":1}],"messagesAndLocalsExcluded":1}').encode())
        self.assert_none(('{"errorType":"RuntimeError","frames":[{"file":"service_manager.py",'
            '"function":"stop","line":1}],"messagesAndLocalsExcluded":0}').encode())

    def test_unknown_error_type(self):
        self.assert_none(('{"errorType":"SecretInternalFailure","frames":[{"file":"service_manager.py",'
            '"function":"stop","line":1}],"messagesAndLocalsExcluded":true}').encode())

    def test_suspicious_frame_field_not_stripped(self):
        self.assert_none(('{"errorType":"RuntimeError","frames":[{"file":"service_manager.py",'
            '"function":"stop","line":1,"message":"private locals"}],'
            '"messagesAndLocalsExcluded":true}').encode())

    def test_unknown_frame_file_function_and_fullpath(self):
        for file_name in ('evil_entry.py','/opt/data/evil_entry.py','/etc/passwd','cloud_client_entry.py'):
            self.assert_none(('{"errorType":"RuntimeError","frames":[{"file":"%s",'
                '"function":"stop","line":1}],"messagesAndLocalsExcluded":true}')%file_name)
        self.assert_none(('{"errorType":"RuntimeError","frames":[{"file":"service_manager.py",'
            '"function":"exec_phase","line":1}],"messagesAndLocalsExcluded":true}').encode())

    def test_bad_line_types_and_bounds(self):
        for line_json in ('"42"','42.0','true','false','0','-5','100001','null'):
            self.assert_none(('{"errorType":"RuntimeError","frames":[{"file":"service_manager.py",'
                '"function":"stop","line":%s}],"messagesAndLocalsExcluded":true}')%line_json)

    def test_frames_shape_rejected(self):
        for frames in ('[]','12','null','{"file":"service_manager.py","function":"stop","line":1}',
            '"[service_manager.py]"'):
            self.assert_none(('{"errorType":"RuntimeError","frames":%s,'
                '"messagesAndLocalsExcluded":true}')%frames)

    def test_more_than_twelve_frames(self):
        frames=','.join('{"file":"service_manager.py","function":"stop","line":%d}'%i for i in range(1,14))
        self.assert_none(('{"errorType":"RuntimeError","frames":[%s],'
            '"messagesAndLocalsExcluded":true}')%frames)

    def test_frames_element_types(self):
        self.assert_none(b'{"errorType":"RuntimeError","frames":["main"],"messagesAndLocalsExcluded":true}\n')
        self.assert_none(b'{"errorType":"RuntimeError","frames":[["main"]],"messagesAndLocalsExcluded":true}\n')

    def test_multiple_valid_lines_are_ambiguous(self):
        self.assert_none((VALID_LINE+'\n'+VALID_LINE_2).encode())
        self.assert_none((VALID_LINE+'\n'+VALID_LINE).encode())

    def test_prose_only_and_empty(self):
        self.assert_none(SECRET_PROSE.encode())
        self.assert_none(b'')

    def test_prose_wrapping_invalid_json_never_returns_text(self):
        self.assert_none(('phase failed '+VALID_LINE[:-1]+' truncated').encode())


class ExecuteOnceIntegration(unittest.TestCase):
    """Injected fake qualify_private_storage + mocked subprocess.run only."""

    def setUp(self):
        module=types.ModuleType('onoes_mind')
        store=types.ModuleType('onoes_mind.enrollment_store')
        store.qualify_private_storage=lambda path,kind='directory':Path(path)
        module.enrollment_store=store
        patch=mock.patch.dict(sys.modules,{'onoes_mind':module,'onoes_mind.enrollment_store':store})
        patch.start()
        self.addCleanup(patch.stop)

    def _journal(self,directory,label):
        path=Path(directory)/(label+'-TRANSPORT-RESULT.json')
        return json.loads(path.read_bytes())

    def test_nonzero_child_journals_sanitized_metadata_then_raises(self):
        stderr=(SECRET_PROSE+'\r\n'+VALID_LINE+'\r\n').encode()
        with TemporaryDirectory() as directory:
            completed=mock.Mock(returncode=3,stdout=b'',stderr=stderr)
            with mock.patch.object(runner.subprocess,'run',return_value=completed) as run:
                with self.assertRaises(runner.PhaseTransportHeld):
                    runner.execute_once(['python','-c','x'],evidence=directory,label='phase-fail')
            self.assertEqual(1,run.call_count)
            journal=self._journal(directory,'phase-fail')
            self.assertEqual(journal['exitCode'],3)
            self.assertEqual(set(journal['failureMetadata']),{'errorType','frames','messagesAndLocalsExcluded'})
            self.assertEqual(journal['failureMetadata']['errorType'],'RuntimeError')
            self.assertEqual(journal['failureMetadata']['frames'],
                [{'file':'cloud_gateway_entry.py','function':'main','line':42}])
            self.assertIs(journal['failureMetadata']['messagesAndLocalsExcluded'],True)

    def test_raw_secret_prose_absent_from_saved_journal(self):
        stderr=(SECRET_PROSE+'\r\n'+VALID_LINE+'\r\n').encode()
        with TemporaryDirectory() as directory:
            completed=mock.Mock(returncode=1,stdout=b'',stderr=stderr)
            with mock.patch.object(runner.subprocess,'run',return_value=completed):
                with self.assertRaises(runner.PhaseTransportHeld):
                    runner.execute_once(['python','-c','x'],evidence=directory,label='phase-secret')
            blob=b''.join(path.read_bytes() for path in sorted(Path(directory).rglob('*')) if path.is_file())
            for fragment in (b'secret',b'hunter2',b'Traceback',b'/opt/data/private'):
                self.assertNotIn(fragment,blob)

    def test_existing_size_and_hash_still_present(self):
        stderr=(SECRET_PROSE+'\r\n'+VALID_LINE+'\r\n').encode()
        with TemporaryDirectory() as directory:
            completed=mock.Mock(returncode=9,stdout=b'out',stderr=stderr)
            with mock.patch.object(runner.subprocess,'run',return_value=completed):
                with self.assertRaises(runner.PhaseTransportHeld):
                    runner.execute_once(['python','-c','x'],evidence=directory,label='phase-hash')
            journal=self._journal(directory,'phase-hash')
            self.assertEqual(journal['stderrBytes'],len(stderr))
            self.assertEqual(journal['stderrSha256'],hashlib.sha256(stderr).hexdigest())
            self.assertEqual(journal['stdoutBytes'],3)
            self.assertEqual(journal['stdoutSha256'],hashlib.sha256(b'out').hexdigest())
            self.assertIs(journal['privateStdioExcluded'],True)
            self.assertFalse((Path(directory)/'phase-hash-TRANSPORT-UNKNOWN.json').exists())

    def test_success_stderr_never_recorded_as_metadata(self):
        stderr=VALID_LINE.encode()
        with TemporaryDirectory() as directory:
            completed=mock.Mock(returncode=0,stdout=b'{"ok":true}',stderr=stderr)
            with mock.patch.object(runner.subprocess,'run',return_value=completed):
                value=runner.execute_once(['python','-c','x'],evidence=directory,label='phase-ok')
            self.assertEqual(value,{'ok':True})
            journal=self._journal(directory,'phase-ok')
            self.assertNotIn('failureMetadata',journal)
            self.assertEqual(journal['exitCode'],0)
            self.assertEqual(journal['stderrBytes'],len(stderr))

    def test_malformed_nonzero_stderr_has_no_metadata(self):
        for stderr in (b'phase failed, see console\n',b'{"errorType":"RuntimeError",,}\n',
        valid_record_bytes('RuntimeError','{"file":"service_manager.py","function":"stop","line":1}','false'),
        valid_record_bytes('RuntimeError','{"file":"service_manager.py","function":"stop","line":1,'
            '"message":"'+SECRET_PROSE+'"}'),
            (VALID_LINE+'\n'+VALID_LINE_2).encode(),b'\xff\xfe'+VALID_LINE.encode()):
                with TemporaryDirectory() as directory:
                    completed=mock.Mock(returncode=4,stdout=b'',stderr=stderr)
                    with mock.patch.object(runner.subprocess,'run',return_value=completed):
                        with self.assertRaises(runner.PhaseTransportHeld):
                            runner.execute_once(['python','-c','x'],evidence=directory,label='phase-bad')
                    journal=self._journal(directory,'phase-bad')
                    self.assertNotIn('failureMetadata',journal)
                    self.assertIn('stderrSha256',journal)

    def test_timeout_stays_unknown_without_metadata_or_retry(self):
        with TemporaryDirectory() as directory:
            with mock.patch.object(runner.subprocess,'run',
                side_effect=runner.subprocess.TimeoutExpired(['python'],5)) as run:
                with self.assertRaises(runner.PhaseTransportHeld):
                    runner.execute_once(['python','-c','x'],evidence=directory,label='phase-timeout',timeout=5)
            self.assertEqual(1,run.call_count)
            self.assertFalse((Path(directory)/'phase-timeout-TRANSPORT-RESULT.json').exists())
            unknown=Path(directory)/'phase-timeout-TRANSPORT-UNKNOWN.json'
            self.assertTrue(unknown.exists())
            saved=json.loads(unknown.read_bytes())
            self.assertEqual(saved['remoteActorRetirement'],'NOT_PROVEN')
            self.assertIs(saved['automaticRetry'],False)
            self.assertNotIn('failureMetadata',saved)
            self.assertEqual(saved['errorType'],'TimeoutExpired')
            self.assertFalse(any(p.name.endswith('-TRANSPORT-RESULT.json')
                for p in Path(directory).iterdir()))


MODULE_LINE=('{"errorType":"EntryHeld","frames":[{"file":"cloud_gateway_entry.py",'
    '"function":"<module>","line":251}],"messagesAndLocalsExcluded":true}')


def module_frame(file_name,line='251'):
    return ('{"errorType":"EntryHeld","frames":[{"file":"%s","function":"<module>",'
        '"line":%s}],"messagesAndLocalsExcluded":true}')%(file_name,line)


class ModuleFrameAllowance(unittest.TestCase):
    """<module> is accepted ONLY for the exact cloud_gateway_entry.py file."""

    def test_module_frame_on_cloud_gateway_entry_accepted(self):
        value=runner.parse_failure_metadata(MODULE_LINE.encode())
        self.assertIsNotNone(value)
        self.assertEqual(value['errorType'],'EntryHeld')
        self.assertEqual(value['frames'],
            [{'file':'cloud_gateway_entry.py','function':'<module>','line':251}])
        self.assertIs(value['messagesAndLocalsExcluded'],True)

    def test_module_frame_alongside_main_frame_accepted(self):
        stderr=('{"errorType":"EntryHeld","frames":[{"file":"cloud_gateway_entry.py",'
            '"function":"<module>","line":251},{"file":"cloud_gateway_entry.py",'
            '"function":"main","line":243}],"messagesAndLocalsExcluded":true}').encode()
        value=runner.parse_failure_metadata(stderr)
        self.assertIsNotNone(value)
        self.assertEqual([f['function'] for f in value['frames']],['<module>','main'])

    def test_module_frame_rejected_on_other_allowed_files(self):
        for file_name in ('service_manager.py','cloud_native_gateway.py'):
            self.assertIsNone(runner.parse_failure_metadata(module_frame(file_name).encode()),file_name)

    def test_module_frame_rejected_on_unknown_and_full_paths(self):
        for file_name in ('evil_entry.py','cloud_client_entry.py','/opt/data/cloud_gateway_entry.py',
            'C:\\opt\\data\\cloud_gateway_entry.py','./cloud_gateway_entry.py',''):
            self.assertIsNone(runner.parse_failure_metadata(module_frame(file_name).encode()),file_name)

    def test_module_frame_line_bounds_and_extra_fields_still_rejected(self):
        for line_json in ('"251"','251.0','true','0','-5','100001','null'):
            self.assertIsNone(runner.parse_failure_metadata(
                module_frame('cloud_gateway_entry.py',line_json).encode()),line_json)
        self.assertIsNone(runner.parse_failure_metadata(
            ('{"errorType":"EntryHeld","frames":[{"file":"cloud_gateway_entry.py",'
                '"function":"<module>","line":251,"message":"private locals"}],'
                '"messagesAndLocalsExcluded":true}').encode()))
        self.assertIsNone(runner.parse_failure_metadata(
            ('{"errorType":"EntryHeld","frames":[{"file":"cloud_gateway_entry.py",'
                '"function":"<module>"}],"messagesAndLocalsExcluded":true}').encode()))

    def test_module_allow_list_is_not_broadened(self):
        self.assertNotIn('<module>',runner.FAILURE_METADATA_FRAME_FUNCTIONS)
        self.assertIn('main',runner.FAILURE_METADATA_FRAME_FUNCTIONS)
        self.assertIn('service_manager.py',runner.FAILURE_METADATA_FRAME_FILES)
        self.assertIsNotNone(runner.parse_failure_metadata(
            ('{"errorType":"EntryHeld","frames":[{"file":"service_manager.py",'
                '"function":"main","line":1}],"messagesAndLocalsExcluded":true}').encode()))
        self.assertIsNone(runner.parse_failure_metadata(module_frame('service_manager.py').encode()))


class RealEntrySubprocessRegression(unittest.TestCase):
    """One real local child of the adjacent pinned entry, called with no arguments.

    Wrong argc fails inside main() before any plan read, OS-specific operation,
    network or service action; only the exit code, empty stdout and the entry's
    own sanitized stderr summary are examined here.
    """

    ENTRY=Path(__file__).resolve().parent/'cloud_gateway_entry.py'

    def test_wrong_argc_child_yields_entry_held_module_frame(self):
        self.assertTrue(self.ENTRY.is_file())
        completed=subprocess.run([sys.executable,'-I','-B',str(self.ENTRY)],
            capture_output=True,timeout=10)
        self.assertEqual(completed.returncode,1)
        self.assertEqual(completed.stdout,b'')
        value=runner.parse_failure_metadata(completed.stderr)
        self.assertIsNotNone(value)
        self.assertEqual(value['errorType'],'EntryHeld')
        module_frames=[f for f in value['frames']
            if f['file']=='cloud_gateway_entry.py' and f['function']=='<module>']
        self.assertEqual(len(module_frames),1)
        self.assertIsInstance(module_frames[0]['line'],int)
        self.assertGreater(module_frames[0]['line'],0)
        self.assertIs(value['messagesAndLocalsExcluded'],True)
        self.assertEqual(set(value),{'errorType','frames','messagesAndLocalsExcluded'})
        for frame in value['frames']:
            self.assertEqual(set(frame),{'file','function','line'})
            self.assertEqual(frame['file'],'cloud_gateway_entry.py')
            self.assertNotIn('\\',frame['file'])
            self.assertNotIn('/',frame['file'])
        rendered=repr(value)
        for fragment in ('Cloud phase held','preserve','unconfirmed','Traceback','/opt','sys.argv'):
            self.assertNotIn(fragment,rendered)
        for line in completed.stderr.decode('utf-8','replace').splitlines():
            if line.strip().startswith('{') and line.strip().endswith('}'):continue
            self.assertNotIn(self.ENTRY.name+'\\',line)


class ModuleFrameExecuteOnceIntegration(unittest.TestCase):
    """Accepted module-frame metadata is journalled yet the nonzero child still raises."""

    def setUp(self):
        module=types.ModuleType('onoes_mind')
        store=types.ModuleType('onoes_mind.enrollment_store')
        store.qualify_private_storage=lambda path,kind='directory':Path(path)
        module.enrollment_store=store
        patch=mock.patch.dict(sys.modules,{'onoes_mind':module,'onoes_mind.enrollment_store':store})
        patch.start()
        self.addCleanup(patch.stop)

    def test_module_metadata_journalled_and_still_raises(self):
        stderr=(SECRET_PROSE+'\r\n'+MODULE_LINE+'\r\n').encode()
        with TemporaryDirectory() as directory:
            completed=mock.Mock(returncode=1,stdout=b'',stderr=stderr)
            with mock.patch.object(runner.subprocess,'run',return_value=completed) as run:
                with self.assertRaises(runner.PhaseTransportHeld):
                    runner.execute_once([sys.executable,'-I','-B','cloud_gateway_entry.py'],
                        evidence=directory,label='phase-module-frame')
            self.assertEqual(1,run.call_count)
            journal=json.loads((Path(directory)/'phase-module-frame-TRANSPORT-RESULT.json').read_bytes())
            self.assertEqual(journal['exitCode'],1)
            self.assertEqual(journal['failureMetadata']['errorType'],'EntryHeld')
            self.assertEqual(journal['failureMetadata']['frames'],
                [{'file':'cloud_gateway_entry.py','function':'<module>','line':251}])
            self.assertIs(journal['failureMetadata']['messagesAndLocalsExcluded'],True)
            self.assertFalse((Path(directory)/'phase-module-frame-TRANSPORT-UNKNOWN.json').exists())
            blob=b''.join(path.read_bytes() for path in sorted(Path(directory).rglob('*')) if path.is_file())
            for fragment in (b'secret',b'hunter2',b'Traceback',b'/opt/data/private'):
                self.assertNotIn(fragment,blob)


if __name__=='__main__':
    unittest.main()
