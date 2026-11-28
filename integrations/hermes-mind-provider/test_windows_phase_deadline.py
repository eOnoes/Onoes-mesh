"""Bounded deadline-envelope tests for NativePhases.local (pure fakes).

No process, SDK, task or native service is ever launched: execute_once is
stubbed with unittest.mock.patch.object on the copied module.
"""
import hashlib,json,sys,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_HERE=str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0,_HERE)

import cloud_phase_runner as runner

sys.path.remove(_HERE)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write(path,text):
    Path(path).write_bytes(text.encode('utf-8'))


class LocalPhaseDeadlineTest(unittest.TestCase):
    """Every guard runs first; only the timeout envelope may differ per phase."""

    def _make(self,root):
        root=Path(root).resolve(strict=True)
        windows_entry=root/'cloud_windows_entry.py'
        owner_entry=root/'cloud_owner_entry.py'
        _write(windows_entry,'# harmless pinned windows entry stub\n')
        _write(owner_entry,'# harmless pinned owner entry stub\n')
        windows_plan_file=root/'windows-plan.json'
        owner_plan_file=root/'owner-plan.json'
        _write(windows_plan_file,json.dumps({'marker':'windows-plan'},sort_keys=True))
        _write(owner_plan_file,json.dumps({'marker':'owner-plan'},sort_keys=True))
        python=Path(sys.executable).resolve(strict=True)
        plan={
            'schema':'onoes-cloud-install-window/v1','agentId':'cyony',
            'readerPrincipal':'context-cyony','sharedProject':'onoes-mesh',
            'modelCalls':0,'maintenanceTask':'ONOes Mesh Workroom Recovery',
            'python':str(python),'pythonSha256':_sha(python),
            'windows':{'entryPath':str(windows_entry),'entrySha256':_sha(windows_entry),
                'planPath':str(windows_plan_file),'planSha256':_sha(windows_plan_file),
                'authorizationPath':str(root/'owner-authorization.json')},
            'owner':{'entryPath':str(owner_entry),'entrySha256':_sha(owner_entry),
                'planPath':str(owner_plan_file),'planSha256':_sha(owner_plan_file),
                'authorizationPath':str(root/'owner-authorization.json')},
        }
        phases=runner.NativePhases.__new__(runner.NativePhases)
        phases.plan=plan
        phases.evidence=root/'evidence'
        return phases,plan,python,windows_entry,owner_entry

    def _stub(self):
        calls=[]
        def fake_execute_once(argv,*,evidence,label,stdin=None,private_stdout=False,timeout=180):
            calls.append({'argv':list(argv),'evidence':evidence,'label':label,'timeout':timeout})
            return {'stubbed':True}
        return calls,fake_execute_once

    def test_mutating_windows_phases_get_600(self):
        with TemporaryDirectory() as td:
            phases,plan,python,windows_entry,_=self._make(td)
            calls,fake=self._stub()
            with mock.patch.object(runner,'execute_once',side_effect=fake):
                for phase in ('retire-old','retire-new','start-new','start-original'):
                    value=phases.local('windows',phase,label='win-'+phase)
                    self.assertEqual(value,{'stubbed':True})
            self.assertEqual(len(calls),4)
            for phase,call in zip(('retire-old','retire-new','start-new','start-original'),calls):
                self.assertEqual(call['timeout'],600)
                self.assertEqual(call['argv'],[str(python),'-I','-B',str(windows_entry),phase,
                    plan['windows']['planPath'],plan['windows']['planSha256'],
                    plan['windows']['authorizationPath']])
                self.assertEqual(call['evidence'],phases.evidence)
                self.assertEqual(call['label'],'win-'+phase)

    def test_other_windows_phases_get_180(self):
        with TemporaryDirectory() as td:
            phases,plan,python,windows_entry,_=self._make(td)
            calls,fake=self._stub()
            with mock.patch.object(runner,'execute_once',side_effect=fake):
                for phase in ('inspect-old','inspect-new','restore-original'):
                    phases.local('windows',phase,label='win-'+phase)
            self.assertEqual(len(calls),3)
            for phase,call in zip(('inspect-old','inspect-new','restore-original'),calls):
                self.assertEqual(call['timeout'],180)
                self.assertEqual(call['argv'],[str(python),'-I','-B',str(windows_entry),phase,
                    plan['windows']['planPath'],plan['windows']['planSha256'],
                    plan['windows']['authorizationPath']])
                self.assertEqual(call['evidence'],phases.evidence)
                self.assertEqual(call['label'],'win-'+phase)

    def test_owner_admit_revoke_get_180(self):
        with TemporaryDirectory() as td:
            phases,plan,python,_,owner_entry=self._make(td)
            calls,fake=self._stub()
            with mock.patch.object(runner,'execute_once',side_effect=fake):
                for phase in ('admit','revoke'):
                    phases.local('owner',phase,label='own-'+phase)
            self.assertEqual(len(calls),2)
            for phase,call in zip(('admit','revoke'),calls):
                self.assertEqual(call['timeout'],180)
                self.assertEqual(call['argv'],[str(python),'-I','-B',str(owner_entry),phase,
                    plan['owner']['planPath'],plan['owner']['planSha256'],
                    plan['owner']['authorizationPath']])
                self.assertEqual(call['evidence'],phases.evidence)
                self.assertEqual(call['label'],'own-'+phase)

    def test_invalid_kind_or_phase_refuses_before_execute(self):
        with TemporaryDirectory() as td:
            phases,_,_,_,_=self._make(td)
            calls,fake=self._stub()
            with mock.patch.object(runner,'execute_once',side_effect=fake):
                for kind,phase in (('gateway','stop'),('client','capture'),('windows','bogus'),
                        ('owner','retire-old'),('bogus','admit')):
                    with self.assertRaises(runner.PhaseTransportHeld):
                        phases.local(kind,phase,label='bad-case')
            self.assertEqual(calls,[])

    def test_changed_entry_python_or_plan_digest_refuses_before_execute(self):
        with TemporaryDirectory() as td:
            phases,plan,python,windows_entry,_=self._make(td)
            calls,fake=self._stub()

            plan=phases.plan
            tampered=json.loads(json.dumps(plan))
            tampered['windows']['entrySha256']='0'*64
            phases.plan=tampered
            with mock.patch.object(runner,'execute_once',side_effect=fake):
                with self.assertRaises(runner.PhaseTransportHeld):
                    phases.local('windows','retire-old',label='tamper-entry')

            phases.plan=json.loads(json.dumps(plan))
            phases.plan['windows']['planSha256']='1'*64
            with mock.patch.object(runner,'execute_once',side_effect=fake):
                with self.assertRaises(runner.PhaseTransportHeld):
                    phases.local('windows','retire-old',label='tamper-plan')

            phases.plan=json.loads(json.dumps(plan))
            phases.plan['pythonSha256']='2'*64
            with mock.patch.object(runner,'execute_once',side_effect=fake):
                with self.assertRaises(runner.PhaseTransportHeld):
                    phases.local('windows','retire-old',label='tamper-python')

            phases.plan=json.loads(json.dumps(plan))
            _write(windows_entry,'# replaced content after pinning\n')
            with mock.patch.object(runner,'execute_once',side_effect=fake):
                with self.assertRaises(runner.PhaseTransportHeld):
                    phases.local('windows','retire-old',label='tamper-entry-file')
            self.assertEqual(calls,[])


if __name__=='__main__':
    unittest.main()
