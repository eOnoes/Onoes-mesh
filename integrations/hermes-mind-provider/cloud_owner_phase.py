"""Finite Windows owner phase; no defaults, key loading or service control.

The reviewed installer supplies the already leased canonical writer, exact
bindings, private custody and protected evidence folders. Imports do nothing.
"""
from contextlib import closing
import json
import os
from pathlib import Path

from onoes_mind.agent_home import AgentHome,WindowsAgentHomeCustody
from onoes_mind.agent_context import ProjectContextReader
from onoes_mind.context_host import WindowsReaderCustody
from onoes_mind.curated_home_import import import_curated_home
from onoes_mind.enrollment_store import qualify_private_storage
from onoes_mind.ledger import LedgerError
from cloud_enrollment import bindings,enroll,revoke_new,require


def save(root,name,value):
    qualify_private_storage(root)
    path=root/name
    with path.open('xb') as stream:
        stream.write((json.dumps(value,sort_keys=True,indent=2)+'\n').encode())
        stream.flush();os.fsync(stream.fileno())
    qualify_private_storage(path,kind='file')
    return True


def read(root,name):
    qualify_private_storage(root)
    path=root/name;qualify_private_storage(path,kind='file')
    require(path.stat().st_size<=16384)
    return json.loads(path.read_bytes())


def contract(writer,home,reader,private,shared,evidence,operator_token):
    bindings(home,reader)
    require(type(private) is WindowsAgentHomeCustody and type(shared) is WindowsReaderCustody
        and isinstance(evidence,Path) and private.directory!=shared.directory)
    expected_private=WindowsAgentHomeCustody(private.directory,home)
    expected_shared=WindowsReaderCustody(shared.directory,reader)
    require(private.entropy==expected_private.entropy and private.path==expected_private.path
        and shared.entropy==expected_shared.entropy and shared.path==expected_shared.path
        and evidence not in (private.directory,shared.directory))
    qualify_private_storage(evidence)
    require(writer.authenticate(operator_token)=='operator')


def admit(writer,home,reader,private,shared,*,operator_token,evidence,attempt_id,review_sha256,
          prepared_curated=None,remote_origin=None):
    contract(writer,home,reader,private,shared,evidence,operator_token)
    require(not private.path.exists() and not shared.path.exists())
    require((prepared_curated is None)==(remote_origin is None))
    if prepared_curated is not None:
        require(prepared_curated.binding==home
            and remote_origin['schema']=='onoes-cloud-curated-snapshot/v1'
            and remote_origin['origin']=='srv1693050/cyony-hermes'
            and remote_origin['privateTextIncluded'] is False
            and {s.name:s.sha256 for s in prepared_curated.sources}
                =={n:v['sha256'] for n,v in remote_origin['sources'].items()})
    attempt={'schema':'onoes-cloud-owner-attempt/v1','attemptId':attempt_id,
        'reviewSha256':review_sha256,'bindingSha256':bindings(home,reader)}
    save(evidence,'ADMIT-ATTEMPT.json',attempt)
    receipts=enroll(writer,home,reader,operator_token=operator_token,attempt_id=attempt_id,
        review_sha256=review_sha256,save_home_token=private.save_new,
        save_reader_token=shared.save_new,
        persist_receipt=lambda r:save(evidence,'ENROLLED-'+r['principal']+'.json',r))
    current=AgentHome(writer,home).recall(private.read(),{'kind':'profile'})
    require(current['agent_id']=='cyony' and current['records']==[])
    with closing(ProjectContextReader(home.store.database_path,binding=reader)) as live_reader:
        require(live_reader.authenticate(shared.read())=='context-cyony')
    imported=None
    if prepared_curated is not None:
        imported=import_curated_home(writer,home,operator_token=operator_token,home_token=private.read(),prepared=prepared_curated)
        rows=AgentHome(writer,home).recall(private.read(),{'kind':'profile','max_bytes':16384})['records']
        require(len(rows)==1 and rows[0]['record_id']==imported['receipt']['record_id']
            and rows[0]['claim']==prepared_curated.text)
        save(evidence,'CURATED-IMPORT.json',{'origin':remote_origin,'canonicalImport':imported,'currentReadback':True})
    result={'schema':'onoes-cloud-owner-result/v1','state':'admitted','attemptId':attempt_id,
        'privateAuthenticated':True,'sharedAuthenticated':True,'curatedImported':imported is not None,
        'receiptCount':len(receipts),'modelCalls':0,'remoteDelivery':False}
    save(evidence,'ADMITTED.json',result)
    return result


def revoke(writer,home,reader,private,shared,*,operator_token,evidence,attempt_id,review_sha256):
    contract(writer,home,reader,private,shared,evidence,operator_token)
    require(read(evidence,'ADMIT-ATTEMPT.json')=={'schema':'onoes-cloud-owner-attempt/v1',
        'attemptId':attempt_id,'reviewSha256':review_sha256,'bindingSha256':bindings(home,reader)})
    receipts=[read(evidence,'ENROLLED-cyony.json')]
    if (evidence/'ENROLLED-context-cyony.json').exists():receipts.append(read(evidence,'ENROLLED-context-cyony.json'))
    require(writer.authenticate(private.read())=='cyony')
    if len(receipts)==2:
        with closing(ProjectContextReader(home.store.database_path,binding=reader)) as live_reader:
            require(live_reader.authenticate(shared.read())=='context-cyony')
    save(evidence,'REVOKE-ATTEMPT.json',{'attemptId':attempt_id,'principals':[r['principal'] for r in receipts]})
    result=revoke_new(writer,home,reader,operator_token=operator_token,attempt_id=attempt_id,
        review_sha256=review_sha256,receipts=receipts)
    try:writer.authenticate(private.read())
    except LedgerError:pass
    else:raise ValueError('New private access revocation did not read back')
    if len(receipts)==2:
        with closing(ProjectContextReader(home.store.database_path,binding=reader)) as live_reader:
            try:live_reader.authenticate(shared.read())
            except LedgerError:pass
            else:raise ValueError('New shared access revocation did not read back')
    save(evidence,'REVOKED.json',result)
    return result
