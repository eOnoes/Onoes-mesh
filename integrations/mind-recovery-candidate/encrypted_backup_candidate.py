"""Inactive trusted-operator 7z export/import. Never a memory/HTTP/MCP endpoint.

Plaintext stays in explicitly selected private NTFS storage or process memory.
Only a fully verified encrypted archive is copied to the destination. Recovery
still needs the independently current Mind authority; archive hashes are not it.
"""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

from onoes_mind.enrollment_store import qualify_private_storage
from checkpoint_candidate import SnapshotReceipt, context, read_plain

TOOL_SHA256='dd3757f31c97e33776f2590317d4fb12f2da075db3dbb1e3f94d0f2a01d84ffa'
SCHEMA='onoes-mind-encrypted-backup-candidate/v1'
MANIFEST='mind-backup-manifest.json'
LIMITS={'snapshot.sqlite':64*1024*1024,
        'snapshot.sqlite.meta':1024*1024,
        'encrypted-key-enrollment.json':16384,
        'snapshot-deletion-history.jsonl':16*1024*1024,MANIFEST:32768}


class EncryptedBackupError(RuntimeError):
    pass


def require(ok, message):
    if not ok:raise EncryptedBackupError(message)


def sha(data):return hashlib.sha256(data).hexdigest()


def unique(pairs):
    result={}
    for key,value in pairs:
        require(key not in result,'Duplicate backup metadata refused.')
        result[key]=value
    return result


def password_bytes(password):
    require(isinstance(password,str),'Local operator password required.')
    try:encoded=password.encode('utf-8')
    except UnicodeError:raise EncryptedBackupError('Invalid operator password.') from None
    require(16<=len(encoded)<=256 and not password.isspace()
            and not any(ord(c)<32 or ord(c)==127 for c in password),
            'Use a separately saved strong password without control characters.')
    return encoded+b'\n'+encoded+b'\n'


