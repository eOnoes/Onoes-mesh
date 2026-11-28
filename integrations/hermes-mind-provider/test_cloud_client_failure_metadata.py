# QFN079 bounded client failure-metadata tests.
import hashlib,json,sys,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parent))
import cloud_phase_runner as runner


def record(error_type='ClientHeld',frames=None,privacy=True):
    return {'errorType':error_type,
        'frames':frames if frames is not None else [
            {'file':'cloud_client_entry.py','function':'<module>','line':8},
            {'file':'cloud_client_entry.py','function':'run','line':40},
            {'file':'cloud_client_entry.py','function':'_run_checked','line':61},
            {'file':'cloud_client_entry.py','function':'require','line':97}],
        'messagesAndLocalsExcluded':privacy}


def line(payload):return json.dumps(payload,sort_keys=True).encode()


def one_frame(function,file='cloud_client_entry.py',line_number=10):
    return record(frames=[{'file':file,'function':function,'line':line_number}])


class ClientFailureMetadata(unittest.TestCase):
    def parse(self,payload):return runner.parse_failure_metadata(line(payload))

    def test_client_held_record_accepted(self):
        parsed=self.parse(record())
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed['errorType'],'ClientHeld')
        self.assertEqual([f['function'] for f in parsed['frames']],
            ['<module>','run','_run_checked','require'])
        self.assertIs(parsed['messagesAndLocalsExcluded'],True)

    def test_every_named_client_function_validates(self):
        for function in runner.FAILURE_METADATA_CLIENT_FRAME_FUNCTIONS:
            parsed=self.parse(one_frame(function))
            self.assertIsNotNone(parsed,function)
            self.assertEqual(parsed['frames'][0]['function'],function)

    def test_client_only_names_rejected_on_other_files(self):
        for function in ('_run_checked','approved','installed','private_read','save',
                         'load','_reuse_public_materialization','switch_plan'):
            for other in ('cloud_gateway_entry.py','service_manager.py','cloud_owner_entry.py'):
                self.assertIsNone(self.parse(one_frame(function,file=other)),
                    (function,other))
        for file,function in [('cloud_gateway_entry.py','<module>'),
                ('cloud_owner_entry.py','<module>'),('cloud_owner_entry.py','run'),
                ('cloud_owner_entry.py','read'),('service_manager.py','require')]:
            self.assertIsNotNone(self.parse(one_frame(function,file=file)),(file,function))
        self.assertIsNone(self.parse(one_frame('approved_inputs')),
            'owner-only name must not validate on client')
        self.assertIsNone(self.parse(one_frame('stop')),
            'client entry frame with non-whitelisted stop stays rejected')

    def test_malformed_client_frames_rejected(self):
        self.assertIsNone(self.parse(one_frame('run',file='/opt/data/cloud_client_entry.py')))
        self.assertIsNone(self.parse(one_frame('_weird_helper')))
        for bad in (True,False,'10',0,100001):
            self.assertIsNone(self.parse(one_frame('run',line_number=bad)),repr(bad))
        extra=record(frames=record()['frames']+[{'file':'cloud_client_entry.py',
            'function':'run','line':1,'note':'x'}])
        self.assertIsNone(self.parse(extra))
        polluted=record();polluted['message']='secret'
        self.assertIsNone(self.parse(polluted))
        polluted=record();polluted['frames'][0]['locals']={'secret':'x'}
        self.assertIsNone(self.parse(polluted))
        duplicated=('{"errorType": "ClientHeld", "errorType": "ClientHeld", "frames": '
            +json.dumps(record()['frames'])+', "messagesAndLocalsExcluded": true}')
        self.assertIsNone(runner.parse_failure_metadata(duplicated.encode()))
        self.assertIsNone(runner.parse_failure_metadata(line(record())+b'\xff\xfe'))

    def test_privacy_ambiguity_and_error_type_rejections(self):
        self.assertIsNone(self.parse(record(privacy=False)))
        self.assertIsNone(self.parse(record(error_type='SecretHeld')))
        self.assertIsNone(runner.parse_failure_metadata(
            line(record())+b'\n'+line(record(frames=[{'file':'cloud_client_entry.py',
            'function':'save','line':5}]))))

    def test_safe_summary_excludes_raw_secret_prose(self):
        safe=line(record())
        stderr=('raw secret token=abc123 password=hunter2 during client deliver\n'
            +safe.decode()+'\nlocals hidden secret_local=zzz\n').encode()
        parsed=runner.parse_failure_metadata(stderr)
        self.assertIsNotNone(parsed)
        blob=json.dumps(parsed,sort_keys=True)
        for sentinel in ('secret','abc123','password','hunter2','locals','raw'):
            self.assertNotIn(sentinel,blob)
        self.assertEqual(parsed,record())

    def test_execute_once_journals_only_safe_client_metadata(self):
        class FakeStore:
            def qualify_private_storage(self,path,**kwargs):return Path(path)
        safe=line(record())
        completed=mock.Mock(returncode=1,stdout=b'',
            stderr=('client raw secret token=abc123 kept private\n'+safe.decode()
                +'\nCloud client operation held; preserve private custody.\n').encode())
        expected_stderr_sha=hashlib.sha256(completed.stderr).hexdigest()
        with TemporaryDirectory() as directory:
            store=FakeStore()
            with mock.patch.dict(sys.modules,{'onoes_mind':store,
                'onoes_mind.enrollment_store':store}), \
                mock.patch.object(runner.subprocess,'run',return_value=completed) as child:
                with self.assertRaises(runner.PhaseTransportHeld):
                    runner.execute_once(['synthetic'],evidence=directory,label='client-failure')
            self.assertEqual(child.call_count,1)
            saved=sorted(Path(directory).iterdir())
            self.assertEqual([p.name for p in saved],
                ['client-failure-TRANSPORT-ATTEMPT.json','client-failure-TRANSPORT-RESULT.json'])
            result=json.loads(saved[1].read_text())
            self.assertEqual(result['failureMetadata'],record())
            self.assertEqual(result['stderrSha256'],expected_stderr_sha)
            self.assertEqual(result['stderrBytes'],len(completed.stderr))
            for path in saved:
                blob=path.read_bytes()
                self.assertNotIn(b'abc123',blob)
                self.assertNotIn(b'hunter2',blob)
                self.assertNotIn(b'custody',blob)
                self.assertNotIn(b'raw secret',blob)


if __name__=='__main__':unittest.main()
