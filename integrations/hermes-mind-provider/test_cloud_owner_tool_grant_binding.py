"""Real-file regression for missing or unpinned pre-downtime tool grants."""
import copy,hashlib,sys,unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0,str(Path(__file__).resolve().parent))
import cloud_install_entry as entry

class OwnerToolGrantBindingTests(unittest.TestCase):
    def fixture(self,root):
        path=(Path(root)/'reviewed-tool-grant.json').resolve()
        path.write_bytes(b'{"synthetic":"read-only-grant"}\n')
        plan={'readerPrincipal':'context-cyony','sharedProject':'onoes-mesh',
              'sourcePins':{str(path):hashlib.sha256(path.read_bytes()).hexdigest()}}
        row={'binding':{'principal_id':'context-cyony','project_id':'onoes-mesh','store':{'synthetic':True}},
             'toolGrantPath':str(path),'toolReviewRef':'synthetic-review'}
        return path,plan,{'projectReaderBindings':[row]}

    def held(self,plan,profile):
        with self.assertRaises(entry.InstallHeld) as error:
            entry._qualify_owner_tool_grant_bindings(plan,profile)
        self.assertNotIn('PRIVATE-SENTINEL',str(error.exception))

    def test_valid_profile_row_pointer_and_pin_without_mutation(self):
        with TemporaryDirectory() as root:
            path,plan,profile=self.fixture(root)
            before=(copy.deepcopy(plan),copy.deepcopy(profile),path.read_bytes(),path.stat().st_mtime_ns)
            self.assertIs(entry._qualify_owner_tool_grant_bindings(plan,profile),True)
            self.assertEqual(before,(plan,profile,path.read_bytes(),path.stat().st_mtime_ns))

    def test_missing_file_caught_before_any_grant_creation(self):
        with TemporaryDirectory() as root:
            path,plan,profile=self.fixture(root);path.unlink()
            self.held(plan,profile);self.assertFalse(path.exists())

    def test_missing_changed_or_malformed_pin(self):
        for bad in ('missing','f'*64,'A'*64,'a'*63,None,True,[]):
            with self.subTest(pin=bad),TemporaryDirectory() as root:
                path,plan,profile=self.fixture(root)
                if bad=='missing':plan['sourcePins'].clear()
                else:plan['sourcePins'][str(path)]=bad
                self.held(plan,profile)

    def test_changed_bytes_and_wrong_pinned_file(self):
        with TemporaryDirectory() as root:
            path,plan,profile=self.fixture(root);path.write_bytes(b'changed')
            self.held(plan,profile)
        with TemporaryDirectory() as root:
            path,plan,profile=self.fixture(root);other=path.with_name('other.json');other.write_bytes(path.read_bytes())
            plan['sourcePins']={str(other):hashlib.sha256(other.read_bytes()).hexdigest()}
            self.held(plan,profile)

    def test_wrong_identity_project_and_duplicate_match(self):
        mutations=(lambda p,w:p.update(readerPrincipal='context-other'),lambda p,w:p.update(sharedProject='other'),
            lambda p,w:w['projectReaderBindings'][0]['binding'].update(principal_id='context-other'),
            lambda p,w:w['projectReaderBindings'][0]['binding'].update(project_id='other'),
            lambda p,w:w['projectReaderBindings'].append(copy.deepcopy(w['projectReaderBindings'][0])))
        for mutate in mutations:
            with TemporaryDirectory() as root:
                path,plan,profile=self.fixture(root);mutate(plan,profile);self.held(plan,profile)

    def test_malformed_containers_rows_and_paths(self):
        for bad in (None,[],True,'PRIVATE-SENTINEL'):
            with TemporaryDirectory() as root:
                path,plan,profile=self.fixture(root)
                self.held(bad,profile);self.held(plan,bad)
                profile['projectReaderBindings']=bad;self.held(plan,profile)
        for row in (None,[],{}, {'binding':[]},{'binding':{}}):
            with TemporaryDirectory() as root:
                path,plan,profile=self.fixture(root);profile['projectReaderBindings']=[row];self.held(plan,profile)
        for bad in (None,True,[],{},'', 'PRIVATE-SENTINEL/relative.json'):
            with TemporaryDirectory() as root:
                path,plan,profile=self.fixture(root);profile['projectReaderBindings'][0]['toolGrantPath']=bad;self.held(plan,profile)

    def test_directory_is_not_a_grant_file(self):
        with TemporaryDirectory() as root:
            path,plan,profile=self.fixture(root);profile['projectReaderBindings'][0]['toolGrantPath']=str(path.parent)
            plan['sourcePins'][str(path.parent)]='a'*64;self.held(plan,profile)

    def test_unrelated_fields_and_nonmatching_valid_rows_are_preserved(self):
        with TemporaryDirectory() as root:
            path,plan,profile=self.fixture(root);plan['unrelated']='ok'
            other=copy.deepcopy(profile['projectReaderBindings'][0]);other['binding']['principal_id']='context-other'
            profile['projectReaderBindings'].append(other);before=copy.deepcopy((plan,profile))
            self.assertTrue(entry._qualify_owner_tool_grant_bindings(plan,profile));self.assertEqual(before,(plan,profile))

if __name__=='__main__':unittest.main()
