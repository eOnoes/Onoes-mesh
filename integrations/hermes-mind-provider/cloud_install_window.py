"""One finite cloud enrollment window using the existing native adapters.

No daemon, scheduler, enrollment defaults, source selection or retry. The owner
entry supplies verified source-bound operations and the maintained admission
boundary. Windows operations use cold SDK processes and the existing launcher
window; gateway operations use the native scoped service manager.
"""
import json
import os
from pathlib import Path


class CloudWindowHeld(RuntimeError):pass


def failure_metadata(error):
    frames=[];cursor=error.__traceback__
    while cursor is not None:
        code=cursor.tb_frame.f_code
        frames.append({'file':Path(code.co_filename).name,'function':code.co_name,'line':cursor.tb_lineno})
        cursor=cursor.tb_next
    return {'errorType':type(error).__name__,'frames':frames[-12:]}


def write_once(path,value):
    with path.open('xb') as stream:
        stream.write((json.dumps(value,sort_keys=True,indent=2)+'\n').encode())
        stream.flush();os.fsync(stream.fileno())


def install_once(adapter,evidence,plan_sha256):
    """Enclose the already reviewed native operations; imported code is inactive.

    Preflight is read-only and must verify owner authorization, all source/profile
    pins, private evidence identity and maintenance ownership. A passing test or
    a pre-existing role approval is not authorization for this new enrollment.
    Existing attempt evidence prohibits another invocation, even after failure.
    """
    evidence=Path(evidence)
    if (not evidence.is_dir() or len(plan_sha256)!=64
            or any(c not in '0123456789abcdef' for c in plan_sha256)):
        raise ValueError('Exact reviewed plan and prepared private evidence directory required')
    if any(evidence.iterdir()):
        raise CloudWindowHeld('Earlier window evidence exists; reconcile without repeating work')
    try:confirmed=adapter.preflight(plan_sha256,evidence)
    except Exception:
        raise CloudWindowHeld('Reviewed preflight failed; no window started') from None
    if confirmed is not True:
        raise CloudWindowHeld('Reviewed scope was not confirmed; no window started')
    write_once(evidence/'WINDOW-ATTEMPT.json',{'planSha256':plan_sha256,'retry':False})

    def step(name,operation):
        write_once(evidence/(name+'-ATTEMPT.json'),{'planSha256':plan_sha256})
        try:
            result=operation()
            if type(result) is not dict or result.get('verified') is not True:
                raise CloudWindowHeld('Operation is unconfirmed; inspect authoritative state')
        except Exception as error:
            write_once(evidence/(name+'-FAILED.json'),failure_metadata(error))
            raise
        # The adapters retain their detailed native receipts separately. Do not
        # copy arbitrary operation results (which may contain private data).
        write_once(evidence/(name+'-RESULT.json'),{'complete':True,'verified':True})
        return result

    try:
        step('gateway-quiesce',adapter.quiesce_gateway)
        step('windows-retire',adapter.retire_windows)
        step('backup-before',adapter.backup_before)
        # Capture uses the frozen SDK's validators on the cloud host. Install
        # public code first; credentials and configuration remain absent/inactive.
        step('client-materialize',adapter.materialize_client)
        step('curated-capture',adapter.capture_curated)
        step('source-install',adapter.install_source)
        step('admit-cyony',adapter.admit_cyony)
        # The leased owner writer must be closed; new services are not started.
        step('backup-after',adapter.backup_after)
        step('windows-start',adapter.start_windows)
        step('client-delivery',adapter.deliver_client)
        step('configuration-select',adapter.select_configuration)
        # Exercise actual host/reader/client/MCP tools without starting a model
        # or admitting chat/cron work. Release is a separate, deliberate step.
        step('qualify-held',adapter.qualify_held)
        step('gateway-release',adapter.release_gateway)
        step('qualify-running',adapter.qualify_running)
    except Exception as error:
        write_once(evidence/'WINDOW-FAILED.json',{**failure_metadata(error),
            'automaticRetry':False,'canonicalRecordsRetained':True})
        try:
            # Actual actor/receipt reconciliation comes before revocation or
            # restoration. A timeout/missing result never proves retirement.
            step('rollback-hold',adapter.hold_for_rollback)
            step('rollback-revoke',adapter.revoke_new_access)
            step('rollback-configuration',adapter.restore_configuration)
            step('rollback-windows',adapter.restore_windows)
            step('rollback-qualify-held',adapter.qualify_original_held)
            step('rollback-gateway-release',adapter.release_original_gateway)
            step('rollback-qualify-running',adapter.qualify_original_running)
        except Exception as rollback_error:
            write_once(evidence/'ROLLBACK-HELD.json',{**failure_metadata(rollback_error),
                'automaticRetry':False,'preserveHandlesAndCustody':True})
            raise CloudWindowHeld('Rollback held for exact-state inspection; do not repeat the window') from None
        write_once(evidence/'RESTORED.json',{'originalSelectionVerified':True,
            'newAccessRevoked':True,'canonicalRecordsAndCustodyRetained':True})
        return {'installed':False,'restored':True,'modelCalls':0}
    write_once(evidence/'COMPLETE.json',{'newSelectionVerified':True,
        'beforeAfterBackupsVerified':True,'cyonyEnrollmentVerified':True,
        'realModelAcceptance':'NOT_RUN','automaticWorkers':False})
    return {'installed':True,'restored':False,'modelCalls':0}
