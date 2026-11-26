"""Cold-process Windows cutover operations around unchanged native controllers.

No CLI, SDK import, service discovery or authorization default. The enclosing
owner entry verifies its source/approval and runs each SDK phase cold. Each
operation holds the existing launcher window and retains exact process handles.
"""
import hashlib
import json
import os
from pathlib import Path
import time


class CutoverHeld(RuntimeError):pass


def require(ok):
    if not ok:raise CutoverHeld('Exact native ownership or selection is unconfirmed; preserve evidence')


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record(evidence,name,value):
    with (Path(evidence)/(name+'.json')).open('xb') as stream:
        stream.write(json.dumps(value,sort_keys=True,allow_nan=False).encode())
        stream.flush();os.fsync(stream.fileno())


def selection(window,startup,roles,startup_path,startup_sha,evidence):
    window.assert_held();root=window.workspace
    require(Path(startup.__file__).resolve()==root/'integrations/mesh_startup_candidate.py'
        and Path(roles.__file__).resolve()==root/'integrations/mind-recovery-candidate/recall_process_candidate.py')
    from onoes_mind.enrollment_store import qualify_private_storage
    evidence=qualify_private_storage(Path(evidence))
    _,handoff,memory,recovery=startup.checked_startup(startup_path,startup_sha)
    selected=startup.profiles(handoff)
    require(startup.load_roles(selected['capture']) is roles)
    return handoff,selected,memory,recovery,evidence


def role_inputs(window,writer,reader,handoff,selected,memory):
    native=window.workspace/'integrations/mind-recovery-candidate'
    require(Path(writer.__file__).resolve()==native/'project_service_process_candidate.py'
        and Path(reader.__file__).resolve()==native/'reader_service_process_candidate.py')
    project=selected['connected']['projectSync']
    return {
        'writer':(writer,{'targetPath':project['serviceProfile'],'sha256':project['serviceProfileSha256']},
            {'targetPath':project['approvalPath']}),
        'reader':(reader,{'targetPath':memory['readerServiceProfile'],'sha256':memory['readerServiceSha256']},
            {'targetPath':handoff['connected']['approvalPath']})}


def retire_selection(*,window,startup,roles,writer,reader,control,retained,
                     startup_path,startup_sha,evidence,label,expected_owner_sha256):
    """Retire only the selected live owner and matching ready memory peers.

    The receipt and attempt beforeimages remain available for rollback. A
    partial/uncertain stop raises; it is not permission to select another SDK.
    """
    require(label in ('old','new') and type(retained) is list)
    handoff,selected,memory,recovery,evidence=selection(window,startup,roles,startup_path,startup_sha,evidence)
    owner=startup.owner_record(window,handoff,selected,roles)
    require(owner and owner['live'] and owner['mode']=='connected'
        and owner['receiptSha256']==expected_owner_sha256)
    receipt=window.workspace.parent/'workroom-ab-preview-process.json'
    archive=evidence/(label+'-owner.json')
    require(not archive.exists() and receipt.resolve(strict=True)==receipt
        and receipt.stat().st_dev==evidence.stat().st_dev and digest(receipt)==expected_owner_sha256)
    inputs=role_inputs(window,writer,reader,handoff,selected,memory)
    states={}
    for role,args in inputs.items():
        state=control.state(*args);peer=owner['record']['peers'][role]
        peer_pin=(selected['connected']['readerProfileSha256'] if role=='reader' else args[1]['sha256'])
        require(state and state['ready'] and state['processLive']
            and (state['pid'],state['creationTicks'])==(peer['pid'],peer['creationTicks'])
            and peer['profileSha256']==peer_pin)
        states[role]={k:state[k] for k in ('pid','creationTicks')}
    row=owner['record']
    record(evidence,label+'-retire-ATTEMPT',{'ownerSha256':expected_owner_sha256,
        'pid':row['pid'],'creationTicks':row['creationTicks'],'peers':states,'automaticRetry':False})
    actor=recovery.ProcessObservation(window,roles,row['pid'],row['creationTicks'],
        [selected['connected']['nodeExecutable'],str(window.workspace/'serve.mjs'),'--native-mind'],allow_terminate=True)
    retained.append(actor);actor.terminate();deadline=time.monotonic()+60
    while actor.poll() is None:
        require(time.monotonic()<deadline);time.sleep(.2)
    for mode in ('capture','connected'):
        startup.retire_mode(window,selected[mode],{**handoff[mode],'mode':mode},roles)
    require(digest(receipt)==expected_owner_sha256 and not archive.exists())
    os.rename(receipt,archive)
    require(digest(archive)==expected_owner_sha256 and not receipt.exists())
    for role,args in inputs.items():control.stop(*args,label+'-'+role+'-stop')
    result={'verified':True,'ownerSha256':expected_owner_sha256,
        'originalOwnerArchived':True,'memoryPeersRetired':states,'newSelectionStarted':False}
    record(evidence,label+'-retire-RESULT',result)
    return result


