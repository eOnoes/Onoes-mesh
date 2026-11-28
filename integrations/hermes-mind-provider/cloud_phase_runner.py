"""Finite native child transports for the enclosing, approved cloud installer.

No scheduler, supervisor, model calls or retries. The master owner entry still
owns the actual window, task pause, source selection and rollback sequencing.
Private stdin/stdout is never copied into generic phase journals.
"""
import hashlib,json,os,re,shlex,subprocess
from pathlib import Path

# Existing pinned route verified from Eddie's PC after owner phone verification. A new owner plan
# cannot silently substitute another authentication or forwarding recipe.
APPROVED_SSH_SHA256='23db00dd522117cfed33720aec1ebd99288c0f9c07b2e5805a9c1a48350e5f98'


class PhaseTransportHeld(RuntimeError):pass


def require(ok):
    if not ok:raise PhaseTransportHeld('Exact native phase is unconfirmed; preserve original receipts')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path,value):
    with Path(path).open('xb') as stream:
        stream.write(json.dumps(value,sort_keys=True).encode());stream.flush();os.fsync(stream.fileno())


# Only the pinned cloud entry's own already-sanitized summary line may reach a
# generic journal. Nothing else in child stderr (prose, messages, locals, paths)
# is ever copied, stripped or reinterpreted.
FAILURE_METADATA_MAX_BYTES=65536
FAILURE_METADATA_MAX_LINE_CHARS=4096
FAILURE_METADATA_MAX_FRAMES=12
FAILURE_METADATA_KEYS=('errorType','frames','messagesAndLocalsExcluded')
FAILURE_METADATA_ERROR_TYPES=('GatewayHeld','EntryHeld','RuntimeError','ValueError','TypeError','OSError',
    'TimeoutExpired','FileNotFoundError','PermissionError','AssertionError',
    'OwnerHeld','ImportError','ModuleNotFoundError','ClientHeld')
FAILURE_METADATA_FRAME_KEYS=('file','function','line')
FAILURE_METADATA_FRAME_FILES=('cloud_gateway_entry.py','cloud_native_gateway.py','service_manager.py',
    'cloud_owner_entry.py','cloud_client_entry.py')
FAILURE_METADATA_FRAME_FUNCTIONS=('main','run_phase','_run_phase','quiesce_and_stop','release_and_start',
    'resume_stopped','assert_stopped','identity','_snapshot','_drained','_owned_marker','_fields','_sources',
    'require','stop','_run_svc','_write_gateway_desired_state')
# File-specific owner allowance only: the pinned owner entry's own top-level
# handler frames. These names never join the shared global gateway list and no
# other file may use them.
FAILURE_METADATA_OWNER_ENTRY_BASENAMES=('cloud_owner_entry.py',)
FAILURE_METADATA_OWNER_FRAME_FUNCTIONS=('<module>','run','approved_inputs','read','require','_same_archive_path')
# File-specific client allowance only: the pinned client entry's own top-level
# handler frames. These names never join the shared global gateway list and no
# other file may use them.
FAILURE_METADATA_CLIENT_ENTRY_BASENAMES=('cloud_client_entry.py',)
FAILURE_METADATA_CLIENT_FRAME_FUNCTIONS=('<module>','run','_run_checked','approved','installed',
    'private_read','read','save','load','_reuse_public_materialization','switch_plan','require')


def _reject_duplicate_keys(pairs):
    seen=set()
    for key,_ in pairs:
        if key in seen:raise ValueError('duplicate JSON object key')
        seen.add(key)
    return dict(pairs)


def _valid_failure_frame(frame):
    if type(frame) is not dict or set(frame)!=set(FAILURE_METADATA_FRAME_KEYS):return False
    if frame['file'] not in FAILURE_METADATA_FRAME_FILES:return False
    function=frame['function']
    # Owner frames are validated as a file-specific set BEFORE the existing
    # gateway logic, so no owner name ever widens the global gateway list.
    if frame['file'] in FAILURE_METADATA_OWNER_ENTRY_BASENAMES:
        if function not in FAILURE_METADATA_OWNER_FRAME_FUNCTIONS:return False
    elif frame['file'] in FAILURE_METADATA_CLIENT_ENTRY_BASENAMES:
        # Client frames are likewise a file-specific set BEFORE the gateway
        # fallback: client names never widen the global list and owner-only
        # names never validate on the client entry.
        if function not in FAILURE_METADATA_CLIENT_FRAME_FUNCTIONS:return False
    else:
        # The pinned entry's top-level handler frames its own module under <module>;
        # accept that name ONLY for the exact cloud_gateway_entry.py file, never elsewhere.
        if function=='<module>':
            if frame['file']!='cloud_gateway_entry.py':return False
        elif function not in FAILURE_METADATA_FRAME_FUNCTIONS:return False
    line=frame['line']
    return type(line) is int and 1<=line<=100000


