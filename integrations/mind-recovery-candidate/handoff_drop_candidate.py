"""Local owner-side JSON handoff drop; no store opener, enrollment or retry loop.

The reviewed client profile selects existing operator custody and one bound
record. Credential material never belongs in command arguments, files or output.
Cloud/other-agent writers require separate purpose-scoped enrollment instead.
"""
import argparse
from dataclasses import dataclass
import hashlib
import importlib
import json
import os
from pathlib import Path
import sys

sys.dont_write_bytecode=True

SCHEMA='onoes-mind-handoff-drop/v1'


def require(ok):
    if not ok:raise ValueError('Handoff drop refused; preserve the input and existing attempt.')


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf-8')
def digest(raw):return hashlib.sha256(raw).hexdigest()
def unique(pairs):
    value={}
    for key,item in pairs:require(key not in value);value[key]=item
    return value


def read(path,limit):
    with Path(path).open('rb') as f:raw=f.read(limit+1)
    require(0<len(raw)<=limit)
    return json.loads(raw.decode('utf-8'),object_pairs_hook=unique),raw


def source_paths(source):
    result={Path(__file__).resolve(),Path(sys.executable).resolve()}
    for pattern in ('*.py','*.mjs','*.ps1','migrations/*.sql'):result.update((source/'onoes_mind').glob(pattern))
    return result


@dataclass(frozen=True)
class Profile:
    path:Path
    sha256:str
    body:dict
    binding:object
    client:object
    transport_error:type


def load_profile(path,sha):
    path=Path(path)
    require(os.name=='nt' and path.is_absolute() and path.resolve(strict=True)==path)
    p,raw=read(path,65536);require(digest(raw)==sha)
    require(type(p) is dict and set(p)=={'schema','mindSource','sourceHashes','binding','endpoint',
        'custodyDirectory','inputDirectory','journalDirectory','reviewRef'} and p['schema']==SCHEMA)
    source=Path(p['mindSource']);require(source.is_absolute() and source.resolve(strict=True)==source)
    pins=p['sourceHashes'];require(type(pins) is dict and {Path(n) for n in pins}==source_paths(source)
        and all(digest(Path(n).read_bytes())==h for n,h in pins.items()))
    require(type(p['reviewRef']) is str and 1<=len(p['reviewRef'])<=512 and p['reviewRef'].strip()==p['reviewRef'])
    existing=sys.modules.get('onoes_mind')
    require(existing is None or Path(existing.__file__).resolve()==source/'onoes_mind/__init__.py')
    sys.path.insert(0,str(source))
    sdk=importlib.import_module('onoes_mind');require(Path(sdk.__file__).resolve()==source/'onoes_mind/__init__.py')
    from onoes_mind.enrollment_store import qualify_private_storage
    from onoes_mind.recall_binding import RecallBinding
    from onoes_mind.handoff_channel import HandoffBinding,HandoffClient,HandoffTransportError,handoff_binding_sha256
    from onoes_mind.context_enrollment import WindowsOperatorCustody
    qualify_private_storage(path,kind='file');qualify_private_storage(path.parent)
    for field in ('custodyDirectory','inputDirectory','journalDirectory'):
        root=Path(p[field]);require(root.is_absolute() and root.resolve(strict=True)==root)
        qualify_private_storage(root)
    require(len({Path(p[field]) for field in ('custodyDirectory','inputDirectory','journalDirectory')})==3)
    row=p['binding'];require(type(row) is dict and set(row)=={'store','record_id','handoff_id','project_id','author'})
    binding=HandoffBinding(RecallBinding(**row['store']),**{k:v for k,v in row.items() if k!='store'})
    require(binding.author=='nims')
    # Custody qualification reads permissions, not the credential. Its read
    # callback is invoked only for an explicit transport operation.
    custody=WindowsOperatorCustody(p['custodyDirectory'],binding.store)
    client=HandoffClient(p['endpoint'],binding_sha256=handoff_binding_sha256(binding),record_id=binding.record_id,
        credential_provider=custody.read,timeout=15)
    require(path.read_bytes()==raw)
    return Profile(path,sha,p,binding,client,HandoffTransportError)


