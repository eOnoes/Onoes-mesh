# QFN074 candidate tests: static cross-check of planned before-backup bindings.
# Pure input comparison only; these tests never run the window or any service.
import ast,copy,sys,unittest
from pathlib import Path

sys.path[:0]=[str(Path(__file__).resolve().parent)]
import cloud_install_entry as entry

H1='a'*64
H2='b'*64
H3='c'*64
H4='d'*64
SENTINEL='C:\\PRIVATE\\SENTINEL-DO-NOT-LEAK-9f3b'


def fixture():
    plan={'backups':{'before':{
        'entryPath':'C:/planned/entry.py','entrySha256':H1,
        'profilePath':'C:/planned/profile.json','profileSha256':H2,
        'resultPath':'C:/planned/result.json'},
        'after':{'entryPath':'C:/planned/entry-after.py'}}}
    owner={'beforeBackup':{
        'entryPath':'C:/planned/entry.py','entrySha256':H1,
        'profilePath':'C:/planned/profile.json','profileSha256':H2},
        'beforeBackupResult':'C:/planned/result.json',
        'beforeArchive':'C:/planned/archive.enc'}
    profile={'resultPath':'C:/planned/result.json','encryptedBackup':'C:/planned/archive.enc'}
    return plan,owner,profile


class OwnerBackupBindingTests(unittest.TestCase):
    def held(self,plan,owner,profile):
        with self.assertRaises(entry.InstallHeld) as caught:
            entry._qualify_owner_backup_bindings(plan,owner,profile)
        message=str(caught.exception)
        self.assertNotIn(SENTINEL,message)
        for value in (str(plan),str(owner),str(profile)):
            if SENTINEL in value:self.assertNotIn(SENTINEL,message)

    def test_success_returns_true_without_mutation(self):
        plan,owner,profile=fixture()
        before=(copy.deepcopy(plan),copy.deepcopy(owner),copy.deepcopy(profile))
        self.assertIs(entry._qualify_owner_backup_bindings(plan,owner,profile),True)
        self.assertEqual((plan,owner,profile),before)

    def test_descriptor_field_mismatch(self):
        for field,replacement in (
            ('entryPath',SENTINEL),('entrySha256',H3),
            ('profilePath',SENTINEL),('profileSha256',H4)):
            plan,owner,profile=fixture()
            owner['beforeBackup'][field]=replacement
            self.held(plan,owner,profile)

    def test_descriptor_field_missing(self):
        for field in ('entryPath','entrySha256','profilePath','profileSha256'):
            plan,owner,profile=fixture()
            del owner['beforeBackup'][field]
            self.held(plan,owner,profile)

    def test_malformed_container_types(self):
        plan,owner,profile=fixture()
        self.held(None,owner,profile)
        self.held(plan,[],profile)
        self.held(plan,owner,False)
        plan2,owner2,profile2=fixture()
        plan2['backups']='not-a-dict'
        self.held(plan2,owner2,profile2)
        plan3,owner3,profile3=fixture()
        plan3['backups']['before']=None
        self.held(plan3,owner3,profile3)
        plan4,owner4,profile4=fixture()
        owner4['beforeBackup']=[owner4['beforeBackup']]
        self.held(plan4,owner4,profile4)

    def test_malformed_hash_shapes(self):
        for field in ('entrySha256','profileSha256'):
            for replacement in ('A'*64,'abc123',H1.upper(),H1[:63],'',None,0):
                plan,owner,profile=fixture()
                owner['beforeBackup'][field]=replacement
                self.held(plan,owner,profile)

    def test_uppercase_planned_hash_holds_even_when_equal(self):
        plan,owner,profile=fixture()
        plan['backups']['before']['entrySha256']=H1.upper()
        owner['beforeBackup']['entrySha256']=H1.upper()
        self.held(plan,owner,profile)

    def test_result_pointer_mismatch_missing_or_nonstr(self):
        for mutate in (
            lambda plan,owner,profile:plan['backups']['before'].__setitem__('resultPath',SENTINEL),
            lambda plan,owner,profile:owner.__setitem__('beforeBackupResult',SENTINEL),
            lambda plan,owner,profile:profile.__setitem__('resultPath',SENTINEL),
            lambda plan,owner,profile:owner.__setitem__('beforeBackupResult',''),
            lambda plan,owner,profile:profile.__setitem__('resultPath',True),
            lambda plan,owner,profile:owner.pop('beforeBackupResult'),
            lambda plan,owner,profile:profile.pop('resultPath')):
            plan,owner,profile=fixture()
            mutate(plan,owner,profile)
            self.held(plan,owner,profile)

    def test_archive_mismatch_missing_or_type(self):
        for mutate in (
            lambda plan,owner,profile:owner.__setitem__('beforeArchive',SENTINEL),
            lambda plan,owner,profile:profile.__setitem__('encryptedBackup',SENTINEL),
            lambda plan,owner,profile:owner.pop('beforeArchive'),
            lambda plan,owner,profile:profile.pop('encryptedBackup'),
            lambda plan,owner,profile:owner.__setitem__('beforeArchive',True),
            lambda plan,owner,profile:profile.__setitem__('encryptedBackup',None)):
            plan,owner,profile=fixture()
            mutate(plan,owner,profile)
            self.held(plan,owner,profile)

    def test_regression_stale_owner_backup_with_valid_hashes_holds(self):
        plan,owner,profile=fixture()
        owner['beforeBackup']['entryPath']='C:/older/entry.py'
        owner['beforeBackup']['profilePath']='C:/older/profile.json'
        self.held(plan,owner,profile)

    def test_extra_unrelated_fields_permitted(self):
        plan,owner,profile=fixture()
        plan['backups']['before']['approvalPath']='C:/planned/approval.json'
        owner['beforeBackup']['note']='unrelated'
        owner['unrelated']=SENTINEL
        profile['archiveCredentialMode']='windows-local'
        before=(copy.deepcopy(plan),copy.deepcopy(owner),copy.deepcopy(profile))
        self.assertIs(entry._qualify_owner_backup_bindings(plan,owner,profile),True)
        self.assertEqual((plan,owner,profile),before)

    def test_preflight_calls_helper_exactly_once_in_before_branch(self):
        tree=ast.parse(Path(entry.__file__).read_text(encoding='utf-8'))
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='CombinedWindow')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='preflight')
        def helper(node):
            return isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='_qualify_owner_backup_bindings'
        calls=[n for n in ast.walk(method) if helper(n)]
        self.assertEqual(len(calls),1)
        loops=[n for n in ast.walk(method) if isinstance(n,ast.For) and isinstance(n.target,ast.Name) and n.target.id=='which']
        branches=[]
        for loop in loops:
            for node in loop.body:
                if not isinstance(node,ast.If):continue
                test=node.test
                if (isinstance(test,ast.Compare) and isinstance(test.left,ast.Name) and test.left.id=='which'
                    and len(test.ops)==1 and isinstance(test.ops[0],ast.Eq) and len(test.comparators)==1
                    and isinstance(test.comparators[0],ast.Constant) and test.comparators[0].value=='before'):
                    if any(helper(n) for n in ast.walk(node)):branches.append((loop,node))
        self.assertEqual(len(branches),1)
        loop,branch=branches[0]
        reads=[n for n in loop.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='profile' for t in n.targets)
            and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='read']
        self.assertEqual(len(reads),1)
        self.assertLess(reads[0].lineno,branch.lineno)

    def test_required_master_descriptor_fields_missing(self):
        for field in ('entryPath','entrySha256','profilePath','profileSha256'):
            with self.subTest(field=field):
                plan,owner,profile=fixture()
                del plan['backups']['before'][field]
                self.held(plan,owner,profile)

    def test_equal_empty_or_malformed_descriptor_fields_refused(self):
        for field in ('entryPath','entrySha256','profilePath','profileSha256'):
            for value in ('',None,True,17,[],{}):
                with self.subTest(field=field,value=value):
                    plan,owner,profile=fixture()
                    owner['beforeBackup'][field]=value
                    plan['backups']['before'][field]=value
                    self.held(plan,owner,profile)

    def test_real_window_coordinator_refuses_stale_inputs_before_any_operation(self):
        from tempfile import TemporaryDirectory
        from cloud_install_window import install_once,CloudWindowHeld
        plan,owner,profile=fixture();owner['beforeBackupResult']='C:/older/result.json'
        operations=[]
        class Adapter:
            def preflight(self,pin,evidence):return entry._qualify_owner_backup_bindings(plan,owner,profile)
            def __getattr__(self,name):
                def operation():operations.append(name);raise AssertionError('No native operation permitted')
                return operation
        with TemporaryDirectory() as temp:
            with self.assertRaises(CloudWindowHeld):install_once(Adapter(),temp,'a'*64)
            self.assertEqual(list(Path(temp).iterdir()),[])
        self.assertEqual(operations,[])


if __name__=='__main__':
    unittest.main()
