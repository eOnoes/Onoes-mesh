"""Inactive managed reader startup around an unchanged read-only enrollment.

The existing credential, terminal proof and reader frame remain authoritative.
This wrapper adds durable PID/birth attempts, a kernel lifetime lease and
generation-specific stop requests. It never provisions or rotates credentials.
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

HERE=Path(__file__).resolve().parent
SCHEMA='onoes-mind-reader-service/v1'


class ReaderServiceError(RuntimeError):pass


class ReaderLaunchUnknown(ReaderServiceError):
    def __init__(self,child,stamp):
        super().__init__('Reader launch is uncertain; preserve its original handle and attempt.')
        self.child,self.creation_ticks=child,stamp


def require(ok):
    if not ok:raise ReaderServiceError('Managed reader refused; preserve existing state.')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unique(pairs):
    result={}
    for key,value in pairs:require(key not in result);result[key]=value
    return result


def checked_profile(path,sha,approval):
    require(os.name=='nt' and approval is not None)
    path=Path(path)
    with path.open('rb') as source:raw=source.read(65537)
    require(len(raw)<=65536 and hashlib.sha256(raw).hexdigest()==sha)
    p=json.loads(raw,object_pairs_hook=unique)
    require(type(p) is dict and set(p)=={'schema','sourceHashes','readerProfilePath',
        'readerProfileSha256','attemptPath','stopPath'} and p['schema']==SCHEMA)
    pins=p['sourceHashes']
    require(type(pins) is dict and {Path(n) for n in pins}=={Path(__file__).resolve(),HERE/'recall_process_candidate.py'}
            and all(type(h) is str and re.fullmatch('[a-f0-9]{64}',h) and digest(n)==h for n,h in pins.items()))
    sys.path.insert(0,str(HERE))
    import recall_process_candidate as roles
    base,binding=roles.approved_profile(p['readerProfilePath'],p['readerProfileSha256'],approval)
    require(base['role']=='reader');roles.terminal_proof(base,binding)
    from onoes_mind.enrollment_store import qualify_private_storage
    qualify_private_storage(path,kind='file');root=qualify_private_storage(path.parent)
    require(path.read_bytes()==raw and Path(p['readerProfilePath']).parent==root)
    accepted=roles.plain_json(approval);require(sha in accepted['profiles'])
    occupied={base[n] for n in ('readyPath','stopPath','credentialPath','outcomePath','terminalPath')}
    occupied.update((str(path),p['readerProfilePath'],str(approval)))
    require(p['attemptPath']!=p['stopPath'])
    for name in ('attemptPath','stopPath'):
        target=Path(p[name]);require(target.is_absolute() and target.parent==root
            and '..' not in target.parts and str(target) not in occupied)
    return p,base,binding


class ReaderLease:
    def __init__(self,binding):
        identity='\0'.join((binding.database_path,binding.store_id,binding.scope_id))
        name='Local\\OnoesMindReader-'+hashlib.sha256(identity.encode()).hexdigest()[:24]
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        for name_,args,result in (
            ('CreateMutexW',[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR],wintypes.HANDLE),
            ('WaitForSingleObject',[wintypes.HANDLE,wintypes.DWORD],wintypes.DWORD),
            ('ReleaseMutex',[wintypes.HANDLE],wintypes.BOOL),('CloseHandle',[wintypes.HANDLE],wintypes.BOOL)):
            fn=getattr(self.kernel,name_);fn.argtypes=args;fn.restype=result
        self.handle=self.kernel.CreateMutexW(None,False,name);require(bool(self.handle))
        value=self.kernel.WaitForSingleObject(self.handle,0)
        if value not in (0,0x80):self.kernel.CloseHandle(self.handle);self.handle=None;require(False)
    def close(self):
        if self.handle:
            handle=self.handle;self.handle=None
            try:require(self.kernel.ReleaseMutex(handle))
            finally:self.kernel.CloseHandle(handle)


def stop_target(p,run_id):
    require(type(run_id) is str and re.fullmatch('[a-f0-9]{32}',run_id))
    path=Path(p['stopPath']);return path.with_name(path.name+'.'+run_id)


def _attempt(p,sha):
    import recall_process_candidate as roles
    from onoes_mind.enrollment_store import qualify_private_storage
    qualify_private_storage(Path(p['attemptPath']),kind='file');record=roles.plain_json(p['attemptPath'])
    require(record.get('schema')=='onoes-mind-reader-service-attempt/v1'
        and record.get('profileSha256')==sha and record.get('state')=='started')
    stop_target(p,record['runId'])
    require(type(record.get('pid')) is int and record['pid']>0
            and type(record.get('creationTicks')) is int and record['creationTicks']>0)
    return record


def _retire_previous(p,base,binding,sha,approval):
    import recall_process_candidate as roles
    from onoes_mind.enrollment_store import qualify_private_storage
    attempt=Path(p['attemptPath']);ready=Path(base['readyPath']);paths=[]
    if os.path.lexists(attempt):
        old=_attempt(p,sha);require(not roles.same_process_alive(old['pid'],old['creationTicks']))
        suffix='.retired-'+old['runId'];paths.append(attempt);stop=stop_target(p,old['runId'])
        if os.path.lexists(ready):
            qualify_private_storage(ready,kind='file');owner=roles.plain_json(ready)
            require(owner.get('managedBy')==sha and owner.get('runId')==old['runId']
                and owner.get('pid')==old['pid'] and owner.get('creationTicks')==old['creationTicks'])
        if os.path.lexists(stop):
            qualify_private_storage(stop,kind='file')
            require(roles.plain_json(stop)==dict(profileSha256=sha,runId=old['runId'],pid=old['pid'],creationTicks=old['creationTicks'],stop=True))
            paths.append(stop)
    elif os.path.lexists(ready):
        owner=roles.reader_state(p['readerProfilePath'],p['readerProfileSha256'],approval)
        require(not owner['processLive'] and 'managedBy' not in owner)
        suffix=f".retired-legacy-{owner['pid']}-{owner['creationTicks']}"
    else:
        require(not os.path.lexists(base['stopPath']));return
    if os.path.lexists(ready):
        qualify_private_storage(ready,kind='file');owner=roles.plain_json(ready)
        require(owner.get('schema')=='onoes-mind-reader-owner/v1'
            and owner.get('profileSha256')==p['readerProfileSha256']
            and owner.get('storeId')==binding.store_id and owner.get('scopeId')==binding.scope_id
            and owner.get('state') in ('starting','running','stopped','failed'))
        paths.append(ready)
    legacy_stop=Path(base['stopPath'])
    if os.path.lexists(legacy_stop):
        qualify_private_storage(legacy_stop,kind='file')
        require(roles.plain_json(legacy_stop)==dict(profileSha256=p['readerProfileSha256'],stop=True))
        paths.append(legacy_stop)
    moves=[];root=attempt.parent.resolve(strict=True)
    for source in paths:
        destination=source.with_name(source.name+suffix)
        require(source.resolve(strict=True).parent==root and not os.path.lexists(destination))
        moves.append((source,destination))
    # Retain the attempt until last so an interrupted archive cannot look unused.
    for source,destination in sorted(moves,key=lambda pair:pair[0]==attempt):os.rename(source,destination)


def launch_service(profile,sha,approval):
    p,base,binding=checked_profile(profile,sha,approval)
    import recall_process_candidate as roles
    lease=ReaderLease(binding);child=stamp=None
    try:
        _retire_previous(p,base,binding,sha,approval)
        run_id=uuid.uuid4().hex;roles.new_role_file(base['readyPath']);roles.new_role_file(stop_target(p,run_id))
        record=dict(schema='onoes-mind-reader-service-attempt/v1',profileSha256=sha,runId=run_id,state='reserved')
        roles.private_new_json(p['attemptPath'],record)
        env={k:v for k,v in os.environ.items() if k.upper() not in ('PYTHONPATH','PYTHONHOME','PYTHONSTARTUP')}
        child=subprocess.Popen([sys.executable,'-I',str(Path(__file__).resolve()),'--profile',str(profile),
            '--sha256',sha,'--approval',str(approval),'--run'],cwd=HERE,env=env,stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        def save():
            with Path(p['attemptPath']).open('w',encoding='utf-8') as output:
                json.dump(record,output);output.flush();os.fsync(output.fileno())
        record.update(pid=child.pid,creationTicks=None,state='identity_pending');save()
        stamp=roles.creation_ticks(child._handle);record.update(creationTicks=stamp,state='started');save()
        lease.close();lease=None
        child.stdin.write(b'START\n');child.stdin.flush();return child,stamp
    except Exception:
        if child is not None:raise ReaderLaunchUnknown(child,stamp) from None
        raise
    finally:
        if lease is not None:lease.close()
        if child is not None:
            try:child.stdin.close()
            except OSError:pass


def service_role(p,base,binding,sha):
    require(sys.stdin.readline().strip()=='START')
    import recall_process_candidate as roles
    from onoes_mind.enrollment_store import qualify_private_storage
    from native_recall_candidate import NativeRecallHost
    attempt=_attempt(p,sha)
    require(attempt['pid']==os.getpid() and attempt['creationTicks']==roles.current_ticks())
    lease=ReaderLease(binding)
    try:host=NativeRecallHost(binding=binding,credential_path=base['credentialPath'])
    except Exception:lease.close();raise
    stop=stop_target(p,attempt['runId'])
    record=dict(schema='onoes-mind-reader-owner/v1',profileSha256=p['readerProfileSha256'],
        managedBy=sha,runId=attempt['runId'],pid=os.getpid(),creationTicks=attempt['creationTicks'],
        state='starting',storeId=binding.store_id,scopeId=binding.scope_id)
    try:
        with Path(base['readyPath']).open('x',encoding='utf-8') as output:
            qualify_private_storage(Path(base['readyPath']),kind='file')
            def save():
                output.seek(0);json.dump(record,output,indent=2);output.write('\n');output.truncate();output.flush();os.fsync(output.fileno())
            save()
            try:
                state=host.start();require(state['running']);record.update(state='running',baseUrl=state['baseUrl'],readOnly=True);save()
                while True:
                    if os.path.lexists(stop):
                        qualify_private_storage(stop,kind='file')
                        require(roles.plain_json(stop)==dict(profileSha256=sha,runId=attempt['runId'],pid=os.getpid(),creationTicks=attempt['creationTicks'],stop=True));break
                    if os.path.lexists(base['stopPath']):
                        qualify_private_storage(Path(base['stopPath']),kind='file')
                        require(roles.plain_json(base['stopPath'])==dict(profileSha256=p['readerProfileSha256'],stop=True));break
                    require(host.status()['running']);time.sleep(.2)
                host.close();record['state']='stopped';save()
            except Exception:
                record['state']='failed';save();raise
    finally:
        try:host.close()
        finally:lease.close()


def service_state(profile,sha,approval):
    p,base,binding=checked_profile(profile,sha,approval)
    import recall_process_candidate as roles
    from onoes_mind.enrollment_store import qualify_private_storage
    attempt=_attempt(p,sha);ready=Path(base['readyPath'])
    live=roles.same_process_alive(attempt['pid'],attempt['creationTicks'])
    value=dict(state='starting',pid=attempt['pid'],creationTicks=attempt['creationTicks'],runId=attempt['runId'])
    if os.path.lexists(ready):
        qualify_private_storage(ready,kind='file')
        try:value=roles.plain_json(ready)
        except json.JSONDecodeError:return {**value,'processLive':live,'ready':False}
        require(value.get('schema')=='onoes-mind-reader-owner/v1' and value.get('managedBy')==sha
            and value.get('profileSha256')==p['readerProfileSha256'] and value.get('runId')==attempt['runId']
            and value.get('pid')==attempt['pid'] and value.get('creationTicks')==attempt['creationTicks']
            and value.get('storeId')==binding.store_id and value.get('scopeId')==binding.scope_id
            and value.get('state') in ('starting','running','stopped','failed'))
    return {**value,'processLive':live,'ready':live and value['state']=='running'}


def request_stop(profile,sha,approval):
    p,_,_=checked_profile(profile,sha,approval);state=service_state(profile,sha,approval)
    require(state['processLive'])
    import recall_process_candidate as roles
    roles.private_new_json(stop_target(p,state['runId']),dict(profileSha256=sha,runId=state['runId'],
        pid=state['pid'],creationTicks=state['creationTicks'],stop=True))


def main():
    parser=argparse.ArgumentParser()
    for name in ('profile','sha256','approval'):parser.add_argument('--'+name,required=True)
    parser.add_argument('--run',action='store_true');args=parser.parse_args()
    try:
        p,base,binding=checked_profile(args.profile,args.sha256,args.approval)
        if args.run:service_role(p,base,binding,args.sha256)
        else:print(json.dumps(dict(status='preview',createsNothing=True)))
        return 0
    except Exception:print(json.dumps(dict(status='reader_service_refused',preserveState=True)));return 1


if __name__=='__main__':raise SystemExit(main())
