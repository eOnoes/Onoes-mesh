# QFN076 Linux-only source qualification.
# Static, no-network qualification of bounded READ-ONLY reuse of an approved
# prior PUBLIC client install. Fake sentinels only; no owner/gateway/store API.
import hashlib,importlib.util,json,os,shutil,sys,tempfile,unittest
from pathlib import Path

SPEC=importlib.util.spec_from_file_location('cloud_client_entry_qfn076',
    Path(__file__).with_name('cloud_client_entry.py'))
entry=importlib.util.module_from_spec(SPEC);sys.modules[SPEC.name]=entry;SPEC.loader.exec_module(entry)

SHA=lambda raw:hashlib.sha256(raw).hexdigest()
SDK_NAME='onoes_mind';PLUGIN_NAME='onoes_mind_provider'


class FakePackage:
    def __init__(self,home,files,descriptor,manifest_sha256,pth_raw):
        self.home=home;self.files=files;self._descriptor=descriptor
        self.manifest_sha256=manifest_sha256
        self.python_resolved=str(Path(sys.executable).resolve(strict=True))
        self.python_sha256=SHA(Path(sys.executable).read_bytes())
        self.pth_raw=pth_raw

    def descriptor(self):return dict(self._descriptor)


def build_case(root,*,descriptor_over=None,receipt_over=None,pth_raw=b'import sys; sys.path[0:0]=[]\n',
               unmanifested=None,extra_pth=False,wrong_exec=False,empty_vendor=True,
               custody_records=(),intents_records=(),client_intent_key=False,
               config=b'profiles: original-sentinel\n'):
    root=Path(tempfile.mkdtemp(prefix='case-',dir=str(root)));root.chmod(0o700)
    home=root/'home';home.mkdir(mode=0o700)
    evidence=home/'onoes-cloud-window-current';evidence.mkdir(mode=0o700)
    prior_dir=home/'onoes-cloud-window-prior-01';prior_dir.mkdir(mode=0o700)
    (home/'config.yaml').write_bytes(config)
    sdk=home/'onoes-mind/sdk-4a7c3e3';plugin=home/'plugins/onoes_mind'
    client=home/'onoes-mind/cyony';vendor=client/'vendor'
    runtime=client/'reader-runtime'
    site=runtime/f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages'
    for folder in (sdk/'onoes_mind',plugin,vendor,runtime/'bin',site,
            client/'custody',client/'intents',client/'review'):
        folder.mkdir(parents=True,mode=0o700)
    sdk_init=b'# sdk sentinel\nMARKER = "sdk-4a7c3e3"\n'
    plugin_init=b'# plugin sentinel\nMARKER = "provider"\n'
    files={'onoes-mind/sdk-4a7c3e3/onoes_mind/__init__.py':sdk_init,
           'onoes-mind/sdk-4a7c3e3/scripts/remote_project_stdio.py':b'# entry sentinel\n',
           'plugins/onoes_mind/__init__.py':plugin_init,
           'plugins/onoes_mind/portable.py':b'# portable sentinel\n',
           'plugins/onoes_mind/config.py':b'# config sentinel\n',
           'plugins/onoes_mind/portable_profile.py':b'# profile sentinel\n',
           'plugins/onoes_mind/journal.py':b'# journal sentinel\n',
           'onoes-mind/cyony/review/home-profile.json':b'{"schema": "home-sentinel"}\n',
           'onoes-mind/cyony/review/shared-reader.json':b'{"schema": "reader-sentinel"}\n'}
    for name,raw in files.items():
        path=home/name;path.parent.mkdir(parents=True,exist_ok=True)
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(raw)
    if unmanifested:
        path=home/unmanifested;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(b'# unknown unmanifested code\n')
    if not empty_vendor:
        (vendor/'unexpected-code.py').write_bytes(b'# unknown payload\n')
    pth=site/'onoes-reader-dependencies.pth';pth.write_bytes(pth_raw);pth.chmod(0o600)
    if extra_pth:(site/'rogue.pth').write_bytes(b'# rogue bootstrap\n')
    link=runtime/'bin/python'
    if wrong_exec:
        fake=root/'fake-python-binary';fake.write_bytes(b'# fake binary sentinel\n')
        shutil.copyfile(fake,link)
    else:
        os.symlink(str(Path(sys.executable).resolve(strict=True)),str(link))
    for name in custody_records:(client/'custody'/name).write_bytes(b'custody-record-sentinel')
    for name in intents_records:(client/'intents'/name).write_bytes(b'intent-record-sentinel')
    if client_intent_key:(client/'intent.key').write_bytes(b'intent-key-sentinel')
    metadata={'schema':'onoes-inactive-cloud-client-package/v1','home':str(home),'agentId':'cyony',
        'sdkRoot':str(sdk),'readerPrincipal':'context-cyony','sharedProject':'onoes-mesh',
        'endpoint':'https://sentinel.ts.net/read','homeProfile':str(client/'review/home-profile.json'),
        'homeProfileSha256':SHA(b'{"schema": "home-sentinel"}\n'),
        'readerProfile':str(client/'review/shared-reader.json'),
        'readerProfileSha256':SHA(b'{"schema": "reader-sentinel"}\n'),
        'readerPython':str(link),'readerEntry':str(sdk/'scripts/remote_project_stdio.py'),
        'nativeMcpChanged':False,'readerMcp':'1.26.0','intentKeyCreated':False,
        'manifestSha256':SHA(json.dumps(sorted(files),sort_keys=True).encode()),
        'files':len(files),'payloadBytes':sum(len(v) for v in files.values()),
        'activated':False,'credentialsCreated':False,'configChanged':False}
    if descriptor_over:metadata.update(descriptor_over)
    package=FakePackage(str(home),files,metadata,metadata['manifestSha256'],pth_raw)
    receipt={**metadata,'codeInstalled':True,'readerVersion':'1.26.0',
        'bootstrapPthSha256':SHA(pth_raw),'nativeMcpChanged':False,
        'credentialsCreated':False,'configChanged':False}
    if receipt_over:receipt.update(receipt_over)
    prior_path=prior_dir/'MATERIALIZED.json';prior_path.write_bytes(json.dumps(receipt,sort_keys=True).encode())
    prior_path.chmod(0o600)
    plan={'schema':'onoes-cloud-client-operation/v1','home':str(home),'evidence':str(evidence),
        'configurationBeforeSha256':SHA(config),'gateway':{'sha256':'f'*64}}
    prior={'path':str(prior_path),'sha256':SHA(prior_path.read_bytes())}
    return home,evidence,prior_dir,prior_path,plan,prior,package,receipt


