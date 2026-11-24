"""Explicit source-pinned project owner process. Default CLI is preview only.

No approval, live path or automatic retry is supplied. Profile approval is a
trusted owner boundary, not isolation from hostile same-login/admin processes.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
SCHEMA = 'onoes-mind-project-operator/v1'
DECISION = 'approve_exact_mesh_project_lifecycle'
OPERATOR_MODE = 'enroll_operator'
OPERATOR_DECISION = 'approve_first_mind_operator_credential'
SCOPE = 'project/onoes-mind/shared'


class ProjectProcessError(RuntimeError):
    pass


class OperatorLaunchUnknown(ProjectProcessError):
    def __init__(self, child, stamp):
        super().__init__('Owned project operator launch is uncertain; retain its handle and do not retry.')
        self.child, self.creation_ticks = child, stamp


def require(ok):
    if not ok: raise ProjectProcessError('Private project operator refused; preserve state.')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result); result[key] = value
    return result


def source_paths(runtime):
    base = Path(runtime['mindSource'])
    require(base.is_absolute() and base.resolve() == base and (base/'onoes_mind/__init__.py').is_file())
    paths = {Path(__file__).resolve(), Path(runtime['python']).resolve(), Path(runtime['pwsh']).resolve()}
    paths.update(HERE/name for name in ('recall_process_candidate.py','native_recall_candidate.py',
        'provision_recall_candidate.py','checkpointed_ledger_candidate.py','checkpoint_candidate.py',
        'persistent_authority.py','project_events_candidate.py','project_events_http_candidate.py',
        'native_project_sync_candidate.py','provision_project_sync_candidate.py'))
    for pattern in ('*.py','*.mjs','*.ps1','migrations/*.sql'):
        paths.update((base/'onoes_mind').glob(pattern))
    return paths


def checked_profile(path, expected_sha, approval_path=None):
    require(os.name == 'nt')
    path = Path(path)
    with path.open('rb') as input_file: raw = input_file.read(65537)
    require(len(raw) <= 65536 and hashlib.sha256(raw).hexdigest() == expected_sha)
    p = json.loads(raw, object_pairs_hook=unique)
    keys = {'schema','ownerSid','runtime','sourceHashes','binding','projects','mode','operationId','reviewRef',
        'credentialPath','outcomePath','terminalPath','attemptPath','keyEnrollmentPath','authorityBindingPath','historyPath'}
    require(type(p) is dict)
    if p.get('mode') == 'add_project': keys.add('addedProjectId')
    require(set(p) == keys and p['schema'] == SCHEMA
            and p['mode'] in ('first_setup','replace','revoke','add_project',OPERATOR_MODE))
    enroll_owner = p['mode'] == OPERATOR_MODE
    runtime = p['runtime']
    require(type(runtime) is dict and set(runtime) == {'python','pwsh','mindSource'}
            and Path(runtime['python']).resolve() == Path(sys.executable).resolve())
    pins = p['sourceHashes']
    require(type(pins) is dict and {Path(n) for n in pins} == source_paths(runtime)
            and all(type(h) is str and re.fullmatch('[0-9a-f]{64}',h) and digest(n) == h for n,h in pins.items()))
    # No participant import until the full required dependency set is verified.
    sys.path.insert(0, str(HERE)); sys.path.insert(0, runtime['mindSource'])
    spec = importlib.util.find_spec('onoes_mind')
    require(spec is not None and Path(spec.origin).resolve() == Path(runtime['mindSource'])/'onoes_mind/__init__.py')
    from onoes_mind.enrollment_store import qualify_private_storage
    from onoes_mind.recall_binding import RecallBinding
    from checkpoint_candidate import read_plain
    from project_events_candidate import EventBinding, identifier, text
    qualify_private_storage(path, kind='file'); root = qualify_private_storage(path.parent)
    require(read_plain(path,65536) == raw)
    if enroll_owner:
        from onoes_mind import context_enrollment
        require(callable(getattr(context_enrollment, 'enroll_initial_operator', None))
                and callable(getattr(context_enrollment, 'WindowsOperatorCustody', None)))
        store = RecallBinding(**p['binding'])
        require(store.scope_id == SCOPE and store.review_ref == p['reviewRef']
                and Path(p['credentialPath']) == root / 'operator.dpapi')
        binding = EventBinding(store.database_path, store.file_device, store.file_inode,
                               store.store_id, store.environment, store.authority_ref)
    else:
        binding = EventBinding(**p['binding'])
    require(identifier(binding.store_id) and identifier(binding.environment) and text(binding.authority_ref,300))
    require(identifier(p['operationId']) and type(p['reviewRef']) is str and p['reviewRef'].strip() == p['reviewRef']
            and 1 <= len(p['reviewRef']) <= 300 and not re.search(r'[\x00-\x1f\x7f]',p['reviewRef']))
    require(type(p['projects']) is list and (not p['projects'] if enroll_owner else 1 <= len(p['projects']) <= 8)
            and all(type(v) is list and len(v)==2 and identifier(v[0]) and text(v[1],160)
                    and v[1] and v[1].strip()==v[1] for v in p['projects']))
    ids = [v[0] for v in p['projects']]; require(ids == sorted(set(ids)))
    if p['mode'] == 'add_project': require(len(ids) >= 2 and p['addedProjectId'] in ids)
    database = qualify_private_storage(Path(binding.database_path),kind='file')
    require(database.resolve() == database)
    stat = database.stat(); require((stat.st_dev,stat.st_ino) == (binding.file_device,binding.file_inode))
    require(not root.is_relative_to(database.parent) and not database.parent.is_relative_to(root))
    outputs = [p[n] for n in ('outcomePath','terminalPath','attemptPath')]
    if p['mode'] == 'revoke': require(p['credentialPath'] is None)
    else: outputs.append(p['credentialPath'])
    require(len(outputs) == len(set(outputs)))
    for name in outputs:
        target = Path(name); require(target.is_absolute() and target.parent == root and '..' not in target.parts)
    require(Path(p['keyEnrollmentPath']) == database.parent/'key-enrollment.json'
            and Path(p['authorityBindingPath']) == database.parent/'checkpoint-authority-binding.json'
            and Path(p['historyPath']) == Path(str(database)+'.deletions.jsonl'))
    sid = subprocess.run([runtime['pwsh'],'-NoLogo','-NoProfile','-NonInteractive','-Command',
        '[Security.Principal.WindowsIdentity]::GetCurrent().User.Value'],capture_output=True,text=True,
        timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
    require(sid.returncode == 0 and sid.stdout.strip() == p['ownerSid'])
    if approval_path is not None:
        qualify_private_storage(Path(approval_path),kind='file')
        a = json.loads(read_plain(Path(approval_path),65536),object_pairs_hook=unique)
        require(type(a) is dict and set(a) == {'decision','ownerSid','profiles','storeId','scopeId','projects','reviewRef','actions'}
            and a['decision'] == (OPERATOR_DECISION if enroll_owner else DECISION) and a['ownerSid'] == p['ownerSid']
            and type(a['profiles']) is list and len(a['profiles']) == len(set(a['profiles']))
            and all(type(h) is str and re.fullmatch('[0-9a-f]{64}',h) for h in a['profiles']) and expected_sha in a['profiles']
            and (not enroll_owner or a['profiles'] == [expected_sha])
            and a['storeId'] == binding.store_id and a['scopeId'] == SCOPE
            and a['projects'] == ids and a['reviewRef'] == p['reviewRef']
            and type(a['actions']) is list and len(a['actions']) == len(set(a['actions']))
            and (a['actions'] == [OPERATOR_MODE] if enroll_owner else
                all(x in ('first_setup','replace','revoke','add_project','run_service','run_mesh_sync') for x in a['actions'])
                and p['mode'] in a['actions']))
    return p, binding


def operator_role(p, binding, profile_sha):
    require(sys.stdin.readline().strip() == 'START')
    import recall_process_candidate as roles
    from onoes_mind.enrollment_store import qualify_private_storage
    qualify_private_storage(Path(p['attemptPath']),kind='file')
    attempt = roles.plain_json(p['attemptPath'])
    require(attempt.get('profileSha256') == profile_sha and attempt.get('pid') == os.getpid()
            and attempt.get('creationTicks') == roles.current_ticks() and attempt.get('state') == 'started')
    for name in ('keyEnrollmentPath','authorityBindingPath','historyPath'):
        qualify_private_storage(Path(p[name]),kind='file')
    from onoes_mind.runtime_keys import unprotect_runtime_keys
    from checkpointed_ledger_candidate import CheckpointedLedgerCandidate
    from persistent_authority import AuthorityBinding, PersistentAuthorityCandidate
    from project_events_candidate import ProjectEventsCandidate
    from provision_project_sync_candidate import prepare_project_service
    package = roles.plain_json(p['keyEnrollmentPath'],16384)
    require(set(package) == {'schema','storeId','environment','recovery_envelope','runtime_envelope'}
        and package['schema'] == 'onoes-mind-key-enrollment/v1'
        and package['storeId'] == binding.store_id and package['environment'] == binding.environment)
    keys = writer = lease = None
    try:
        if p['mode'] == OPERATOR_MODE:
            from native_project_sync_candidate import ProjectServiceLease
            lease = ProjectServiceLease(binding)
        keys = unprotect_runtime_keys(package['runtime_envelope'],store_id=binding.store_id,environment_id=binding.environment)
        authority = PersistentAuthorityCandidate(AuthorityBinding(**roles.plain_json(p['authorityBindingPath'])))
        writer = CheckpointedLedgerCandidate(binding.database_path,p['historyPath'],authority,
            store_id=binding.store_id,environment=binding.environment,**keys)
        if p['mode'] == OPERATOR_MODE:
            from onoes_mind.context_enrollment import WindowsOperatorCustody, enroll_initial_operator
            from onoes_mind.recall_binding import RecallBinding
            custody = WindowsOperatorCustody(Path(p['credentialPath']).parent, RecallBinding(**p['binding']))
            enrolled = enroll_initial_operator(writer, custody)
            require(enrolled == {'principal_id':'operator','store_id':binding.store_id})
            roles.private_new_json(p['outcomePath'], dict(status='operator_enrolled_inactive',
                operationId=p['operationId'],storeId=binding.store_id,environment=binding.environment,
                principal='operator',mode=OPERATOR_MODE,projects=[],serviceStarted=False,runtimeEnrollment=False,
                credentialIssued=True,credentialStorage={'fileSha256':digest(custody.path)}))
        else:
            prepare_project_service(ProjectEventsCandidate(writer,binding),mode=p['mode'],
                projects=tuple(tuple(v) for v in p['projects']),credential_path=p['credentialPath'],outcome_path=p['outcomePath'],
                operation_id=p['operationId'],review_ref=p['reviewRef'],added_project_id=p.get('addedProjectId'))
    finally:
        try:
            if writer is not None: writer.close()
        finally:
            if lease is not None: lease.close()
            keys = None


def launch_operator(profile_path, profile_sha, approval_path):
    require(approval_path is not None)
    p, binding = checked_profile(profile_path,profile_sha,approval_path)
    import recall_process_candidate as roles
    from native_project_sync_candidate import ProjectServiceLease
    lease = ProjectServiceLease(binding)
    child = stamp = None
    try:
        names = ['attemptPath','outcomePath','terminalPath'] + ([] if p['mode']=='revoke' else ['credentialPath'])
        for name in names: roles.new_role_file(p[name])
        record = dict(profileSha256=profile_sha,state='reserved')
        roles.private_new_json(p['attemptPath'],record)
        env = {k:v for k,v in os.environ.items() if k.upper() not in ('PYTHONPATH','PYTHONHOME','PYTHONSTARTUP')}
        child = subprocess.Popen([sys.executable,'-I',str(Path(__file__).resolve()),'--profile',str(profile_path),
            '--sha256',profile_sha,'--approval',str(approval_path),'--run'],env=env,cwd=HERE,
            stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        def save():
            with Path(p['attemptPath']).open('w',encoding='utf-8') as output:
                json.dump(record,output); output.flush(); os.fsync(output.fileno())
        record.update(pid=child.pid,creationTicks=None,state='identity_pending'); save()
        stamp = roles.creation_ticks(child._handle)
        record.update(creationTicks=stamp,state='started'); save()
        lease.close(); lease = None
        child.stdin.write(b'START\n'); child.stdin.flush()
        return child, stamp
    except Exception:
        if child is not None: raise OperatorLaunchUnknown(child,stamp) from None
        raise ProjectProcessError('Project operator was not confirmed started; preserve its attempt.') from None
    finally:
        if lease is not None: lease.close()
        if child is not None:
            try: child.stdin.close()
            except OSError: pass


def finish_operator(child, stamp, profile_path, profile_sha, approval_path):
    # The caller retains this handle through observation timeouts; no hidden wait,
    # kill, retry or terminal proof from a file/PID alone is allowed here.
    require(child.poll() == 0)
    p, binding = checked_profile(profile_path,profile_sha,approval_path)
    import recall_process_candidate as roles
    require(roles.creation_ticks(child._handle) == stamp)
    from onoes_mind.enrollment_store import qualify_private_storage
    for name in ('attemptPath','outcomePath'): qualify_private_storage(Path(p[name]),kind='file')
    attempt = roles.plain_json(p['attemptPath']); outcome = roles.plain_json(p['outcomePath'])
    require(attempt.get('profileSha256') == profile_sha and attempt.get('pid') == child.pid
            and attempt.get('creationTicks') == stamp and attempt.get('state') == 'started')
    expected = {'first_setup':'provisioned_inactive','replace':'replaced_inactive','revoke':'revoked_inactive',
                'add_project':'project_added_inactive',OPERATOR_MODE:'operator_enrolled_inactive'}[p['mode']]
    require(outcome.get('status') == expected and outcome.get('operationId') == p['operationId']
        and outcome.get('storeId') == binding.store_id and outcome.get('environment') == binding.environment
        and outcome.get('principal') == ('operator' if p['mode'] == OPERATOR_MODE else 'mesh-project-sync')
        and outcome.get('mode') == p['mode']
        and outcome.get('projects') == [v[0] for v in p['projects']]
        and outcome.get('addedProjectId') == p.get('addedProjectId')
        and outcome.get('serviceStarted') is False and outcome.get('runtimeEnrollment') is False
        and outcome.get('credentialIssued') is (p['mode'] != 'revoke'))
    credential_sha = None
    if p['mode'] != 'revoke':
        qualify_private_storage(Path(p['credentialPath']),kind='file')
        credential_sha = digest(p['credentialPath'])
        require(credential_sha == outcome['credentialStorage']['fileSha256'])
    receipt = dict(schema='onoes-mind-project-operator-terminal/v1',profileSha256=profile_sha,
        pid=child.pid,creationTicks=stamp,exitCode=0,operationId=p['operationId'],mode=p['mode'],
        storeId=binding.store_id,environment=binding.environment,outcomeSha256=digest(p['outcomePath']),
        credentialFileSha256=credential_sha)
    roles.private_new_json(p['terminalPath'],receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description='Private project owner process: preview only by default.')
    parser.add_argument('--profile',required=True); parser.add_argument('--sha256',required=True)
    parser.add_argument('--approval'); parser.add_argument('--run',action='store_true'); args = parser.parse_args()
    try:
        require(not args.run or args.approval is not None)
        p,binding = checked_profile(args.profile,args.sha256,args.approval if args.run else None)
        if not args.run:
            print(json.dumps(dict(status='preview',mode=p['mode'],createsNothing=True,needsOwnerApproval=True))); return 0
        operator_role(p,binding,args.sha256); return 0
    except Exception:
        print(json.dumps(dict(status='refused',preserveState=True,automaticRetry=False))); return 1


if __name__ == '__main__': sys.exit(main())
