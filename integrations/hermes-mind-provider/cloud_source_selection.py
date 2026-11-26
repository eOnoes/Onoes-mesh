"""Select two reviewed Windows seams and the existing recovery wrapper only.

Uses the original native configuration replacement primitive. The enclosing
installer owns actor retirement, disabled recovery-task admission and launcher
exclusion; hashes alone are not an exclusion mechanism. No task is changed.
"""
import hashlib
import json
import os
from pathlib import Path


class SelectionHeld(RuntimeError):
    pass


def require(ok):
    if not ok:
        raise SelectionHeld('Cloud source selection differs; preserve all original files and evidence')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, raw):
    with Path(path).open('xb') as stream:
        stream.write(raw);stream.flush();os.fsync(stream.fileno())
    require(Path(path).read_bytes()==raw)


def prepare(*, workspace, wrapper, replacements, original_startup, original_sha256,
            new_startup, new_sha256, expected_wrapper_sha256):
    workspace=Path(workspace);wrapper=Path(wrapper)
    require(workspace.is_absolute() and workspace.resolve(strict=True)==workspace
            and wrapper.is_absolute() and wrapper.resolve(strict=True)==wrapper
            and wrapper.name=='mesh-capture-first-hidden.vbs')
    targets={workspace/'integrations/mind-recovery-candidate'/name for name in (
        'project_service_process_candidate.py','native_project_sync_candidate.py')}
    require(type(replacements) is dict and set(map(Path,replacements))==targets)
    changes=[]
    for name,item in replacements.items():
        path=Path(name)
        require(path.resolve(strict=True)==path and type(item['after']) is bytes
                and sha(path.read_bytes())==item['beforeSha256']
                and sha(item['after'])==item['afterSha256'] and item['afterSha256']!=item['beforeSha256'])
        changes.append((path,path.read_bytes(),item['after']))
    before=wrapper.read_bytes();require(sha(before)==expected_wrapper_sha256)
    if before.startswith(b'\xff\xfe'):prefix,encoding=before[:2],'utf-16-le'
    elif before.startswith(b'\xfe\xff'):prefix,encoding=before[:2],'utf-16-be'
    else:prefix,encoding=b'','utf-8'
    text=before[len(prefix):].decode(encoding)
    old_path,new_path=str(Path(original_startup)),str(Path(new_startup))
    require(old_path!=new_path and original_sha256!=new_sha256
            and text.count(old_path)==text.count(original_sha256)==1
            and new_path not in text and new_sha256 not in text
            and all(type(v) is str and len(v)==64 and all(c in 'abcdef0123456789' for c in v)
                    for v in (original_sha256,new_sha256)))
    after=prefix+text.replace(old_path,new_path,1).replace(original_sha256,new_sha256,1).encode(encoding)
    changes.append((wrapper,before,after))
    return changes


def install(changes, *, evidence, atomic_replace, assert_quiescent):
    from onoes_mind.enrollment_store import qualify_private_storage
    evidence=qualify_private_storage(Path(evidence))
    require(len(changes)==3 and len({p for p,_,_ in changes})==3 and assert_quiescent() is True)
    for path,before,after in changes:
        require(path.resolve(strict=True)==path and path.read_bytes()==before
                and type(after) is bytes and before!=after)
    attempt={'schema':'onoes-cloud-source-selection/v1','items':[
        {'path':str(path),'beforeSha256':sha(before),'afterSha256':sha(after),'backup':'source-before-'+str(i)+'.bytes'}
        for i,(path,before,after) in enumerate(changes)]}
    save(evidence/'SOURCE-SELECTION-ATTEMPT.json',json.dumps(attempt,sort_keys=True).encode())
    # Every original is durable before the first replacement, including partial
    # failure paths. The existing primitive preserves Windows destination ACLs.
    for item,(_,before,_) in zip(attempt['items'],changes):save(evidence/item['backup'],before)
    for path,before,after in changes:atomic_replace(path,sha(before),after,assert_quiescent)
    result={'verified':True,'filesSelected':3,'existingTaskUnchanged':True,'beforeimagesRetained':True}
    save(evidence/'SOURCE-SELECTION-RESULT.json',json.dumps(result).encode())
    return result


def restore(*, evidence, atomic_replace, assert_quiescent):
    from onoes_mind.enrollment_store import qualify_private_storage
    evidence=qualify_private_storage(Path(evidence))
    require(assert_quiescent() is True)
    path=evidence/'SOURCE-SELECTION-ATTEMPT.json'
    if not path.exists():return {'verified':True,'selectionAttempted':False}
    attempt=json.loads(path.read_bytes())
    require(attempt['schema']=='onoes-cloud-source-selection/v1' and len(attempt['items'])==3)
    pending=[]
    for index,item in enumerate(attempt['items']):
        target=Path(item['path']);backup=evidence/item['backup']
        require(item['backup']=='source-before-'+str(index)+'.bytes'
                and target.resolve(strict=True)==target)
        current=sha(target.read_bytes())
        require(current in (item['beforeSha256'],item['afterSha256']))
        if current==item['beforeSha256']:continue
        require(backup.resolve(strict=True)==backup)
        before=backup.read_bytes();require(sha(before)==item['beforeSha256'])
        pending.append((target,current,before))
    # A foreign change in any file blocks all restoration, not just that file.
    require(assert_quiescent() is True)
    for target,current,before in pending:atomic_replace(target,current,before,assert_quiescent)
    result={'verified':True,'filesRestored':len(pending),'originalBytesVerified':True,'existingTaskUnchanged':True}
    save(evidence/'SOURCE-RESTORED.json',json.dumps(result).encode())
    return result
