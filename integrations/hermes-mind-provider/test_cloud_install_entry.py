"""Cold-entry admission must fail before SDK import or any native action."""
import hashlib,importlib.util,json,os,subprocess,sys
from pathlib import Path
import pytest

PROVIDER=Path(os.environ['MESH_PROVIDER_SOURCE'])
NAMES=('cloud_install_entry.py','cloud_install_window.py','cloud_phase_runner.py',
    'cloud_windows_task.py','cloud_source_selection.py','private_mind_route.py')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def prepared(tmp_path):
    public=tmp_path/'public';public.mkdir()
    for name in NAMES:(public/name).write_bytes((PROVIDER/name).read_bytes())
    workspace=tmp_path/'copied-mesh';core=workspace/'integrations'
    native=core/'mind-recovery-candidate';native.mkdir(parents=True)
    for p in (native/'recall_process_candidate.py',core/'mesh_launcher_window.py',core/'native-atomic.py'):
        p.write_text('# Owned nonexecuting core source witness\n')
    sdk=tmp_path/'unimportable-sdk';package=sdk/'onoes_mind';package.mkdir(parents=True)
    witness=tmp_path/'SDK-WAS-IMPORTED'
    (package/'__init__.py').write_text('from pathlib import Path\nPath('+repr(str(witness))+').write_text("must not run")\n')
    plan={'schema':'onoes-cloud-install-window/v1','agentId':'cyony','readerPrincipal':'context-cyony',
        'sharedProject':'onoes-mesh','modelCalls':0,'maintenanceTask':'ONOes Mesh Workroom Recovery',
        'sdk':str(sdk),'workspace':str(workspace),'python':str(Path(sys.executable).resolve()),
        'pythonSha256':sha(Path(sys.executable).resolve()),'core':{
            'rolesPath':str(native/'recall_process_candidate.py'),'launcherModulePath':str(core/'mesh_launcher_window.py'),
            'atomicModulePath':str(core/'native-atomic.py')},
        'sourcePins':{str(p):sha(p) for p in [*public.glob('*.py'),package/'__init__.py',
            native/'recall_process_candidate.py',core/'mesh_launcher_window.py',core/'native-atomic.py']},
        'privateFixtureMarker':'do not echo this private fixture value'}
    return public,plan,witness


def refused(prepared,*,auth_decision='approve_cyony_private_home_and_mesh_reader',wrong_pin=False,duplicate=False):
    public,plan,witness=prepared;plan_path=public.parent/'private-owner-plan.json'
    raw=json.dumps(plan,sort_keys=True).encode()
    if duplicate:raw=raw[:-1]+b',"agentId":"deep"}'
    plan_path.write_bytes(raw);pin=hashlib.sha256(raw).hexdigest()
    auth=public.parent/'private-owner-authorization.json'
    auth.write_text(json.dumps({'schema':'onoes-cloud-install-authorization/v1','owner':'Eddie',
        'decision':auth_decision,'planSha256':pin}))
    result=subprocess.run([sys.executable,'-I','-B',str(public/'cloud_install_entry.py'),str(plan_path),
        '0'*64 if wrong_pin else pin,str(auth)],stdin=subprocess.DEVNULL,capture_output=True,
        timeout=10,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    assert result.returncode==1 and result.stdout==b''
    assert b'do not echo this private fixture value' not in result.stderr
    report=json.loads(result.stderr.decode().splitlines()[-1])
    assert report['messagesAndLocalsExcluded'] is True
    assert not witness.exists()  # A bad boundary cannot even import the SDK.


@pytest.mark.parametrize('field,value',[('agentId','deep'),('readerPrincipal','context-echo'),
    ('sharedProject','all-projects'),('modelCalls',1),('maintenanceTask','another task')])
def test_broader_or_different_window_never_imports_sdk(prepared,field,value):
    prepared[1][field]=value;refused(prepared)


def test_prior_deep_approval_cannot_authorize_cloud_window(prepared):
    refused(prepared,auth_decision='approve_deep_one_message')


def test_changed_master_bytes_refused_before_sdk_import(prepared):refused(prepared,wrong_pin=True)


def test_missing_required_helper_pin_refused_before_sdk_import(prepared):
    public,plan,_=prepared;del plan['sourcePins'][str(public/'cloud_phase_runner.py')]
    refused(prepared)


def test_changed_pinned_helper_refused_before_sdk_import(prepared):
    public,_,_=prepared
    with (public/'cloud_source_selection.py').open('ab') as stream:stream.write(b'\n# unexpected owned edit\n')
    refused(prepared)


def test_duplicate_master_key_refused_before_sdk_import(prepared):refused(prepared,duplicate=True)


def window_type():
    spec=importlib.util.spec_from_file_location('inactive_cloud_entry_guard_test',PROVIDER/'cloud_install_entry.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_uncertain_transport_blocks_before_any_compensating_action(tmp_path):
    module=window_type();window=module.CombinedWindow.__new__(module.CombinedWindow)
    transport=tmp_path/'transport';transport.mkdir();(transport/'send-TRANSPORT-UNKNOWN.json').write_text('{}')
    window.root={'transport':transport}
    def forbidden(*args):raise AssertionError('Must not issue a compensating command')
    window.gateway=forbidden
    with pytest.raises(module.InstallHeld):window.hold_for_rollback()


def test_partial_new_start_cannot_be_retired_without_its_result(tmp_path):
    module=window_type();window=module.CombinedWindow.__new__(module.CombinedWindow)
    transport=tmp_path/'transport';transport.mkdir();windows=tmp_path/'windows';windows.mkdir()
    (windows/'new-start-ATTEMPT.json').write_text('{}');window.root={'transport':transport,'windows':windows}
    calls=[]
    def held(*args):calls.append(args);return {'verified':True}
    class Task:
        def assert_paused(self):return True
    window.gateway=held;window.task=Task()
    def forbidden(*args):raise AssertionError('Cannot retire a partially identified writer')
    window.windows=forbidden
    with pytest.raises(module.InstallHeld):window.hold_for_rollback()
    assert calls==[('rehold','gateway-rollback-hold')]


def test_unrecorded_private_credential_cannot_be_treated_as_absent(tmp_path):
    module=window_type();window=module.CombinedWindow.__new__(module.CombinedWindow)
    owner=tmp_path/'owner';owner.mkdir();private=tmp_path/'private';private.mkdir();shared=tmp_path/'shared';shared.mkdir()
    (private/'agent-home.dpapi').write_bytes(b'owned unexpected fixture file')
    window.root={'owner':owner};window.owner_body={'privateCustody':str(private),'sharedCustody':str(shared)}
    with pytest.raises(module.InstallHeld):window.revoke_new_access()
    assert (private/'agent-home.dpapi').read_bytes()==b'owned unexpected fixture file'


def test_foreign_public_exposure_blocks_route_restoration_before_mutation(tmp_path):
    module=window_type();window=module.CombinedWindow.__new__(module.CombinedWindow)
    spec=importlib.util.spec_from_file_location('owned_route_guard_fixture',PROVIDER/'private_mind_route.py')
    routes=importlib.util.module_from_spec(spec);spec.loader.exec_module(routes)
    window.routes=routes;window.plan={'route':{'hostname':'fixture.example.ts.net'}}
    window.root={'private':tmp_path}
    window.route_status=lambda:{'AllowFunnel':{'fixture.example.ts.net:8453':True}}
    def forbidden(*args):raise AssertionError('Cannot mutate a route with changed exposure')
    window.route_command=forbidden
    with pytest.raises(module.InstallHeld):window.restore_windows()
