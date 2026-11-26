"""Prepare the existing v7 host view; no enrollment or runtime operation.

The returned profile is not an owner approval. The existing native service
validator and an explicit new owner decision remain required before launch.
"""
from copy import deepcopy
from dataclasses import dataclass,field
import hashlib
import json
from pathlib import Path
import re

V6='onoes-mind-project-service/v6'
V7='onoes-mind-project-service/v7'
SCOPE='project/onoes-mind/shared'
PROJECT='onoes-mesh'
SERVICE_KEYS={'schema','sourceHashes','operatorProfilePath','operatorProfileSha256',
    'attemptPath','readyPath','stopPath','serviceRuntimeProfilePath',
    'serviceRuntimeProfileSha256','enrolledMeshSourceDirectory',
    'agentHomeBindings','agentHomePort','handoffBinding'}
CORE_STORE=('database_path','store_id','environment','authority_ref','file_device','file_inode')


class ProfileConflict(ValueError):pass


def require(ok):
    if not ok:raise ProfileConflict('Host preparation inputs, source or selected scope changed')


def digest(raw):return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def unique(pairs):
    out={}
    for key,value in pairs:
        require(key not in out);out[key]=value
    return out


def absolute(value):
    path=Path(value)
    require(path.is_absolute() and '..' not in path.parts)
    return path


def pins(value):
    require(type(value) is dict and value and all(type(k) is str and absolute(k)
        and type(v) is str and re.fullmatch('[0-9a-f]{64}',v) for k,v in value.items()))
    return deepcopy(value)


@dataclass(frozen=True)
class PreparedHost:
    original_service_path:str
    original_service_sha256:str
    original_runtime_sha256:str
    runtime_path:str
    service_path:str
    runtime:dict=field(repr=False)
    service:dict=field(repr=False)

    def descriptor(self):
        return {'schema':'onoes-cloud-host-preparation/v1','status':'OWNER_APPROVAL_REQUIRED',
            'originalServicePath':self.original_service_path,'originalServiceSha256':self.original_service_sha256,
            'originalRuntimeSha256':self.original_runtime_sha256,'runtimePath':self.runtime_path,
            'runtimeSha256':digest(encoded(self.runtime)),'servicePath':self.service_path,
            'serviceSha256':digest(encoded(self.service)),'newPrivateActor':'cyony',
            'newReaderPrincipal':'context-cyony','sharedProject':PROJECT,
            'existingActorBindingHashes':{row['agent_id']:digest(encoded(row))
                for row in self.service['agentHomeBindings'] if row['agent_id']!='cyony'},
            'handoffBindingSha256':digest(encoded(self.service['handoffBinding'])),
            'activated':False,'credentialsCreated':False}


def prepare_host(*,service_raw,runtime_raw,service_path,expected_service_sha256,expected_runtime_sha256,
                 mind_source,runtime_source_hashes,service_source_hashes,new_runtime_path,new_service_path,
                 new_attempt_path,new_ready_path,new_stop_path,tool_grant_path,tool_review_ref):
    require(type(service_raw) is bytes and type(runtime_raw) is bytes
        and digest(service_raw)==expected_service_sha256 and digest(runtime_raw)==expected_runtime_sha256)
    old=json.loads(service_raw,object_pairs_hook=unique);view=json.loads(runtime_raw,object_pairs_hook=unique)
    require(type(old) is dict and set(old)==SERVICE_KEYS and old['schema']==V6
        and old['serviceRuntimeProfileSha256']==expected_runtime_sha256 and type(view) is dict
        and type(view.get('runtime')) is dict and set(view['runtime'])=={'python','pwsh','mindSource'}
        and type(view.get('sourceHashes')) is dict and type(old['agentHomePort']) is int
        and 1024<=old['agentHomePort']<=65535)
    original=absolute(service_path);root=absolute(old['operatorProfilePath']).parent
    old_view=absolute(old['serviceRuntimeProfilePath'])
    require(original.parent==root and old_view.parent==root)
    destinations=[absolute(p) for p in (new_runtime_path,new_service_path,new_attempt_path,new_ready_path,new_stop_path)]
    occupied={original,old_view,absolute(old['operatorProfilePath'])}
    occupied.update(absolute(old[k]) for k in ('attemptPath','readyPath','stopPath'))
    require(len(set(destinations))==5 and all(p.parent==root and p not in occupied for p in destinations))
    source=absolute(mind_source);runtime_pins=pins(runtime_source_hashes);service_pins=pins(service_source_hashes)
    require({Path(k).name for k in service_pins}=={'project_service_process_candidate.py','project_operator_process_candidate.py'}
        and len(service_pins)==2 and len({Path(k).parent for k in service_pins})==1)
    rows=old['agentHomeBindings']
    require(type(rows) is list and all(type(row) is dict and set(row)=={'agent_id','store'} for row in rows)
        and [row['agent_id'] for row in rows]==['deep','echo'])
    store=rows[1]['store']
    require(type(store) is dict and store.get('scope_id')==SCOPE and all(k in store for k in CORE_STORE)
        and all(type(row['store']) is dict and row['store'].get('scope_id')==SCOPE
            and all(row['store'].get(k)==store[k] for k in CORE_STORE) for row in rows))
    handoff=old['handoffBinding']
    require(type(handoff) is dict and handoff.get('author')=='nims' and handoff.get('project_id')==PROJECT
        and type(handoff.get('store')) is dict and handoff['store'].get('scope_id')==SCOPE
        and all(handoff['store'].get(k)==store[k] for k in CORE_STORE)
        and PROJECT in [p[0] for p in view.get('projects',[])])
    grant=absolute(tool_grant_path)
    require(grant not in occupied|set(destinations) and not grant.is_relative_to(Path(store['database_path']).parent)
        and not grant.is_relative_to(source) and not any(grant.is_relative_to(Path(k).parent) for k in service_pins)
        and type(tool_review_ref) is str and 1<=len(tool_review_ref)<=256
        and tool_review_ref.strip()==tool_review_ref and not re.search(r'[\x00-\x1f\x7f]',tool_review_ref))
    new_view=deepcopy(view)
    new_view['runtime']={**new_view['runtime'],'mindSource':str(source)}
    new_view['sourceHashes']=runtime_pins
    proposed=deepcopy(old)
    proposed.update(schema=V7,sourceHashes=service_pins,serviceRuntimeProfilePath=str(destinations[0]),
        serviceRuntimeProfileSha256=digest(encoded(new_view)),
        attemptPath=str(destinations[2]),readyPath=str(destinations[3]),stopPath=str(destinations[4]),
        agentHomeBindings=sorted([*deepcopy(rows),{'store':deepcopy(store),'agent_id':'cyony'}],key=lambda r:r['agent_id']),
        projectReaderBindings=[{'binding':{'store':deepcopy(store),'principal_id':'context-cyony','project_id':PROJECT},
            'toolGrantPath':str(grant),'toolReviewRef':tool_review_ref}])
    return PreparedHost(str(original),expected_service_sha256,expected_runtime_sha256,
        str(destinations[0]),str(destinations[1]),new_view,proposed)
