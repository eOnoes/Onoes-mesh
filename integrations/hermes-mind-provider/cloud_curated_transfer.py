"""Owner-only two-file curated transfer; no SSH, enrollment or database writes.

Capture runs on the source host only after approval. Stage runs in a separately
prepared private directory on the canonical host. The existing curated importer
owns validation, stable event identity, provenance and the canonical write.
"""
from dataclasses import dataclass,field
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
from types import MappingProxyType

from onoes_mind.agent_home import _content
from onoes_mind.curated_home_import import NAMES,prepare_curated_import
from onoes_mind.enrollment_store import qualify_private_storage
from onoes_mind.ledger import _secret_category


class TransferHold(ValueError):pass


def require(ok):
    if not ok:raise TransferHold('Curated source or private staging differs; preserve originals and inspect')


def sha(raw):return hashlib.sha256(raw).hexdigest()


def private(path,kind,*,source=False):
    path=Path(path);info=path.lstat()
    require(path.is_absolute() and path.resolve(strict=True)==path and not path.is_symlink()
        and (stat.S_ISDIR(info.st_mode) if kind=='directory' else stat.S_ISREG(info.st_mode)))
    if os.name=='nt':qualify_private_storage(path,kind=kind)
    else:
        # Native home directories may be traversable; saved files must still be
        # private. Never accept another user writing either source directory.
        forbidden=0o022 if source and kind=='directory' else 0o077
        require(info.st_uid==os.getuid() and info.st_mode&forbidden==0)
    if kind=='file':require(info.st_nlink==1)
    return info


def identity(info):return (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)


@dataclass(frozen=True)
class CuratedSnapshot:
    origin:str
    source_home:str
    files:object=field(repr=False)
    metadata:object=field(repr=False)

    def descriptor(self):
        return {'schema':'onoes-cloud-curated-snapshot/v1','origin':self.origin,
            'sourceHome':self.source_home,'sources':dict(self.metadata),'privateTextIncluded':False}


def capture(home,*,origin,expected_identities):
    """Read exactly the approved files; never scan chats or other agent homes."""
    require(origin=='srv1693050/cyony-hermes' and type(expected_identities) is dict
        and set(expected_identities)==set(NAMES))
    home=Path(home);roots=[private(p,'directory',source=True) for p in (home,home/'memories')]
    files={};metadata={}
    for name in NAMES:
        path=home/'memories'/name;before=private(path,'file')
        require(tuple(expected_identities[name])==identity(before))
        with path.open('rb') as stream:
            require(identity(os.fstat(stream.fileno()))==identity(before))
            raw=stream.read(8196)
            require(identity(os.fstat(stream.fileno()))==identity(before))
        require(len(raw)<=8195 and identity(private(path,'file'))==identity(before))
        text=raw.decode('utf-8-sig')
        if text.strip():_content(text)
        require(not _secret_category(text))
        files[name]=raw
        metadata[name]={'identity':identity(before),'sha256':sha(raw),'bytes':len(raw)}
    require([identity(private(p,'directory',source=True))[:2] for p in (home,home/'memories')]
        ==[identity(i)[:2] for i in roots])
    # Leave headroom for the canonical importer's source labels/provenance.
    require(sum(len(v) for v in files.values())<=7000)
    return CuratedSnapshot(origin,str(home),MappingProxyType(files),MappingProxyType(metadata))


def encode(snapshot):
    """Private transport bytes, never a log/diagnostic result."""
    return json.dumps({'descriptor':snapshot.descriptor(),
        'files':{n:base64.b64encode(v).decode('ascii') for n,v in snapshot.files.items()}},
        separators=(',',':'),allow_nan=False).encode()


def decode(raw,*,expected_sha256):
    require(type(raw) is bytes and len(raw)<=16000 and sha(raw)==expected_sha256)
    value=json.loads(raw);require(set(value)=={'descriptor','files'})
    d=value['descriptor'];require(d['schema']=='onoes-cloud-curated-snapshot/v1'
        and d['origin']=='srv1693050/cyony-hermes' and set(value['files'])==set(NAMES)
        and set(d['sources'])==set(NAMES) and d['privateTextIncluded'] is False)
    files={n:base64.b64decode(v,validate=True) for n,v in value['files'].items()}
    require(sum(map(len,files.values()))<=7000)
    for n,raw_file in files.items():
        require(sha(raw_file)==d['sources'][n]['sha256'] and len(raw_file)==d['sources'][n]['bytes'])
    return CuratedSnapshot(d['origin'],d['sourceHome'],MappingProxyType(files),MappingProxyType(d['sources']))


def stage(snapshot,destination,home_binding):
    """Exclusive local staging; return the supported importer's prepared object.

    Keep snapshot.descriptor() with the protected owner receipt to retain remote
    host/path/file identity as well as canonical original-name/hash provenance.
    A partial failure is retained; never overwrite or automatically clean it.
    """
    require(isinstance(snapshot,CuratedSnapshot) and home_binding.agent_id=='cyony')
    root=Path(destination);private(root,'directory')
    require({p.name for p in root.iterdir()}<={'memories'} and set(snapshot.files)==set(NAMES))
    folder=root/'memories'
    # Windows directories are provisioned privately by the reviewed owner
    # operation. Python's mkdir(0700) uses OWNER RIGHTS rather than the exact
    # explicit operator ACL required by Mind; never relax the validator.
    if not folder.exists():
        require(os.name!='nt');folder.mkdir(mode=0o700)
    private(folder,'directory');require(not any(folder.iterdir()))
    for name,raw in snapshot.files.items():
        require(sha(raw)==snapshot.metadata[name]['sha256'])
        fd=os.open(folder/name,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
        private(folder/name,'file')
    return prepare_curated_import(home_binding,hermes_home=root,
        expected_sha256={n:sha(v) for n,v in snapshot.files.items()})