def parse_failure_metadata(stderr):
    """Return only the pinned entry's trusted sanitized summary, else None.

    Exact bytes, bounded size, strict UTF-8, strict JSON with exact keys, a
    true privacy flag, an allow-listed error type and safe frames only. Any
    ambiguity (two or more valid lines) yields None. Raw stderr never escapes.
    """
    if type(stderr) is not bytes or len(stderr)>FAILURE_METADATA_MAX_BYTES:return None
    try:text=stderr.decode('utf-8')
    except UnicodeDecodeError:return None
    found=[]
    for line in text.splitlines():
        if len(line)>FAILURE_METADATA_MAX_LINE_CHARS:continue
        stripped=line.strip()
        if not stripped.startswith('{') or not stripped.endswith('}'):continue
        try:candidate=json.loads(stripped,object_pairs_hook=_reject_duplicate_keys)
        except (ValueError,RecursionError):continue
        if type(candidate) is not dict or set(candidate)!=set(FAILURE_METADATA_KEYS):continue
        if candidate['messagesAndLocalsExcluded'] is not True:continue
        if candidate['errorType'] not in FAILURE_METADATA_ERROR_TYPES:continue
        frames=candidate['frames']
        if type(frames) is not list or not 1<=len(frames)<=FAILURE_METADATA_MAX_FRAMES:continue
        if not all(_valid_failure_frame(f) for f in frames):continue
        found.append({'errorType':candidate['errorType'],
            'messagesAndLocalsExcluded':True,
            'frames':[dict(f) for f in frames]})
    if len(found)!=1:return None
    return found[0]


