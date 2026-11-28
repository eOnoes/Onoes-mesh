"""Standalone unittests for the Windows template binding preflight guard.

Standard library only. No SDK, task, process, service, SSH, model or database
access. The fake helper files are never imported or executed by the module.
"""
import ast,hashlib,json,os,sys,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parent))

import cloud_install_entry as entry

CUTOVER_SOURCE=(b'"""Frozen cutover helper placeholder."""\n'
    b'READY = True\n')
CONTROLS_SOURCE=(b'raise RuntimeError("module code must never execute during validation")\n'
    b'class MindRoles:\n    pass\n')
ENTRY_SOURCE=b'# harmless fake cloud entry module\nVALUE = 1\n'


def sha(raw):return hashlib.sha256(raw).hexdigest()

_UNSET=object()


class BindingGuardTests(unittest.TestCase):
    def setUp(self):
        self._directory=TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root=Path(self._directory.name).resolve(strict=True)
        self.entry_path=self.root/'cloud_install_entry.py'
        self.cutover_path=self.root/'cloud_windows_cutover.py'
        self.controls_path=self.root/'controls.py'
        self.entry_path.write_bytes(ENTRY_SOURCE)
        self.cutover_path.write_bytes(CUTOVER_SOURCE)
        self.controls_path.write_bytes(CONTROLS_SOURCE)
        self.entry_sha=sha(self.entry_path.read_bytes())
        self.cutover_sha=sha(self.cutover_path.read_bytes())
        self.controls_sha=sha(self.controls_path.read_bytes())

    def plan(self):
        return {'windows':{'entryPath':str(self.entry_path),'entrySha256':self.entry_sha},
            'sourcePins':{str(self.cutover_path):self.cutover_sha,str(self.controls_path):self.controls_sha}}

    def body(self):
        return {'cutoverSha256':self.cutover_sha,'nativeControlsPath':str(self.controls_path),
            'nativeControlsSha256':self.controls_sha}

    def assert_held(self,plan=_UNSET,body=_UNSET):
        with self.assertRaises(entry.InstallHeld):
            entry._qualify_windows_template_bindings(
                self.plan() if plan is _UNSET else plan,
                self.body() if body is _UNSET else body)

    def test_valid_exact_pinned_inputs(self):
        self.assertIs(entry._qualify_windows_template_bindings(self.plan(),self.body()),True)

    def test_each_missing_field(self):
        for name in ('cutoverSha256','nativeControlsPath','nativeControlsSha256'):
            body=self.body();del body[name]
            self.assert_held(body=body)

    def test_explicit_none_reaches_api(self):
        for name in ('cutoverSha256','nativeControlsPath','nativeControlsSha256'):
            body=self.body();body[name]=None
            self.assert_held(body=body)

    def test_blank_malformed_and_bool_sha(self):
        for name in ('cutoverSha256','nativeControlsSha256'):
            for bad in ('','x'*64,sha(b'x').upper(),'g'*64,True,1,sha(b'x')+'0'):
                body=self.body();body[name]=bad
                self.assert_held(body=body)

    def test_blank_nonstring_controls_path(self):
        for bad in ('',True,str(self.controls_path)+' '):
            body=self.body();body['nativeControlsPath']=bad
            self.assert_held(body=body)

    def test_incorrect_body_hash(self):
        body=self.body();body['cutoverSha256']=sha(b'other')
        self.assert_held(body=body)
        body=self.body();body['nativeControlsSha256']=sha(b'other')
        self.assert_held(body=body)

    def test_incorrect_actual_file_digest(self):
        self.cutover_path.write_bytes(CUTOVER_SOURCE+b'# drift\n')
        self.assert_held()

    def test_incorrect_master_sourcepin(self):
        plan=self.plan();plan['sourcePins'][str(self.controls_path)]=sha(b'other')
        self.assert_held(plan=plan)

    def test_unpinned_helpers(self):
        plan=self.plan();del plan['sourcePins'][str(self.cutover_path)]
        self.assert_held(plan=plan)
        plan=self.plan();del plan['sourcePins'][str(self.controls_path)]
        self.assert_held(plan=plan)

    def test_missing_noncanonical_wrong_directory_nonabsolute_controls(self):
        missing=self.root/'absent.py'
        body=self.body();body['nativeControlsPath']=str(missing)
        self.assert_held(body=body)
        nested=self.root/'nested';nested.mkdir()
        noncanonical=str(nested)+os.sep+'..'+os.sep+'controls.py'
        body=self.body();body['nativeControlsPath']=noncanonical
        plan=self.plan();plan['sourcePins'][noncanonical]=self.controls_sha
        self.assert_held(plan=plan,body=body)
        outside_directory=TemporaryDirectory()
        self.addCleanup(outside_directory.cleanup)
        outside=Path(outside_directory.name).resolve(strict=True)
        elsewhere=outside/'controls.py';elsewhere.write_bytes(CONTROLS_SOURCE)
        body=self.body();body['nativeControlsPath']=str(elsewhere)
        self.assert_held(body=body)
        body=self.body();body['nativeControlsPath']='controls.py'
        self.assert_held(body=body)

    def test_explicit_pinned_alternate_sibling_is_valid(self):
        alternate=self.root/'alternate.py';alternate.write_bytes(CONTROLS_SOURCE)
        plan=self.plan();plan['sourcePins'][str(alternate)]=self.controls_sha
        body=self.body();body['nativeControlsPath']=str(alternate)
        self.assertIs(entry._qualify_windows_template_bindings(plan,body),True)

    def test_cutover_symlink_metadata_is_rejected(self):
        original=entry.os.path.islink
        with mock.patch.object(entry.os.path,'islink',side_effect=lambda p: str(p)==str(self.cutover_path) or original(p)):
            self.assert_held()

    def test_source_without_mindroles(self):
        self.controls_path.write_bytes(b'raise RuntimeError("never execute")\nclass Other:\n    pass\n')
        sha_now=sha(self.controls_path.read_bytes())
        plan=self.plan();plan['sourcePins'][str(self.controls_path)]=sha_now
        body=self.body();body['nativeControlsSha256']=sha_now
        self.assert_held(plan=plan,body=body)

    def test_nested_class_is_not_top_level(self):
        self.controls_path.write_bytes(b'raise RuntimeError("never execute")\n'
            b'if True:\n    class MindRoles:\n        pass\n')
        sha_now=sha(self.controls_path.read_bytes())
        plan=self.plan();plan['sourcePins'][str(self.controls_path)]=sha_now
        body=self.body();body['nativeControlsSha256']=sha_now
        self.assert_held(plan=plan,body=body)

    def test_malformed_python(self):
        self.controls_path.write_bytes(b'class MindRoles: pass (((\n')
        sha_now=sha(self.controls_path.read_bytes())
        plan=self.plan();plan['sourcePins'][str(self.controls_path)]=sha_now
        body=self.body();body['nativeControlsSha256']=sha_now
        self.assert_held(plan=plan,body=body)

    def test_non_dict_inputs(self):
        for plan in (None,'plan',[],42):self.assert_held(plan=plan)
        for body in (None,'body',[],42):self.assert_held(body=body)
        self.assert_held(plan=None,body=None)

    def test_missing_malformed_plan_keys(self):
        for key in ('windows','sourcePins'):
            plan=self.plan();del plan[key]
            self.assert_held(plan=plan)
        plan=self.plan();del plan['windows']['entryPath']
        self.assert_held(plan=plan)
        plan=self.plan();plan['windows']['entrySha256']=sha(b'other')
        self.assert_held(plan=plan)
        plan=self.plan();plan['windows']=None
        self.assert_held(plan=plan)

    def test_entry_path_must_be_absolute_canonical(self):
        plan=self.plan();plan['windows']['entryPath']='cloud_install_entry.py'
        self.assert_held(plan=plan)

    def test_module_code_never_executed(self):
        # The controls source raises at import time and both helpers contain
        # module-level side effects that must not run; validation still parses.
        self.controls_path.write_bytes(b'raise RuntimeError("module code must never execute")\n'
            b'class MindRoles:\n    pass\n')
        sha_now=sha(self.controls_path.read_bytes())
        plan=self.plan();plan['sourcePins'][str(self.controls_path)]=sha_now
        body=self.body();body['nativeControlsSha256']=sha_now
        self.assertIs(entry._qualify_windows_template_bindings(plan,body),True)
        self.assertNotIn('cloud_windows_cutover',sys.modules)
        self.assertNotIn('controls',sys.modules)
        tree=ast.parse(self.controls_path.read_bytes())
        self.assertTrue(any(type(node) is ast.Raise for node in tree.body))

    def test_errors_never_echo_values(self):
        body=self.body();body['cutoverSha256']='deadbeef'
        try:
            entry._qualify_windows_template_bindings(self.plan(),body)
        except entry.InstallHeld as error:
            message=str(error)
            self.assertNotIn('deadbeef',message)
            self.assertNotIn(str(self.controls_path),message)
        else:
            self.fail('expected InstallHeld')

    def test_entry_file_cannot_disguise_itself_as_helper(self):
        plan=self.plan()
        body=self.body();body['nativeControlsPath']=str(self.entry_path)
        body['nativeControlsSha256']=self.entry_sha
        plan['sourcePins'][str(self.entry_path)]=self.entry_sha
        self.assert_held(plan=plan,body=body)
        plan=self.plan();plan['windows']['entryPath']=str(self.cutover_path)
        plan['windows']['entrySha256']=self.cutover_sha
        self.assert_held(plan=plan)