def payload(profile,path):
    path=Path(path);root=Path(profile.body['inputDirectory'])
    require(path.is_absolute() and path.resolve(strict=True)==path and path.parent==root and path.suffix=='.json')
    value,_=read(path,40960)
    require(type(value) is dict and set(value)=={'expected_revision_id','event_id','document','review_ref'}
        and type(value['expected_revision_id']) is int and value['expected_revision_id']>0
        and type(value['event_id']) is str and 1<=len(value['event_id'])<=128
        and value['event_id'].strip()==value['event_id'] and value['review_ref']==profile.body['reviewRef'])
    from onoes_mind.agent_handoff import _document
    from onoes_mind.ledger import _secret_category
    document,_=_document(value['document'])
    require(all(document[key]==getattr(profile.binding,key) for key in ('handoff_id','project_id','author')))
    require(_secret_category(value) is None)
    return value


def save(path,value):
    with path.open('xb') as f:f.write(canonical(value));f.flush();os.fsync(f.fileno())


def publish(profile,path,*,reconcile=False):
    require(digest(profile.path.read_bytes())==profile.sha256)
    value=payload(profile,path);payload_sha=digest(canonical(value))
    key=digest((profile.client.binding_sha256+'\0'+value['event_id']).encode())
    root=Path(profile.body['journalDirectory']);intent=root/(key+'.intent.json');receipt=root/(key+'.receipt.json')
    refused=root/(key+'.refused.json')
    metadata={'schema':'onoes-handoff-drop-intent/v1','bindingSha256':profile.client.binding_sha256,
        'recordId':profile.binding.record_id,'eventId':value['event_id'],'payloadSha256':payload_sha}
    if reconcile:
        recorded,_=read(intent,4096);require(recorded==metadata)
        if receipt.exists():
            result,_=read(receipt,8192)
            require(type(result) is dict and result.get('durable') is True
                and result.get('contract_version')=='handoff_revise@1'
                and result.get('event_id')==value['event_id'] and result.get('record_id')==profile.binding.record_id
                and type(result.get('receipt_id')) is str and bool(result['receipt_id']))
            return {'status':'already_acknowledged','receipt':result,'currentStateVerified':False}
        require(not refused.exists())
    else:
        require(not receipt.exists() and not refused.exists())
        save(intent,metadata) # Exclusive creation admits only one first send.
    try:result=profile.client.call('revise',value)
    except profile.transport_error as error:
        status='outcome_unconfirmed' if error.outcome_uncertain else 'refused'
        result={'status':status,'eventId':value['event_id'],'automaticRetry':False}
        if not error.outcome_uncertain:save(refused,result)
        return result
    try:save(receipt,result)
    except FileExistsError:
        previous,_=read(receipt,8192);require(previous==result)
    except OSError:
        return {'status':'outcome_unconfirmed','eventId':value['event_id'],'automaticRetry':False}
    return {'status':'acknowledged','receipt':result,'currentStateVerified':False}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',required=True);parser.add_argument('--sha256',required=True)
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--preview',action='store_true');group.add_argument('--read',action='store_true')
    group.add_argument('--publish');group.add_argument('--reconcile')
    args=parser.parse_args()
    try:
        require(sys.flags.isolated==1)
        profile=load_profile(args.profile,args.sha256)
        if args.preview:
            result={'profileVerified':True,'recordId':profile.binding.record_id,'projectId':profile.binding.project_id,
                'credentialRead':False,'memoryWritten':False}
        elif args.read:result=profile.client.call('read',{})
        else:result=publish(profile,args.publish or args.reconcile,reconcile=bool(args.reconcile))
        print(canonical(result).decode('utf-8'))
        return 0 if result.get('status') not in ('refused','outcome_unconfirmed') else 2
    except Exception:
        print(json.dumps({'status':'held','message':'Preserve the input and original attempt; inspect before retrying.'}))
        return 1


if __name__=='__main__':raise SystemExit(main())
