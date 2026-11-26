"""Owner-only private credential delivery primitive; no SSH, CLI or issuance.

The caller supplies newly approved credentials over the pinned SSH channel and
records a protected attempt before sending. An uncertain reply is inspected,
never resent blindly. No existing file is overwritten or removed.
"""
import json
import os
from pathlib import Path
import stat

from cloud_client_package import CLIENT,verify_package,encoded,sha,require
from onoes_mind.agent_home import _HOME_TOKEN
from onoes_mind.posix_home_state import PosixHomeCredential,_directory,_read_private
from onoes_mind.remote_project_tool import PosixContextCredential,CONTEXT_TOKEN


def provision(package,*,home_token,reader_token,intent_key):
    verify_package(package)
    require(os.name=='posix' and isinstance(home_token,str) and _HOME_TOKEN.fullmatch(home_token)
        and isinstance(reader_token,str) and CONTEXT_TOKEN.fullmatch(reader_token)
        and type(intent_key) is bytes and len(intent_key)==32)
    home=Path(package.home)
    # Verify the complete independently pinned public package before trusting
    # its profile paths. No configuration or permission is changed here.
    for name,raw in package.files.items():
        path=home/name;require(path.resolve(strict=True)==path)
        _,parent_id=_directory(path.parent)
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
        with os.fdopen(fd,'rb') as stream:
            before=os.fstat(stream.fileno())
            require(stat.S_ISREG(before.st_mode) and stat.S_IMODE(before.st_mode)==0o600
                and before.st_uid==os.geteuid() and before.st_nlink==1 and before.st_size==len(raw))
            actual=stream.read(len(raw)+1);after=os.fstat(stream.fileno())
        fingerprint=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
        require(_directory(path.parent)[1]==parent_id and actual==raw
            and fingerprint(before)==fingerprint(after)==fingerprint(path.lstat()))
    hp=json.loads(package.files[CLIENT+'/review/home-profile.json'])
    rp=json.loads(package.files[CLIENT+'/review/shared-reader.json'])
    require(hp['agent_id']=='cyony' and rp['principal_id']=='context-cyony'
        and rp['project_id']=='onoes-mesh')
    custody=home/CLIENT/'custody';_,custody_id=_directory(custody)
    intents=home/CLIENT/'intents';_directory(intents)
    require(not any(custody.iterdir()) and not any(intents.iterdir()))
    values={
        'home.json':encoded({'schema':'onoes-mind/posix-home-credential/v1','agent_id':'cyony',
            'binding_sha256':hp['home_binding_sha256'],'token':home_token}),
        'context.json':encoded({'schema':'onoes-mind/posix-context-credential/v1',
            'principal_id':'context-cyony','binding_sha256':rp['binding_sha256'],'token':reader_token}),
        'intent.key':intent_key}
    for name,raw in values.items():
        require(_directory(custody)[1]==custody_id)
        fd=os.open(custody/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    fd=os.open(custody,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
    require(PosixHomeCredential(custody/'home.json',agent_id='cyony',
        binding_sha256=hp['home_binding_sha256']).read()==home_token)
    require(PosixContextCredential(custody/'context.json',principal_id='context-cyony',
        binding_sha256=rp['binding_sha256']).read()==reader_token)
    require(_read_private(custody/'intent.key',32,custody_id)[0]==intent_key)
    return {'schema':'onoes-cloud-custody-delivery/v1','agentId':'cyony','readerPrincipal':'context-cyony',
        'packageManifestSha256':package.manifest_sha256,'files':{n:sha(v) for n,v in values.items()},
        'sdkReadbackVerified':True,'configChanged':False,'modelCalls':0,'credentialsPrinted':False}