class PreflightIntegrationTests(unittest.TestCase):
    SENTINEL=object()

    def window(self,plan,body,task=None,calls=None):
        window=entry.CombinedWindow.__new__(entry.CombinedWindow)
        window.plan=plan;window.pin='pin';window.authorization=self.SENTINEL
        window.test_disposition=self.SENTINEL
        window.root={'journal':Path('journal.json')}
        window.windows_body=body
        window.task=task if task is not None else SimpleNamespace(
            binding=None,status=lambda:self.fail('task lifecycle reached'))
        return window

    def plan(self,entry_path,entry_sha):
        return {'schema':'onoes-cloud-install-window/v1','workspace':str(Path('workspace')),
            'windows':{'entryPath':str(entry_path),'entrySha256':entry_sha}}

    def body(self):
        return {'schema':'onoes-cloud-windows-phases/v1','workspace':str(Path('workspace')),
            'agentId':'cyony','evidence':str(Path('windows-evidence')),
            'maintenance':{'powershell':'powershell','powershellSha256':'p'*64},
            'nativeControlsPath':None,'nativeControlsSha256':None}

    def test_incomplete_template_holds_before_accounting_and_lifecycle(self):
        with TemporaryDirectory() as directory:
            root=Path(directory).resolve(strict=True)
            entry_path=root/'cloud_install_entry.py';entry_path.write_bytes(ENTRY_SOURCE)
            calls=[]
            original=entry._qualify_windows_template_bindings
            def spy(plan,body):
                calls.append('qualify')
                return original(plan,body)
            entry._qualify_windows_template_bindings=spy
            self.addCleanup(setattr,entry,'_qualify_windows_template_bindings',original)
            def accounting(*args):
                calls.append('accounting');return self.SENTINEL
            previous_accounting=entry.test_accounting
            entry.test_accounting=accounting
            self.addCleanup(setattr,entry,'test_accounting',previous_accounting)
            window=self.window(self.plan(entry_path,sha(entry_path.read_bytes())),
                self.body(),task=SimpleNamespace(
                    binding=None,status=lambda:self.fail('task status reached')))
            with self.assertRaises(entry.InstallHeld):
                window.preflight('pin','journal.json')
            self.assertEqual(calls,['qualify'])

    def test_valid_plan_calls_helper_before_test_accounting(self):
        with TemporaryDirectory() as directory:
            root=Path(directory).resolve(strict=True)
            entry_path=root/'cloud_install_entry.py'
            cutover=root/'cloud_windows_cutover.py'
            controls=root/'controls.py'
            entry_path.write_bytes(ENTRY_SOURCE)
            cutover.write_bytes(CUTOVER_SOURCE)
            controls.write_bytes(CONTROLS_SOURCE)
            entry_sha=sha(entry_path.read_bytes())
            plan=self.plan(entry_path,entry_sha)
            plan['sourcePins']={str(cutover):sha(cutover.read_bytes()),
                str(controls):sha(controls.read_bytes())}
            body={'cutoverSha256':sha(cutover.read_bytes()),'nativeControlsPath':str(controls),
                'nativeControlsSha256':sha(controls.read_bytes())}
            calls=[]
            original=entry._qualify_windows_template_bindings
            def spy(p,b):
                calls.append('qualify')
                self.assertIs(p,plan);self.assertIs(b,body)
                return original(p,b)
            entry._qualify_windows_template_bindings=spy
            self.addCleanup(setattr,entry,'_qualify_windows_template_bindings',original)
            window=self.window(plan,body)
            def accounting(*args):
                calls.append('accounting')
                raise entry.InstallHeld('mocked sentinel stop before native operations')
            previous_accounting=entry.test_accounting
            entry.test_accounting=accounting
            self.addCleanup(setattr,entry,'test_accounting',previous_accounting)
            with self.assertRaises(entry.InstallHeld):
                window.preflight('pin','journal.json')
            self.assertEqual(calls,['qualify','accounting'])


if __name__=='__main__':
    unittest.main()
