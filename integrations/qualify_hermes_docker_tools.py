"""Exercise the installed Hermes file and terminal tools with one disposable workspace."""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from uuid import uuid4


IMAGE = 'sha256:4c69bc1980152b72d46d052e3b71329992acd598e3f9e931a7a11c478f273828'


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True, timeout=20,
                                   creationflags=subprocess.CREATE_NO_WINDOW).strip()


def check_container(container, allowed_mounts):
    observed, = json.loads(docker('inspect', '--type', 'container', container))
    host = observed['HostConfig']
    assert observed['Image'] == IMAGE
    assert host['NetworkMode'] == 'none' and not host['Privileged']
    assert ('no-new-privileges' in ' '.join(host['SecurityOpt'])) and 'ALL' in host['CapDrop']
    assert observed['Config']['User'] == '65534:65534'
    bindings = {}
    for value in host['Binds']:
        match = re.fullmatch(r'(.+):(/[^:]+)(:ro)?', value)
        assert match
        source, destination, readonly = match.groups()
        bindings[destination] = (Path(source).resolve(), not readonly)
    assert bindings == allowed_mounts and len(bindings) == len(host['Binds'])
    assert all(item['Type'] == 'bind' for item in observed['Mounts'])
    assert {item['Destination']:item['RW'] for item in observed['Mounts']} == {
        path:writable for path, (_, writable) in allowed_mounts.items()}


def observe(source, fixture):
    workspace = fixture/'work'
    marker = fixture/'owner'/'fixture-only.txt'
    profile = fixture/'profile'
    assert Path.cwd() == workspace and Path(os.environ['HERMES_HOME']) == profile
    sys.path.insert(0, str(source))
    from hermes_constants import get_hermes_home
    from tools import credential_files, file_tools, terminal_tool
    from tools.environments import docker as docker_backend
    from tools.terminal_scope import build_profile_terminal_scope, reset_terminal_scope, set_terminal_scope
    from tools.terminal_tool_lifecycle import cleanup_vm, get_active_env, ensure_task_env

    assert get_hermes_home().resolve() == profile
    assert docker('context', 'show') == 'desktop-linux'
    context, = json.loads(docker('context', 'inspect', 'desktop-linux'))
    assert context['Endpoints']['docker']['Host'] == 'npipe:////./pipe/dockerDesktopLinuxEngine'
    assert docker('image', 'inspect', IMAGE, '--format', '{{.Id}}') == IMAGE
    scope = build_profile_terminal_scope(profile)
    scope_token = set_terminal_scope(scope)
    container = None
    environment = None
    cleanup_finished = False
    task = 'default'
    try:
        selected = terminal_tool._get_env_config()
        assert selected['env_type'] == 'docker' and selected['docker_image'] == IMAGE
        assert not selected['docker_network'] and not selected['docker_orphan_reaper']
        assert not selected['docker_volumes'] and not selected['docker_forward_env'] and not selected['docker_env']
        assert not selected['container_persistent'] and not selected['docker_persist_across_processes']
        assert Path(selected['host_cwd']).resolve() == workspace
        assert not credential_files.get_credential_file_mounts(), 'Worker profile included a credential mount'
        allowed_mounts = {'/workspace': (workspace, True)}
        skills = credential_files.get_skills_directory_mount()
        caches = credential_files.get_cache_directory_mounts()
        for kind, mounts in [('skill', skills), ('cache', caches)]:
            for entry in mounts:
                folder = Path(entry['host_path']).resolve(strict=True)
                assert folder.is_relative_to(profile), f'{kind} mount was outside the disposable profile'
                assert next(folder.iterdir(), None) is None, f'{kind} mount was not empty'
                allowed_mounts[entry['container_path']] = (folder, False)
        environment = ensure_task_env(task)
        assert isinstance(environment, docker_backend.DockerEnvironment), 'Hermes did not start a Docker environment'
        container = environment._container_id
        check_container(container, allowed_mounts)

        working_input = json.loads(file_tools.read_file_tool('numbers.txt', task_id=task))
        assert '3 11' in working_input['content']
        blocked = json.loads(file_tools.read_file_tool(str(marker), task_id=task))
        assert marker.read_text() not in json.dumps(blocked) and blocked.get('error'), 'Host marker was readable'
        code = "from pathlib import Path\nPath('answer.txt').write_text(str(sum(map(int, Path('numbers.txt').read_text().split()))))\n"
        written = json.loads(file_tools.write_file_tool('/workspace/calculate.py', code, task_id=task))
        assert written.get('verified') is True, written
        assert (workspace/'calculate.py').is_file(), written
        assert (workspace/'calculate.py').read_text() == code
        executed = json.loads(terminal_tool.terminal_tool('python3 -I /workspace/calculate.py',
                              task_id=task, workdir='/workspace', timeout=15))
        assert executed.get('exit_code') == 0 and (workspace/'answer.txt').read_text() == '14'
        assert get_active_env(task) is environment
        check_container(container, allowed_mounts)
        hashes = {Path(module.__file__).resolve().relative_to(source).as_posix():sha256(Path(module.__file__).read_bytes()).hexdigest()
                  for module in (file_tools, terminal_tool, docker_backend)}
    finally:
        try:
            cleanup_vm(task, force_remove=True)
            if environment is not None:
                cleanup_finished = environment.wait_for_cleanup(timeout=15.0)
        finally:
            reset_terminal_scope(scope_token)
    assert cleanup_finished and not docker('ps', '-aq', '--no-trunc', '--filter', 'id='+container)
    print(json.dumps({'sourceHashes':hashes,'image':IMAGE,'readAllowedWorkspace':True,
                      'hostMarkerDenied':True,'writtenAndCheckedWork':True,'workspaceMounts':1,
                      'readOnlyEmptyCacheMounts':len(caches),'readOnlyEmptySkillMounts':len(skills),
                      'network':'none','containerRemoved':True,'modelRequests':0,'fixtureOnly':True}))


