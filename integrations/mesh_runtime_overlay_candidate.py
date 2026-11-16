"""Explicit finite Mesh code overlay. No process stop, startup or key access."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import tempfile


STARTUP_HELPERS=frozenset({
    'integrations/mesh_startup_candidate.py',
    'integrations/mesh_recovery_candidate.py',
    'integrations/mesh_native_recovery.py',
    'integrations/mesh_native_pair.py',
    'integrations/mesh_launcher_window.py',
})


def require(ok):
    if not ok: raise RuntimeError('Mesh code overlay refused; preserve existing state.')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None


def encoded(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')


def plan_hash(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def checked(value):
    require(os.name=='nt' and type(value) is dict and set(value)=={
        'schema','workspace','payloadRoot','journalRoot','toolSha256','observerSha256','runtime','files'})
    p=json.loads(encoded(value));require(p['schema']=='onoes-mesh-runtime-overlay/v2'
        and p['toolSha256']==digest(__file__) and p['observerSha256']==digest(observer_path()))
    roots=[Path(p[n]) for n in ('workspace','payloadRoot','journalRoot')]
    for root in roots:require(root.is_absolute() and root.resolve()==root)
    workspace,payload,journal=roots
    require(workspace.is_dir() and payload.is_dir() and journal.parent.is_dir()
        and not any(a.is_relative_to(b) or b.is_relative_to(a) for i,a in enumerate(roots) for b in roots[i+1:]))
    r=p['runtime'];require(type(r) is dict and set(r)=={
        'meshPid','meshCreationTicks','gatewayPort','serviceAttemptPath','serviceProfileSha256','freshLaunchAttempts'}
        and all(type(r[n]) is int and r[n]>0 for n in ('meshPid','meshCreationTicks','gatewayPort'))
        and 1024<=r['gatewayPort']<=65535 and type(r['serviceProfileSha256']) is str
        and re.fullmatch('[a-f0-9]{64}',r['serviceProfileSha256']))
    attempt=Path(r['serviceAttemptPath']);require(attempt.is_absolute() and attempt.resolve()==attempt
        and attempt.parent.is_dir() and attempt.name.endswith('-service-attempt.json')
        and not any(attempt.is_relative_to(root) for root in roots))
    fresh=r['freshLaunchAttempts'];require(type(fresh) is list and 1<=len(fresh)<=8)
    declared={attempt};mesh=False
    for entry in fresh:
        require(type(entry) is dict and set(entry)=={'kind','path','profileSha256'}
            and entry['kind'] in ('mesh','service') and type(entry['profileSha256']) is str
            and re.fullmatch('[a-f0-9]{64}',entry['profileSha256']))
        path=Path(entry['path']);require(path.is_absolute() and path.resolve()==path and path.parent.is_dir()
            and path.suffix=='.json' and path not in declared and not any(path.is_relative_to(root) for root in roots))
        declared.add(path);mesh=mesh or entry['kind']=='mesh'
    require(mesh)
    require(type(p['files']) is list and 1<=len(p['files'])<=256);seen=set()
    for f in p['files']:
        require(type(f) is dict and set(f)=={'relativePath','beforeSha256','afterSha256'})
        rel=f['relativePath'];require(type(rel) is str and '\\' not in rel)
        parts=PurePosixPath(rel).parts
        allowed=(rel in ('package.json','server.mjs','serve.mjs') or rel in STARTUP_HELPERS or
            len(parts)==2 and parts[0] in ('lib','public') and parts[1].endswith('.mjs') or
            len(parts)==2 and parts[0]=='integrations' and Path(parts[1]).suffix in ('.mjs','.ps1') or
            len(parts)==3 and parts[:2]==('integrations','mind-recovery-candidate') and parts[2].endswith('.py'))
        require(allowed and all(re.fullmatch('[A-Za-z0-9_.-]+',n) and n not in ('.','..') for n in parts)
            and rel not in seen and type(f['afterSha256']) is str and re.fullmatch('[a-f0-9]{64}',f['afterSha256'])
            and (f['beforeSha256'] is None or type(f['beforeSha256']) is str and re.fullmatch('[a-f0-9]{64}',f['beforeSha256'])))
        seen.add(rel)
        for base in (workspace,payload):
            path=base/rel;require(path.resolve()==path and path.parent.is_dir() and path.resolve().is_relative_to(base))
        require(digest(payload/rel)==f['afterSha256'] and (payload/rel).stat().st_size<=4*1024*1024)
    require(any(f['beforeSha256']!=f['afterSha256'] for f in p['files']))
    return p


def write_atomic(path,body):
    """Same-directory fsync/replace pattern used by native_bridge_maintenance."""
    fd,temp=tempfile.mkstemp(prefix='.mesh-overlay-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as out:out.write(body);out.flush();os.fsync(out.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)


def observer_path():
    return Path(__file__).resolve().parent/'mind-recovery-candidate/recall_process_candidate.py'


def roles(expected_sha=None):
    path=observer_path()
    if expected_sha is not None:require(digest(path)==expected_sha)
    spec=importlib.util.spec_from_file_location('mesh_overlay_observer',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def declared_attempt_stopped(p,observer,entry):
    path=Path(entry['path'])
    if not os.path.lexists(path):return
    require(path.is_file() and path.resolve()==path and path.stat().st_size<=8192)
    record=json.loads(path.read_bytes())
    mesh=entry['kind']=='mesh'
    require(record.get('schema') in (('onoes-mesh-native-child/v1','onoes-mesh-native-child/v2','onoes-mesh-native-child/v3') if mesh else ('onoes-mind-project-service-attempt/v1',))
        and record.get('profileSha256')==entry['profileSha256']
        and record.get('state')==('input_sent' if mesh else 'started')
        and type(record.get('pid')) is int and record['pid']>0
        and type(record.get('creationTicks')) is int and record['creationTicks']>0)
    if mesh and record.get('schema')=='onoes-mesh-native-child/v3':
        require(record.get('mode')=='capture_only' and 'peers' not in record)
    if mesh:
        require(record.get('entryPoint')==str(Path(p['workspace'])/'serve.mjs') and record.get('credentialsInRecord') is False)
    else:require(type(record.get('runId')) is str and re.fullmatch('[A-Za-z0-9:_-]{1,100}',record['runId']))
    require(not observer.same_process_alive(record['pid'],record['creationTicks']))


class stopped_window:
    def __init__(self,p):self.p=p;self.reservation=None;self.observer=None
    def assert_stopped(self):
        r=self.p['runtime'];observer=self.observer
        require(digest(observer_path())==self.p['observerSha256'])
        require(not observer.same_process_alive(r['meshPid'],r['meshCreationTicks']))
        entries=[dict(kind='service',path=r['serviceAttemptPath'],profileSha256=r['serviceProfileSha256']),*r['freshLaunchAttempts']]
        for entry in entries:declared_attempt_stopped(self.p,observer,entry)
    def __enter__(self):
        self.observer=roles(self.p['observerSha256']);self.assert_stopped()
        r=self.p['runtime'];reservation=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        try:
            reservation.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
            reservation.bind(('127.0.0.1',r['gatewayPort']))
            self.reservation=reservation;self.assert_stopped();return self
        except Exception:reservation.close();raise
    def __exit__(self,*_):self.reservation.close()


def originals(p):
    return all(digest(Path(p['workspace'])/f['relativePath'])==f['beforeSha256'] for f in p['files'])


def target_path(p,f):
    root=Path(p['workspace']);path=root/f['relativePath']
    require(root.resolve()==root and path.resolve()==path and path.parent.resolve()==path.parent
        and path.is_relative_to(root))
    return path


def read_journal(p):
    root=Path(p['journalRoot']);path=root/'journal.json'
    require(root.resolve()==root and path.resolve()==path and path.stat().st_size<=32768)
    j=json.loads(path.read_bytes());require(j.get('schema')=='onoes-mesh-runtime-overlay-journal/v1' and j.get('planSha256')==plan_hash(p)
        and j.get('state') in ('prepared','installing','installed','restored')
        and type(j.get('createdIdentities')) is dict and type(j.get('written')) is list)
    for f in p['files']:
        if f['beforeSha256'] is not None and f['beforeSha256']!=f['afterSha256']:
            before=root/'before'/f['relativePath'];require(before.resolve()==before and digest(before)==f['beforeSha256'])
    return j


def inspect_overlay(value):
    p=checked(value);root=Path(p['journalRoot'])
    if not os.path.lexists(root):
        require(originals(p));return dict(state='original',filesReady=True,runtimeChecked=False,createsNothing=True,planSha256=plan_hash(p))
    read_journal(p)
    actual=[digest(Path(p['workspace'])/f['relativePath']) for f in p['files']]
    require(all(a in (f['beforeSha256'],f['afterSha256']) for a,f in zip(actual,p['files'])))
    state='installed' if all(a==f['afterSha256'] for a,f in zip(actual,p['files'])) else 'original' if originals(p) else 'partial'
    return dict(state=state,planSha256=plan_hash(p),createsNothing=True)


def apply_overlay(value,approval):
    p=checked(value);require(approval==dict(decision='approve_exact_mesh_runtime_overlay',planSha256=plan_hash(p)))
    root=Path(p['journalRoot']);require(not os.path.lexists(root) and originals(p))
    with stopped_window(p) as window:
        require(originals(p));root.mkdir();(root/'before').mkdir()
        j=dict(schema='onoes-mesh-runtime-overlay-journal/v1',planSha256=plan_hash(p),state='prepared',written=[],createdIdentities={})
        for f in p['files']:
            if f['beforeSha256'] is not None and f['beforeSha256']!=f['afterSha256']:
                before=root/'before'/f['relativePath'];before.parent.mkdir(parents=True,exist_ok=True)
                body=target_path(p,f).read_bytes();require(hashlib.sha256(body).hexdigest()==f['beforeSha256'])
                with before.open('xb') as out:out.write(body);out.flush();os.fsync(out.fileno())
                require(digest(before)==f['beforeSha256'])
        write_atomic(root/'journal.json',encoded(j))
        try:
            for f in p['files']:
                if f['beforeSha256']==f['afterSha256']:continue
                window.assert_stopped()
                path=target_path(p,f);require(digest(path)==f['beforeSha256'])
                body=(Path(p['payloadRoot'])/f['relativePath']).read_bytes();require(hashlib.sha256(body).hexdigest()==f['afterSha256'])
                j.update(state='installing',intent=f['relativePath']);write_atomic(root/'journal.json',encoded(j))
                if f['beforeSha256'] is None:
                    fd,temp=tempfile.mkstemp(prefix='.mesh-overlay-',dir=path.parent)
                    try:
                        with os.fdopen(fd,'wb') as out:out.write(body);out.flush();os.fsync(out.fileno())
                        stat=Path(temp).stat();j['createdIdentities'][f['relativePath']]=[stat.st_dev,stat.st_ino]
                        write_atomic(root/'journal.json',encoded(j));target_path(p,f);require(not os.path.lexists(path))
                        os.rename(temp,path)  # Windows refuses an existing destination.
                    finally:
                        if os.path.exists(temp):os.unlink(temp)
                else:
                    target_path(p,f);require(digest(path)==f['beforeSha256']);write_atomic(path,body)
                require(digest(path)==f['afterSha256']);j['written'].append(f['relativePath']);write_atomic(root/'journal.json',encoded(j))
            window.assert_stopped()
            j.update(state='installed',intent=None);write_atomic(root/'journal.json',encoded(j))
        except Exception:
            raise RuntimeError('Mesh code overlay outcome uncertain; inspect the same journal and do not retry.') from None
    require(inspect_overlay(p)['state']=='installed');return dict(state='installed',planSha256=plan_hash(p),processesStarted=False)


def rollback_overlay(value,approval):
    p=checked(value);require(approval==dict(decision='approve_exact_mesh_runtime_rollback',planSha256=plan_hash(p)))
    j=read_journal(p);require(inspect_overlay(p)['state'] in ('original','installed','partial'))
    # Validate every removal before beginning any rollback writes.
    for f in p['files']:
        path=target_path(p,f)
        if f['beforeSha256'] is None and path.exists():
            stat=path.stat();require(j['createdIdentities'].get(f['relativePath'])==[stat.st_dev,stat.st_ino])
    with stopped_window(p) as window:
        for f in reversed(p['files']):
            window.assert_stopped()
            path=target_path(p,f);current=digest(path)
            require(current in (f['beforeSha256'],f['afterSha256']))
            if current==f['beforeSha256']:continue
            if f['beforeSha256'] is None:
                stat=path.stat();require(j['createdIdentities'].get(f['relativePath'])==[stat.st_dev,stat.st_ino]
                    and path.resolve()==path and path.is_relative_to(Path(p['workspace'])))
                path.unlink()  # Only this installer-created, unchanged file.
            else:
                before=Path(p['journalRoot'])/'before'/f['relativePath'];require(before.resolve()==before)
                body=before.read_bytes();require(hashlib.sha256(body).hexdigest()==f['beforeSha256']);write_atomic(path,body)
        window.assert_stopped()
        require(originals(p));j.update(state='restored',intent=None);write_atomic(Path(p['journalRoot'])/'journal.json',encoded(j))
    return dict(state='original',planSha256=plan_hash(p),processesStarted=False)
