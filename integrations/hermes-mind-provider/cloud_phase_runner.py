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
        require(authorization=={'schema':'onoes-cloud-install-authorization/v1','owner':'Eddie',
            'decision':'approve_cyony_private_home_and_mesh_reader','planSha256':plan_sha256}
            and re.fullmatch('[a-f0-9]{64}',plan_sha256))
        # The enclosing entry checks the raw master-plan SHA. This helper also
        # refuses a broader identity, scope or task regardless of child inputs.
        require(plan['schema']=='onoes-cloud-install-window/v1' and plan['agentId']=='cyony'
            and plan['readerPrincipal']=='context-cyony' and plan['sharedProject']=='onoes-mesh'
            and plan['modelCalls']==0 and plan['maintenanceTask']=='ONOes Mesh Workroom Recovery')
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
        return execute_once([str(python),'-I','-B',str(entry),phase,value['planPath'],
            value['planSha256'],value['authorizationPath']],evidence=self.evidence,label=label)

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
        require(result['profileSha256']==value['profileSha256'] and result['status']=='backup_complete_inactive'
            and result['archiveRehearsal']=='PASS' and result['archive']==body['encryptedBackup']
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