def restore_owner_beforeimage(*,window,startup,roles,startup_path,startup_sha,
                             evidence,expected_owner_sha256):
    """Restore the exact original public receipt, refusing a foreign active slot."""
    handoff,selected,_,_,evidence=selection(window,startup,roles,startup_path,startup_sha,evidence)
    receipt=window.workspace.parent/'workroom-ab-preview-process.json';archive=evidence/'old-owner.json'
    require(not os.path.lexists(receipt) and archive.resolve(strict=True)==archive
        and archive.stat().st_dev==receipt.parent.stat().st_dev and digest(archive)==expected_owner_sha256)
    proof=json.loads((evidence/'old-retire-ATTEMPT.json').read_bytes())
    require(proof['ownerSha256']==expected_owner_sha256
        and not roles.same_process_alive(proof['pid'],proof['creationTicks']))
    # Reuse native validation against the archived attempt before selection. The
    # native reader uses ROOT's public slot, so validate its recorded lineage
    # after the exact restore and before any process is started.
    record(evidence,'restore-owner-ATTEMPT',{'ownerSha256':expected_owner_sha256,'automaticRetry':False})
    os.rename(archive,receipt)
    require(digest(receipt)==expected_owner_sha256)
    owner=startup.owner_record(window,handoff,selected,roles)
    require(owner and owner['mode']=='connected' and not owner['live']
        and owner['receiptSha256']==expected_owner_sha256)
    result={'verified':True,'sameOriginalOwnerBeforeimage':True,'originalProcessRetired':True}
    record(evidence,'restore-owner-RESULT',result)
    return result


def start_selection(*,window,startup,roles,writer,reader,control,retained,
                    startup_path,startup_sha,evidence,label,expected_existing=None):
    """Explicit first activation, or exact old-peer restoration, before recovery."""
    require(label in ('old','new','restored') and type(retained) is list)
    handoff,selected,memory,_,evidence=selection(window,startup,roles,startup_path,startup_sha,evidence)
    inputs=role_inputs(window,writer,reader,handoff,selected,memory)
    states={role:control.state(*args) for role,args in inputs.items()}
    for role,state in states.items():
        if state and state['processLive']:
            require(expected_existing is not None and state['ready']
                and {k:state[k] for k in ('pid','creationTicks')}==expected_existing[role])
        else:require(state is None or state['state']=='stopped')
    record(evidence,label+'-start-ATTEMPT',{'startupSha256':startup_sha,'automaticRetry':False})
    for role,args in inputs.items():
        if not states[role] or not states[role]['processLive']:
            control.start(*args,label+'-'+role+'-start')
    try:
        result,held=startup.ensure_capture_first(window,approval_path=startup_path,approval_sha=startup_sha)
        retained.extend(held)
    except Exception as error:
        retained.append(error);retained.extend(getattr(error,'handles',[]));raise
    require(result.get('startupMode')=='connected' or result.get('state')=='observed_running')
    owner=startup.owner_record(window,handoff,selected,roles)
    require(owner and owner['live'] and owner['mode']=='connected')
    result={'verified':True,'pid':owner['record']['pid'],'creationTicks':owner['record']['creationTicks'],
        'ownerSha256':owner['receiptSha256'],'sameApprovedSelection':True}
    record(evidence,label+'-start-RESULT',result)
    return result