def run_tool(tool, arguments, password, *, cwd=None):
    selected=Path(tool)
    require(selected.is_absolute() and not selected.is_symlink()
            and not (selected.stat().st_file_attributes&0x400)
            and sha(read_plain(selected,16*1024*1024))==TOOL_SHA256,
            'Reviewed portable archive tool required.')
    # Bare -p requests a password when creating. Omit it when reading: bare -p
    # there means an empty password. All real password bytes use stdin only.
    try:
        result=subprocess.run([str(selected),arguments[0],'-sccUTF-8',*arguments[1:]],input=password_bytes(password),
            cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=120,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except (OSError,subprocess.SubprocessError):
        raise EncryptedBackupError('Archive operation failed; preserve attempted files.') from None
    require(result.returncode==0,'Archive operation refused; preserve attempted files.')
    return result.stdout


def check_publication(publication):
    require(type(publication) is SnapshotReceipt,'Reviewed snapshot publication required.')
    context(publication.store_id,publication.environment)
    require(type(publication.sequence) is int and publication.sequence>=0,
            'Invalid snapshot publication.')


def decode_bundle(archive, tool, password, expected_hash, publication):
    check_publication(publication)
    require(isinstance(expected_hash,str) and re.fullmatch('[0-9a-f]{64}',expected_hash),
            'Independently selected archive fingerprint required.')
    require(sha(read_plain(archive,128*1024*1024))==expected_hash,'Archive fingerprint mismatch.')
    listing=run_tool(tool,['l','-slt','--',str(archive)],password).decode('utf-8').replace('\r','')
    require('\n----------\n' in listing,'Archive entry inventory unavailable.')
    entries=[]
    for block in listing.split('\n----------\n',1)[1].strip().split('\n\n'):
        values=dict(line.split(' = ',1) for line in block.splitlines() if ' = ' in line)
        if values:entries.append(values)
    require(sorted(e.get('Path','') for e in entries)==sorted(LIMITS),
            'Unexpected, duplicate or missing archive entries.')
    for entry in entries:
        require(entry.get('Encrypted')=='+' and '7zAES' in entry.get('Method','')
                and not entry.get('Symbolic Link') and not entry.get('Hard Link')
                and int(entry.get('Size','-1')) in range(LIMITS[entry['Path']]+1),
                'Archive encryption/type/size check failed.')
    files={}
    for name in LIMITS:
        value=run_tool(tool,['x','-so','--',str(archive),name],password)
        require(len(value)<=LIMITS[name],'Archive payload exceeds bound.')
        files[name]=value
    manifest=json.loads(files[MANIFEST],object_pairs_hook=unique)
    require(set(manifest)=={'schema','publication','files'} and manifest['schema']==SCHEMA
            and manifest['publication']==asdict(publication)
            and manifest['files']=={name:sha(value) for name,value in files.items() if name!=MANIFEST},
            'Encrypted manifest/content/publication mismatch.')
    return files


def save_new(path, data):
    descriptor=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY|getattr(os,'O_BINARY',0),0o600)
    with os.fdopen(descriptor,'wb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())


def export_encrypted_backup_candidate(source_directory, staging_directory, destination, tool, password, *,
                                      publication, source_snapshot='first-empty-snapshot.sqlite'):
    check_publication(publication);password_bytes(password)
    source=qualify_private_storage(source_directory);stage=qualify_private_storage(staging_directory)
    require(not stage.is_relative_to(source) and not source.is_relative_to(stage) and not any(stage.iterdir()),
            'Separate empty private staging directory required.')
    target=Path(destination)
    require(target.is_absolute() and '..' not in target.parts and target.suffix.lower()=='.7z'
            and target.parent.is_dir() and target.parent.resolve()==target.parent,
            'Explicit canonical encrypted destination required.')
    require(not os.path.lexists(target),'Existing archive is preserved.')
    require(not target.is_relative_to(source) and not target.is_relative_to(stage),
            'Encrypted destination must be separate from private source/staging.')
    require(isinstance(source_snapshot,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.sqlite',source_snapshot),
            'Explicit snapshot basename required.')
    names={name:name for name in LIMITS if name!=MANIFEST}
    names.update({'snapshot.sqlite':source_snapshot,'snapshot.sqlite.meta':source_snapshot+'.meta'})
    files={}
    for name,limit in LIMITS.items():
        if name==MANIFEST:continue
        qualify_private_storage(source/names[name],kind='file')
        files[name]=read_plain(source/names[name],limit)
    require(sha(files['snapshot.sqlite'])==publication.database_sha256
            and sha(files['snapshot.sqlite.meta'])==publication.metadata_sha256,
            'Source snapshot differs from reviewed publication.')
    history=files['snapshot-deletion-history.jsonl'].splitlines(keepends=True)
    require(len(history)>publication.sequence
            and sha(b''.join(history[:publication.sequence+1]))==publication.history_prefix_sha256,
            'Snapshot history prefix mismatch.')
    package=json.loads(files['encrypted-key-enrollment.json'],object_pairs_hook=unique)
    require(set(package)=={'schema','storeId','environment','recovery_envelope','runtime_envelope'}
            and package['schema']=='onoes-mind-key-enrollment/v1'
            and package['storeId']==publication.store_id and package['environment']==publication.environment
            and all(isinstance(package[k],str) and package[k] for k in ('recovery_envelope','runtime_envelope')),
            'Encrypted key-package context mismatch.')
    manifest=dict(schema=SCHEMA,publication=asdict(publication),files={name:sha(value) for name,value in files.items()})
    files[MANIFEST]=(json.dumps(manifest,separators=(',',':'))+'\n').encode()
    for name,value in files.items():save_new(stage/name,value)
    private_archive=stage/'verified-backup.7z'
    run_tool(tool,['a','-t7z','-p','-mhe=on','-mx=1','-mmt=1','-bd','--',str(private_archive),*files],password,cwd=stage)
    encrypted=read_plain(private_archive,128*1024*1024);fingerprint=sha(encrypted)
    require(decode_bundle(private_archive,tool,password,fingerprint,publication)==files,
            'Encrypted readback differs from staged package.')
    for name in manifest['files']:
        require(sha(read_plain(source/names[name],LIMITS[name]))==manifest['files'][name],
                'Source changed during export; encrypted destination not published.')
    save_new(target,encrypted)
    require(sha(read_plain(target,128*1024*1024))==fingerprint,'Encrypted destination verification failed.')
    receipt=dict(schema=SCHEMA,archive=str(target),archiveSha256=fingerprint,
        publication=asdict(publication),files=manifest['files'],encryptedReadback='PASS',activated=False)
    save_new(stage/'archive-export-receipt.json',(json.dumps(receipt,indent=2)+'\n').encode())
    return receipt


def unpack_encrypted_backup_candidate(archive, destination_directory, tool, password, *, expected_archive_sha256, publication):
    target=qualify_private_storage(destination_directory)
    require(not any(target.iterdir()),'Existing recovery files are preserved.')
    files=decode_bundle(archive,tool,password,expected_archive_sha256,publication)
    # Decrypt and validate in RAM first. Never let the external tool extract paths.
    for name,value in files.items():
        save_new(target/name,value)
        qualify_private_storage(target/name,kind='file')
        require(sha(read_plain(target/name,LIMITS[name]))==sha(value),'Recovery output changed.')
    return dict(schema=SCHEMA,directory=str(target),files={name:sha(value) for name,value in files.items()},
                activated=False,currentAuthorityQualified=False)