def launch_assignment(interpreter, source, fixture, work, env):
    sys.path.insert(0, str(source))
    from gateway.mesh_assignment_process import AssignmentProcessScope

    admission = uuid4().hex
    scope = AssignmentProcessScope(SimpleNamespace(profile_id='fixture', epoch='fixture'),
                                   SimpleNamespace(session_id=admission),
                                   dict(admission_id=admission, generation=1, principal_id='fixture-worker'))
    try:
        modules = [Path(sys.modules[item.__module__].__file__).resolve() for item in (type(scope), type(scope.fence))]
        assert all(path.parent == source/'gateway' for path in modules)
        args = [str(interpreter), '-IB', str(Path(__file__).resolve()), '--observe', str(source), str(fixture)]
        with scope.popen(args, cwd=str(work), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=True, encoding='utf-8', errors='replace') as child:
            try:
                stdout, stderr = child.communicate(timeout=160)
            except subprocess.TimeoutExpired:
                scope.dispose()
                raise
            if child.returncode:
                raise RuntimeError(stderr[-3800:])
        observed = scope.retire()
        deadline = time.monotonic() + 5
        while observed['state'] == 'held' and time.monotonic() < deadline:
            time.sleep(0.05)
            observed = scope.observe()
        assert observed['admissionId'] == admission and observed['sessionId'] == admission
        assert observed['assignmentLaunchSealed'] and observed['processTreeEnded'], observed['state']
        result = json.loads(stdout.splitlines()[-1])
        result['sourceHashes'].update({path.relative_to(source).as_posix():sha256(path.read_bytes()).hexdigest()
                                       for path in modules})
        result['assignmentProcessTreeEnded'] = True
        return result
    finally:
        scope.dispose()


def qualify(interpreter, source):
    # Keep the disposable task outside every project checkout so that discovery
    # cannot attach trusted project skills from the enclosing repository.
    with tempfile.TemporaryDirectory(prefix='hermes-docker-qualification-') as name:
        fixture = Path(name).resolve()
        work, owner, profile = (fixture/part for part in ('work', 'owner', 'profile'))
        for folder in (work, owner, profile):
            folder.mkdir()
        (work/'numbers.txt').write_text('3 11\n', encoding='utf-8')
        (owner/'fixture-only.txt').write_text(secrets.token_hex(24), encoding='ascii')
        config = {'terminal': {'backend':'docker', 'cwd':str(work),'docker_image':IMAGE,
                  'docker_mount_cwd_to_workspace':True,'docker_network':False,'docker_volumes':[],
                  'docker_forward_env':[],'docker_env':{},'docker_orphan_reaper':False,
                  'docker_persist_across_processes':False,'container_persistent':False,
                  'container_disk':0,'container_memory':256,'docker_shm_size':'64m',
                  'docker_extra_args':['--pull=never','--user=65534:65534'],'timeout':15}}
        (profile/'config.yaml').write_text(json.dumps(config),encoding='utf-8')
        keep = {'APPDATA','LOCALAPPDATA','USERPROFILE','SYSTEMROOT','WINDIR', 'TEMP','TMP',
                'PATH','COMSPEC','PATHEXT','PROGRAMDATA','PROCESSOR_ARCHITECTURE'}
        env = {key:value for key,value in os.environ.items() if key.upper() in keep}
        env.update(HERMES_HOME=str(profile), DOCKER_CONTEXT='desktop-linux', PYTHONIOENCODING='utf-8')
        assert shutil.which('docker')
        return launch_assignment(interpreter, source, fixture, work, env)


if __name__ == '__main__':
    if os.name != 'nt' or len(sys.argv) != 4:
        raise SystemExit('Usage on Windows: qualify_hermes_docker_tools.py HERMES_PYTHON HERMES_SOURCE PROOF_DIRECTORY')
    if sys.argv[1] == '--observe':
        observe(Path(sys.argv[2]).resolve(strict=True), Path(sys.argv[3]).resolve(strict=True))
    else:
        proof_dir = Path(sys.argv[3]).resolve(strict=True)
        result = qualify(Path(sys.argv[1]).resolve(strict=True), Path(sys.argv[2]).resolve(strict=True))
        with (proof_dir/'DOCKER-ASSIGNMENT-PROOF.json').open('x',encoding='utf-8') as output:
            json.dump(result,output,indent=2)
        print(json.dumps(result))