@unittest.skipUnless(os.name=='posix','POSIX-only private-mode qualification')
class PublicClientReuse(unittest.TestCase):
    def setUp(self):
        self._tmp=tempfile.TemporaryDirectory()
        self.root=Path(self._tmp.name);self.root.chmod(0o700)
        self.root=self.root.resolve(strict=True)
        self._path=list(sys.path)
        self._modules={name:sys.modules.get(name) for name in (SDK_NAME,PLUGIN_NAME)}
        for name in (SDK_NAME,PLUGIN_NAME):sys.modules.pop(name,None)

    def tearDown(self):
        for name,previous in self._modules.items():
            if previous is None:sys.modules.pop(name,None)
            else:sys.modules[name]=previous
        sys.path[:]=self._path
        self._tmp.cleanup()

    def test_foreign_existing_plugin_origin_still_refused(self):
        from types import SimpleNamespace
        home,evidence,prior_dir,prior_path,plan,prior,package,receipt=build_case(self.root)
        sys.modules[PLUGIN_NAME]=SimpleNamespace(__file__=str(self.root/'foreign-provider/__init__.py'))
        with self.assertRaises(entry.ClientHeld):entry._reuse_public_materialization(plan,package,prior)

    def test_success_is_read_only_and_honest(self):
        home,evidence,prior_dir,prior_path,plan,prior,package,receipt=build_case(self.root)
        before={prior_path:SHA(prior_path.read_bytes()),
            home/'config.yaml':SHA((home/'config.yaml').read_bytes()),
            home/'onoes-mind/sdk-4a7c3e3/onoes_mind/__init__.py':
                SHA((home/'onoes-mind/sdk-4a7c3e3/onoes_mind/__init__.py').read_bytes()),
            home/'plugins/onoes_mind/__init__.py':SHA((home/'plugins/onoes_mind/__init__.py').read_bytes()),
            home/'onoes-mind/cyony/review/shared-reader.json':
                (home/'onoes-mind/cyony/review/shared-reader.json').read_bytes()}
        self.assertFalse(any(evidence.iterdir()))
        meta=entry._reuse_public_materialization(plan,package,prior)
        self.assertTrue(meta['publicCodeReused'] is True and meta['codeNewlyInstalled'] is False)
        self.assertEqual(meta['priorMaterializationSha256'],prior['sha256'])
        self.assertEqual(meta['bootstrapPthSha256'],receipt['bootstrapPthSha256'])
        self.assertEqual(entry.digest(prior_path),prior['sha256'])
        for path,value in before.items():
            observed=path.read_bytes() if isinstance(value,bytes) else SHA(path.read_bytes())
            self.assertEqual(observed,value)
        self.assertFalse(any(evidence.iterdir()))
        self.assertFalse((home/'onoes-mind/cyony/intent.key').exists())

    def test_tampered_prior_receipt_or_hash_refused(self):
        home,evidence,prior_dir,prior_path,plan,prior,package,receipt=build_case(self.root)
        data=json.loads(prior_path.read_bytes());data['readerVersion']='1.25.0'
        prior_path.chmod(0o600);prior_path.write_bytes(json.dumps(data,sort_keys=True).encode())
        with self.assertRaises((entry.ClientHeld,FileNotFoundError)):
            entry._reuse_public_materialization(plan,package,prior)
        home,evidence,prior_dir,prior_path,plan,prior,package,receipt=build_case(self.root)
        prior['sha256']='0'*64
        with self.assertRaises(entry.ClientHeld):
            entry._reuse_public_materialization(plan,package,prior)

    def test_descriptor_and_receipt_flag_mismatches_refused(self):
        for overrides in ({'endpoint':'https://evil.ts.net/read'},{'manifestSha256':'1'*64},
                {'codeInstalled':False},{'nativeMcpChanged':True},{'readerVersion':'1.25.0'},
                {'bootstrapPthSha256':'2'*64}):
            home,evidence,prior_dir,prior_path,plan,prior,package,receipt=build_case(self.root,receipt_over=overrides)
            prior['sha256']=SHA(prior_path.read_bytes())
            with self.assertRaises(entry.ClientHeld,msg=str(overrides)):
                entry._reuse_public_materialization(plan,package,prior)

    def test_payload_and_extra_code_mismatch_refused(self):
        for missing in ('onoes-mind/sdk-4a7c3e3/onoes_mind/__init__.py',
                'plugins/onoes_mind/journal.py'):
            home,evidence,prior_dir,prior_path,plan,prior,package,receipt=build_case(self.root)
            package.files.pop(missing)
            with self.assertRaises((entry.ClientHeld,FileNotFoundError),msg=missing):
                entry._reuse_public_materialization(plan,package,prior)
        home,evidence,prior_dir,prior_path,plan,prior,package,receipt=build_case(self.root)
        sdk_init=home/'onoes-mind/sdk-4a7c3e3/onoes_mind/__init__.py'
        original=sdk_init.read_bytes();sdk_init.chmod(0o600);sdk_init.write_bytes(b'# substituted payload\n')
        with self.assertRaises(entry.ClientHeld):
            entry._reuse_public_materialization(plan,package,prior)
        for extra in ('onoes-mind/cyony/vendor/unexpected-code.py',
                'onoes-mind/sdk-4a7c3e3/onoes_mind/__pycache__/stale.pyc'):
            home,evidence,prior_dir,prior_path,plan,prior,package,receipt=build_case(self.root,unmanifested=extra)
            with self.assertRaises(entry.ClientHeld,msg=extra):
                entry._reuse_public_materialization(plan,package,prior)
        home,evidence,prior_dir,prior_path,plan,prior,package,receipt=build_case(self.root,empty_vendor=False)
        with self.assertRaises(entry.ClientHeld):
            entry._reuse_public_materialization(plan,package,prior)

    def test_partial_roots_refused(self):
        home,evidence,prior_dir,prior_path,plan,prior,package,receipt=build_case(self.root)
        shutil.rmtree(home/'onoes-mind/sdk-4a7c3e3')
        with self.assertRaises((entry.ClientHeld,FileNotFoundError)):
            entry._reuse_public_materialization(plan,package,prior)

    def test_custody_intents_and_client_key_refused(self):
        for records in (('home.json',),('session.json',)):
            home,evidence,prior_dir,prior_path,plan,prior,package,receipt=build_case(self.root,custody_records=records)
            with self.assertRaises((entry.ClientHeld,FileNotFoundError)):
                entry._reuse_public_materialization(plan,package,prior)
        home,evidence,prior_dir,prior_path,plan,prior,package,receipt=build_case(self.root)
        os.chmod(home/'onoes-mind/cyony'/'custody',0o755)
        with self.assertRaises(entry.ClientHeld):
            entry._reuse_public_materialization(plan,package,prior)
        home,evidence,prior_dir,prior_path,plan,prior,package,receipt=build_case(self.root,intents_records=('intent.json',))
        with self.assertRaises((entry.ClientHeld,FileNotFoundError)):
            entry._reuse_public_materialization(plan,package,prior)
        home,evidence,prior_dir,prior_path,plan,prior,package,receipt=build_case(self.root,client_intent_key=True)
        with self.assertRaises((entry.ClientHeld,FileNotFoundError)):
            entry._reuse_public_materialization(plan,package,prior)

    def test_changed_config_refused(self):
        home,evidence,prior_dir,prior_path,plan,prior,package,receipt=build_case(self.root)
        (home/'config.yaml').chmod(0o600);(home/'config.yaml').write_bytes(b'profiles: changed-sentinel\n')
        with self.assertRaises(entry.ClientHeld):
            entry._reuse_public_materialization(plan,package,prior)

    def test_bootstrap_extra_or_changed_pth_refused(self):
        home,evidence,prior_dir,prior_path,plan,prior,package,receipt=build_case(self.root,extra_pth=True)
        with self.assertRaises(entry.ClientHeld):
            entry._reuse_public_materialization(plan,package,prior)
        home,evidence,prior_dir,prior_path,plan,prior,package,receipt=build_case(self.root)
        site=home/'onoes-mind/cyony/reader-runtime'/f'lib/python{sys.version_info.major}.{sys.version_info.minor}'/'site-packages'
        pth=site/'onoes-reader-dependencies.pth';pth.chmod(0o600);pth.write_bytes(b'# tampered bootstrap\n')
        with self.assertRaises(entry.ClientHeld):
            entry._reuse_public_materialization(plan,package,prior)

    def test_wrong_executable_link_refused(self):
        home,evidence,prior_dir,prior_path,plan,prior,package,receipt=build_case(self.root,wrong_exec=True)
        with self.assertRaises(entry.ClientHeld):
            entry._reuse_public_materialization(plan,package,prior)

    def test_malformed_prior_and_same_or_outside_parent_refused(self):
        home,evidence,prior_dir,prior_path,plan,prior,package,receipt=build_case(self.root)
        for bad in (None,'not-a-dict',{'path':prior['path']},{'path':prior['path'],'sha256':'ZZ'},
                {'path':prior['path'],'sha256':'A'*64,'extra':1},
                {'path':str(home/'onoes-mind/cyony/custody'/'intent.key'),'sha256':'0'*64}):
            with self.assertRaises((entry.ClientHeld,FileNotFoundError),msg=repr(bad)):
                entry._reuse_public_materialization(plan,package,bad)
        with self.assertRaises(entry.ClientHeld):
            entry._reuse_public_materialization({**plan,'evidence':str(prior_dir)},package,prior)
        for bad_path in (str(evidence/'MATERIALIZED.json'),
                str(home/'onoes-cloud-window-prior-02'/'MATERIALIZED.json'),
                str(self.root/'onoes-cloud-window-outside'/'MATERIALIZED.json'),str(prior_path.parent)):
            moved={'path':bad_path,'sha256':prior['sha256']}
            with self.assertRaises((entry.ClientHeld,FileNotFoundError),msg=bad_path):
                entry._reuse_public_materialization(plan,package,moved)

    def test_run_checked_reuse_dispatch_is_read_only(self):
        home,evidence,prior_dir,prior_path,plan,prior,package,receipt=build_case(self.root)
        plan['priorPublicMaterialization']=prior
        calls={'held':0}
        class PackageApi:
            def materialize(self,pkg):raise AssertionError('fresh materialize must not run for explicit reuse')
        def held():
            calls['held']+=1
            self.assertFalse((evidence/'MATERIALIZED.json').exists())
            return True
        result=entry._run_checked('materialize','4'*64,(plan,None,held,PackageApi(),package,None))
        self.assertEqual(calls['held'],2)
        self.assertEqual(result,{'verified':True,'publicCodeOnly':True,'credentialsCreated':False,'configChanged':False})
        self.assertEqual({p.name for p in evidence.iterdir()},{'MATERIALIZE-ATTEMPT.json','MATERIALIZED.json'})
        saved=json.loads((evidence/'MATERIALIZED.json').read_bytes())
        self.assertTrue(saved['publicCodeReused'] is True and saved['codeNewlyInstalled'] is False)
        self.assertEqual(saved['priorMaterializationSha256'],prior['sha256'])
        self.assertEqual(SHA(prior_path.read_bytes()),prior['sha256'])
        self.assertFalse((home/'onoes-mind/cyony/intent.key').exists())

    def test_run_checked_invalid_prior_never_falls_back(self):
        class PackageApi:
            def materialize(self,pkg):raise AssertionError('fresh materialize must not run for an invalid explicit prior')
        for kind in ('none','text','missing-sha'):
            home,evidence,prior_dir,prior_path,plan,prior,package,receipt=build_case(self.root)
            bad=None if kind=='none' else 'not-a-dict' if kind=='text' else {'path':prior['path']}
            with self.assertRaises(entry.ClientHeld,msg=repr(bad)):
                entry._run_checked('materialize','5'*64,
                    ({**plan,'priorPublicMaterialization':bad},None,lambda:True,PackageApi(),package,None))
            self.assertEqual({p.name for p in evidence.iterdir()},{'MATERIALIZE-ATTEMPT.json'})
            self.assertFalse((evidence/'MATERIALIZED.json').exists())
            self.assertEqual(SHA(prior_path.read_bytes()),prior['sha256'])

    def test_run_checked_fresh_dispatch_uses_package_api(self):
        home,evidence,prior_dir,prior_path,plan,prior,package,receipt=build_case(self.root)
        fresh={**package.descriptor(),'codeInstalled':True,'readerVersion':'1.26.0',
            'bootstrapPthSha256':SHA(package.pth_raw),'nativeMcpChanged':False,
            'credentialsCreated':False,'configChanged':False}
        calls=[]
        class PackageApi:
            def materialize(self,pkg):calls.append(pkg);return dict(fresh)
        result=entry._run_checked('materialize','6'*64,(plan,None,lambda:True,PackageApi(),package,None))
        self.assertEqual(len(calls),1)
        self.assertEqual(json.loads((evidence/'MATERIALIZED.json').read_bytes()),fresh)
        self.assertEqual(result,{'verified':True,'publicCodeOnly':True,'credentialsCreated':False,'configChanged':False})


if __name__=='__main__':
    unittest.main(verbosity=2)