def execute_once(argv,*,evidence,label,stdin=None,private_stdout=False,timeout=180):
    """Run one bounded child; a lost transport is never proof a peer retired."""
    from onoes_mind.enrollment_store import qualify_private_storage
    require(type(argv) is list and all(type(a) is str and '\x00' not in a for a in argv)
        and re.fullmatch('[a-z][a-z0-9-]{0,79}',label)
        and (stdin is None or type(stdin) is bytes) and type(private_stdout) is bool
        and isinstance(timeout,(int,float)) and 0<timeout<=600)
    evidence=qualify_private_storage(Path(evidence))
    save(evidence/(label+'-TRANSPORT-ATTEMPT.json'),{'automaticRetry':False,'privateStdioExcluded':True})
    try:
        stream={'stdin':subprocess.DEVNULL} if stdin is None else {'input':stdin}
        result=subprocess.run(argv,**stream,capture_output=True,timeout=timeout,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except BaseException as error:
        save(evidence/(label+'-TRANSPORT-UNKNOWN.json'),{'errorType':type(error).__name__,
            'remoteActorRetirement':'NOT_PROVEN','automaticRetry':False,'privateStdioExcluded':True})
        raise PhaseTransportHeld('Native transport uncertain; reconcile existing actor and receipts, do not resend') from None
    # Child stderr may contain private data. Retain only its size/hash here;
    # authoritative native phase receipts, not arbitrary text, drive recovery.
    summary={'exitCode':result.returncode,'stdoutBytes':len(result.stdout),
        'stderrBytes':len(result.stderr),'stdoutSha256':hashlib.sha256(result.stdout).hexdigest(),
        'stderrSha256':hashlib.sha256(result.stderr).hexdigest(),'privateStdioExcluded':True}
    # Only the pinned entry's own trusted sanitized summary line may be journalled;
    # any other stderr text (prose, messages, locals, paths) stays unparsed and unsaved.
    if result.returncode!=0:
        metadata=parse_failure_metadata(result.stderr)
        if metadata is not None:summary['failureMetadata']=metadata
    save(evidence/(label+'-TRANSPORT-RESULT.json'),summary)
    require(result.returncode==0 and len(result.stdout)<=262144)
    if private_stdout:return result.stdout
    value=json.loads(result.stdout)
    require(type(value) is dict)
    return value


class NativePhases:
    """Concrete commands for existing entries; no callback or shell expansion."""
    WINDOWS=('inspect-old','retire-old','start-new','inspect-new','retire-new','restore-original','start-original')
    GATEWAY=('stop','verify-stopped','release','verify-running','rehold','verify-rollback-stopped',
        'release-original','verify-original-running')
    CLIENT=('materialize','capture','export-curated','deliver','select','restore','qualify-held','qualify-original-held')

    def __init__(self,plan,plan_sha256,authorization,evidence):
        # Mirror the master entry owner_authorization contract exactly. No legacyCasePolicy key
        # keeps the old strict v1 form; a present descriptor demands an explicit hash-bound v2.
        # A null/malformed descriptor never falls back to v1 and v2 is never forged into v1.
        # Construction performs no operation; the entry still owns full pinned case/attempt checks.
        try:
            require(type(plan) is dict and type(plan_sha256) is str
                and re.fullmatch('[a-f0-9]{64}',plan_sha256) and type(authorization) is dict)
            if 'legacyCasePolicy' not in plan:
                require(authorization=={'schema':'onoes-cloud-install-authorization/v1','owner':'Eddie',
                    'decision':'approve_cyony_private_home_and_mesh_reader','planSha256':plan_sha256})
            else:
                descriptor=plan['legacyCasePolicy']
                require(type(descriptor) is dict and set(descriptor)=={'path','sha256','originalAttempts'}
                    and type(descriptor['sha256']) is str and re.fullmatch('[a-f0-9]{64}',descriptor['sha256'])
                    and authorization=={'schema':'onoes-cloud-install-authorization/v2','owner':'Eddie',
                        'decision':'approve_cyony_private_home_and_mesh_reader_with_exact_legacy_case_policy',
                        'planSha256':plan_sha256,'legacyCaseSha256':descriptor['sha256']})
        except (AttributeError,TypeError,KeyError,IndexError):
            raise PhaseTransportHeld('Exact native phase is unconfirmed; preserve original receipts') from None
        # The enclosing entry checks the raw master-plan SHA. This helper also
        # refuses a broader identity, scope or task regardless of child inputs.
        require(plan.get('schema')=='onoes-cloud-install-window/v1' and plan.get('agentId')=='cyony'
            and plan.get('readerPrincipal')=='context-cyony' and plan.get('sharedProject')=='onoes-mesh'
            and plan.get('modelCalls')==0 and plan.get('maintenanceTask')=='ONOes Mesh Workroom Recovery')
        self.plan=plan;self.evidence=Path(evidence)

    def local(self,kind,phase,*,label):
        require(kind in ('windows','owner') and phase in (self.WINDOWS if kind=='windows' else ('admit','revoke')))
        value=self.plan[kind]
        expected='cloud_windows_entry.py' if kind=='windows' else 'cloud_owner_entry.py'
        entry=Path(value['entryPath']);python=Path(self.plan['python'])
        require(entry.name==expected and entry.is_absolute() and entry.resolve(strict=True)==entry
            and digest(entry)==value['entrySha256'] and digest(value['planPath'])==value['planSha256']
            and python.is_absolute() and python.resolve(strict=True)==python
            and digest(python)==self.plan['pythonSha256'])
        # The global transport ceiling stays 600. Windows mutating phases need
        # the full envelope for native role graceful-stop/readiness; every
        # other local phase keeps the default 180 explicitly.
        timeout=600 if kind=='windows' and phase in ('retire-old','retire-new','start-new','start-original') else 180
        return execute_once([str(python),'-I','-B',str(entry),phase,value['planPath'],
            value['planSha256'],value['authorizationPath']],evidence=self.evidence,label=label,timeout=timeout)

    def backup(self,which,*,label):
        from onoes_mind.enrollment_store import qualify_private_storage
        require(which in ('before','after'))
        value=self.plan['backups'][which];python=Path(self.plan['python']);entry=Path(value['entryPath'])
        require(entry.name=='project_backup_entry.py' and entry.is_absolute() and entry.resolve(strict=True)==entry
            and digest(entry)==value['entrySha256'] and digest(value['profilePath'])==value['profileSha256']
            and digest(value['approvalPath'])==value['approvalSha256']
            and python.is_absolute() and python.resolve(strict=True)==python
            and digest(python)==self.plan['pythonSha256'])
        profile=qualify_private_storage(Path(value['profilePath']),kind='file')
        qualify_private_storage(Path(value['approvalPath']),kind='file')
        body=json.loads(profile.read_bytes())
        require(body['archiveCredentialMode']=='windows-local' and body['resultPath']==value['resultPath']
            and not os.path.lexists(body['resultPath']) and not os.path.lexists(body['attemptPath']))
        # The existing native CLI intentionally prints prose. Execute its real
        # --run action, then qualify its own protected result rather than
        # interpreting a preview or the words "Backup COMPLETE" as evidence.
        execute_once([str(python),'-I','-B',str(entry),'--profile',value['profilePath'],
            '--sha',value['profileSha256'],'--approval',value['approvalPath'],'--run'],
            evidence=self.evidence,label=label,timeout=600,private_stdout=True)
        result_path=qualify_private_storage(Path(body['resultPath']),kind='file')
        result=json.loads(result_path.read_bytes())
        # Path identity only: exact str spellings compared as absolute pathlib Paths, so Windows
        # slash/case variants of the same location match. Never samefile/resolve: a hardlink,
        # symlink or relative alias to the same bytes stays a different archive.
        reported=Path(result['archive']) if type(result['archive']) is str else None
        approved=Path(body['encryptedBackup']) if type(body['encryptedBackup']) is str else None
        same=(reported is not None and approved is not None and reported.is_absolute()
            and approved.is_absolute() and '..' not in reported.parts and '..' not in approved.parts
            and reported==approved)
        require(result['profileSha256']==value['profileSha256'] and result['status']=='backup_complete_inactive'
            and result['archiveRehearsal']=='PASS' and same
            and digest(result['archive'])==result['archiveSha256'] and result['serviceStarted'] is False)
        return result

    def remote(self,kind,phase,*,label,stdin=None):
        require(kind in ('gateway','client') and phase in (self.GATEWAY if kind=='gateway' else self.CLIENT)
            and (stdin is None or (kind=='client' and phase=='deliver' and len(stdin)<=8192)))
        remote=self.plan['remote'];value=remote[kind];ssh=remote['sshArgv']
        require(type(ssh) is list and ssh[-1]=='root@100.106.29.72'
            and re.fullmatch('[a-f0-9]{64}',remote['containerId'])
            and remote['python']=='/opt/hermes/.venv/bin/python3')
        # Pin the exact previously approved SSH recipe; caller cannot replace
        # it with a password, forwarding, host-key bypass or another route.
        require(hashlib.sha256(json.dumps(ssh,separators=(',',':')).encode()).hexdigest()
            ==remote['sshArgvSha256']==APPROVED_SSH_SHA256)
        options={ssh[i+1] for i,a in enumerate(ssh[:-1]) if a=='-o'}
        require({'BatchMode=yes','StrictHostKeyChecking=yes','ForwardAgent=no','ForwardX11=no',
            'ClearAllForwardings=yes','PasswordAuthentication=no','KbdInteractiveAuthentication=no',
            'IdentityAgent=none','IdentitiesOnly=yes','PreferredAuthentications=publickey','UpdateHostKeys=no'}<=options
            and '-T' in ssh and '-i' in ssh and not any(a in ssh for a in ('-n','-L','-R','-D','-A','-X','-Y','-tt')))
        entry=value['entryPath'];expected='cloud_gateway_entry.py' if kind=='gateway' else 'cloud_client_entry.py'
        require(entry.startswith('/opt/data/') and Path(entry).name==expected
            and re.fullmatch('[a-f0-9]{64}',value['planSha256']))
        command=shlex.join(['docker','exec','--user','10000:10000','-i',remote['containerId'],remote['python'],
            '-I','-B',entry,phase,value['planPath'],value['planSha256'],value['authorizationPath']])
        return execute_once(ssh+[command],evidence=self.evidence,label=label,stdin=stdin,
            private_stdout=(kind=='client' and phase=='export-curated'))
