"""Finite owner-only Cyony enrollment using supported Mind APIs.

No CLI, listener, key loading, file writes or automatic retries. The caller owns
approval, encrypted backups, the canonical writer lease and exclusive custody.
Each committed enrollment needs its durable receipt before the next begins.
"""
from dataclasses import asdict
import hashlib
import json
import re

from onoes_mind.agent_home import AgentHomeBinding,enroll_agent_home
from onoes_mind.agent_context import AgentContextBinding
from onoes_mind.context_enrollment import _check_store,enroll_context_reader


class EnrollmentHold(ValueError):pass


def require(ok):
    if not ok:raise EnrollmentHold('Cloud enrollment evidence changed; preserve custody and inspect, do not retry')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def bindings(home,reader):
    require(isinstance(home,AgentHomeBinding) and isinstance(reader,AgentContextBinding)
        and home.agent_id=='cyony' and reader.principal_id=='context-cyony'
        and reader.project_id=='onoes-mesh' and home.store==reader.store
        and reader.store.scope_id=='project/onoes-mind/shared')
    return digest({'home':asdict(home),'reader':asdict(reader)})


def state(ledger,principal):
    """Hash credential verifiers, never return them or a credential value."""
    rows={}
    for table,columns,order in (
        ('principals','principal_id,kind,credential_epoch','principal_id'),
        ('credentials','credential_id,salt,verifier,epoch,issued_at,revoked_at','credential_id'),
        ('recall_service_credentials','salt,verifier,epoch','principal_id'),
        ('scope_grants','scope_id,can_read,can_write','scope_id')):
        rows[table]=[tuple(r) for r in ledger.db.execute(
            f'SELECT {columns} FROM {table} WHERE principal_id=? ORDER BY {order}',(principal,))]
    require(len(rows['principals'])==1)
    return {'principal':principal,'epoch':rows['principals'][0][2],'stateSha256':digest(rows)}


def enroll(ledger,home,reader,*,operator_token,attempt_id,review_sha256,
           save_home_token,save_reader_token,persist_receipt):
    """Separate SDK commits; an uncertain save/receipt deliberately stops progress.

    The first absence check and each subsequent SDK check run under the caller's
    existing exclusive writer lease. A failed second step leaves the first
    principal and its recorded receipt for scoped recovery, never blind reissue.
    """
    pin=bindings(home,reader)
    require(type(attempt_id) is str and re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,95}',attempt_id)
        and type(review_sha256) is str and re.fullmatch('[0-9a-f]{64}',review_sha256)
        and all(callable(f) for f in (save_home_token,save_reader_token,persist_receipt)))
    _check_store(ledger,home.store)
    require(ledger.authenticate(operator_token)=='operator')
    require(not ledger.db.execute('SELECT 1 FROM principals WHERE principal_id IN (?,?)',
        (home.agent_id,reader.principal_id)).fetchone())
    receipts=[]
    for principal,invoke in (
        (home.agent_id,lambda:enroll_agent_home(ledger,home,operator_token=operator_token,save_new_token=save_home_token)),
        (reader.principal_id,lambda:enroll_context_reader(ledger,reader,operator_token=operator_token,save_new_token=save_reader_token))):
        invoke()
        receipt={'schema':'onoes-new-cloud-enrollment/v1','attemptId':attempt_id,
            'reviewSha256':review_sha256,'bindingSha256':pin,'storeId':home.store.store_id,
            **state(ledger,principal)}
        # False or exception means no next step. Even if persistence succeeded
        # before a lost acknowledgement, do not re-enroll or erase the evidence.
        require(persist_receipt(receipt) is True)
        receipts.append(receipt)
    return tuple(receipts)


def revoke_new(ledger,home,reader,*,operator_token,attempt_id,review_sha256,receipts):
    """Rotate only unchanged, newly-enrolled identities named by trusted receipts.

    Receipts must be loaded from the approved owner's protected attempt record,
    never supplied by a chat request. Changed credentials, grants or epochs hold
    recovery. No principals, memory, custody files or history are deleted.
    """
    pin=bindings(home,reader)
    require(type(receipts) in (tuple,list) and 1<=len(receipts)<=2)
    principals=[r.get('principal') for r in receipts]
    require(len(set(principals))==len(principals) and principals[0]=='cyony'
        and (len(principals)==1 or principals[1]=='context-cyony'))
    with ledger._transaction(immediate=True):
        _check_store(ledger,home.store)
        require(ledger.authenticate(operator_token)=='operator')
        for receipt in receipts:
            require(set(receipt)=={'schema','attemptId','reviewSha256','bindingSha256','storeId','principal','epoch','stateSha256'}
                and receipt['schema']=='onoes-new-cloud-enrollment/v1'
                and receipt['attemptId']==attempt_id and receipt['reviewSha256']==review_sha256
                and receipt['bindingSha256']==pin and receipt['storeId']==home.store.store_id
                and receipt['epoch']==1)
            require(state(ledger,receipt['principal'])=={k:receipt[k] for k in ('principal','epoch','stateSha256')})
        for principal in principals:ledger.rotate_credentials(principal)
    return {'revokedPrincipals':principals,'recordsAndCustodyRetained':True,'retryAuthorized':False}
