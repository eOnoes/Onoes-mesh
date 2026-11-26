"""Prepare an inactive nested Mesh startup view for the reviewed v7 host.

No filesystem writes, enrollment, credential loading, listener or launch. The
existing owner installer must separately authorize and select these views.
"""
from copy import deepcopy
from dataclasses import dataclass,field
import hashlib
import json
from pathlib import Path
from types import MappingProxyType

NAMES={'capture','capture-approval','connected','connected-approval','writer-approval','handoff','memory','startup'}
SCHEMAS={'connected':'onoes-mesh-native-launch/v2','handoff':'onoes-mesh-capture-handoff-approval/v1',
    'memory':'onoes-mesh-native-recovery-approval/v1','startup':'onoes-mesh-capture-first-approval/v1',
    'capture':'onoes-mesh-native-capture-launch/v1','capture-approval':'onoes-mesh-offline-capture-approval/v1'}


class StartupConflict(ValueError):pass


def require(ok):
    if not ok:raise StartupConflict('Startup graph or reviewed host differs; no views selected')


def digest(raw):return hashlib.sha256(raw).hexdigest()


def encoded(body):return json.dumps(body,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def unique(pairs):
    result={}
    for k,v in pairs:require(k not in result);result[k]=v
    return result


def absolute(value):
    require(type(value) is str)
    p=Path(value);require(p.is_absolute() and '..' not in p.parts)
    return p


@dataclass(frozen=True)
class PreparedStartup:
    originals:object=field(repr=False)
    files:object=field(repr=False)
    paths:object=field(repr=False)
    service_path:str
    service_sha256:str

    def descriptor(self):
        return {'schema':'onoes-cloud-startup-preparation/v1','status':'OWNER_APPROVAL_REQUIRED',
            'activated':False,'credentialsCreated':False,
            'servicePath':self.service_path,'serviceSha256':self.service_sha256,
            'views':{n:{'path':self.paths[n],'sha256':digest(b)} for n,b in self.files.items()}}


def prepare_startup(*,originals,original_paths,original_sha256,new_paths,
                    service_path,service_raw,expected_service_sha256,
                    home_descriptor,project_descriptor,source_replacements,launch_paths):
    """Retain the reader/settings/data links, replace only reviewed host links.

    Descriptors come from the reviewed native service's pure home_approval and
    project_read_approval functions. They are proposed grant contents, not an
    approval. The enclosing installer verifies their source before selection.
    """
    require(all(type(v) is dict and set(v)==NAMES for v in (originals,original_paths,original_sha256,new_paths)))
    old={}
    for name,raw in originals.items():
        require(type(raw) is bytes and digest(raw)==original_sha256[name])
        old[name]=json.loads(raw,object_pairs_hook=unique)
        require(type(old[name]) is dict)
        if name in SCHEMAS:require(old[name]['schema']==SCHEMAS[name])
    before={n:absolute(p) for n,p in original_paths.items()};after={n:absolute(p) for n,p in new_paths.items()}
    service_path=absolute(service_path);root=before['startup'].parent
    require(len(set(before.values()))==8 and len(set(after.values()))==8
        and not set(before.values())&set(after.values()) and service_path not in set(before.values())|set(after.values())
        and all(p.parent==root for p in [*before.values(),*after.values(),service_path]))
    require(type(service_raw) is bytes and digest(service_raw)==expected_service_sha256)
    host=json.loads(service_raw,object_pairs_hook=unique)
    require(host['schema']=='onoes-mind-project-service/v7'
        and [r['agent_id'] for r in host['agentHomeBindings']]==['cyony','deep','echo']
        and len(host['projectReaderBindings'])==1)
    read=host['projectReaderBindings'][0];bound=read['binding']
    require(bound['principal_id']=='context-cyony' and bound['project_id']=='onoes-mesh'
        and bound['store']['scope_id']=='project/onoes-mind/shared')
    expected_home={'decision':'approve_exact_private_agent_homes','port':host['agentHomePort'],
        'bindings':{r['agent_id']:digest(encoded(r)) for r in host['agentHomeBindings']}}
    expected_reader={'decision':'approve_exact_shared_project_readers','port':host['agentHomePort'],
        'readers':{'context-cyony':{'bindingSha256':digest(encoded(bound)),'projectId':'onoes-mesh',
            'scopeId':'project/onoes-mind/shared','toolGrantPath':str(Path(read['toolGrantPath'])),
            'toolReviewRef':read['toolReviewRef']}}}
    require(home_descriptor==expected_home and project_descriptor==expected_reader)
    connected=old['connected'];grant=old['writer-approval'];handoff=old['handoff'];memory=old['memory'];startup=old['startup']
    def link(body,key,name,sha_key):
        require(body[key]==str(before[name]) and body[sha_key]==original_sha256[name])
    require(connected['projectSync']['approvalPath']==str(before['writer-approval'])
        and connected['projectSync']['serviceProfileSha256'] in grant['profiles'])
    link(handoff['connected'],'profilePath','connected','profileSha256')
    link(handoff['connected'],'approvalPath','connected-approval','approvalSha256')
    link(handoff['connected'],'projectApprovalPath','writer-approval','projectApprovalSha256')
    link(handoff['capture'],'profilePath','capture','profileSha256')
    link(handoff['capture'],'approvalPath','capture-approval','approvalSha256')
    require(old['capture-approval']['profileSha256']==original_sha256['capture'])
    link(memory,'profilePath','connected','profileSha256')
    link(startup,'handoffApprovalPath','handoff','handoffApprovalSha256')
    link(startup,'memoryApprovalPath','memory','memoryApprovalSha256')
    require(grant['agentHomes']=={'decision':expected_home['decision'],'port':expected_home['port'],
        'bindings':{n:h for n,h in expected_home['bindings'].items() if n!='cyony'}}
        and set(grant['actions'])=={'run_agent_homes','run_handoff_refresh','run_mesh_sync','run_service'}
        and len(grant['actions'])==4 and 'projectReads' not in grant)
    handoff_pin=digest(json.dumps(host['handoffBinding'],ensure_ascii=True,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
    require(grant['handoffRefresh']['bindingSha256']==handoff_pin
        and host['handoffBinding']['author']=='nims' and host['handoffBinding']['project_id']=='onoes-mesh'
        and grant['handoffRefresh']['recordId']==host['handoffBinding']['record_id'])
    require(grant['profiles'].count(original_sha256['connected'])==1
        and grant['profiles'].count(connected['projectSync']['serviceProfileSha256'])==1
        and len(grant['profiles'])==2
        and old['connected-approval']['profiles'].count(original_sha256['connected'])==1)
    proposed=deepcopy(old)
    require(type(source_replacements) is dict and len(source_replacements)==1)
    for source,change in source_replacements.items():
        require(absolute(source).name=='project_service_process_candidate.py'
            and type(change) is dict and set(change)=={'before','after'}
            and type(change['before']) is str and type(change['after']) is str
            and len(change['before'])==len(change['after'])==64 and change['before']!=change['after'])
        for name in ('capture','connected'):
            require(proposed[name]['sourceHashes'][source]==change['before'])
            proposed[name]['sourceHashes'][source]=change['after']
    require(type(launch_paths) is dict and set(launch_paths)=={'capture','connected'})
    states=[]
    for name,paths in launch_paths.items():
        require(type(paths) is dict and set(paths)=={'attemptPath','stdoutPath','stderrPath'})
        for key,value in paths.items():
            path=absolute(value);require(path.parent==root and value!=old[name][key])
            states.append(path)
        proposed[name].update(paths)
    require(len(set(states))==6 and not set(states)&(set(before.values())|set(after.values())|{service_path})
        and not set(states)&{absolute(old[n][k]) for n in ('capture','connected') for k in launch_paths[n]})
    proposed['connected']['projectSync'].update(approvalPath=str(after['writer-approval']),
        serviceProfile=str(service_path),serviceProfileSha256=expected_service_sha256)
    new_connected=digest(encoded(proposed['connected']))
    proposed['writer-approval'].update(profiles=[expected_service_sha256,new_connected],
        actions=[*grant['actions'],'run_project_reads'],agentHomes=deepcopy(home_descriptor),projectReads=deepcopy(project_descriptor))
    proposed['connected-approval']['profiles']=[new_connected if p==original_sha256['connected'] else p
        for p in old['connected-approval']['profiles']]
    new_capture=digest(encoded(proposed['capture']))
    proposed['capture-approval']['profileSha256']=new_capture
    proposed['handoff']['capture'].update(profilePath=str(after['capture']),profileSha256=new_capture,
        approvalPath=str(after['capture-approval']),approvalSha256=digest(encoded(proposed['capture-approval'])))
    proposed['handoff']['connected'].update(profilePath=str(after['connected']),profileSha256=new_connected,
        approvalPath=str(after['connected-approval']),approvalSha256=digest(encoded(proposed['connected-approval'])),
        projectApprovalPath=str(after['writer-approval']),projectApprovalSha256=digest(encoded(proposed['writer-approval'])))
    proposed['memory'].update(profilePath=str(after['connected']),profileSha256=new_connected)
    proposed['startup'].update(handoffApprovalPath=str(after['handoff']),handoffApprovalSha256=digest(encoded(proposed['handoff'])),
        memoryApprovalPath=str(after['memory']),memoryApprovalSha256=digest(encoded(proposed['memory'])))
    return PreparedStartup(MappingProxyType(dict(originals)),MappingProxyType({n:encoded(v) for n,v in proposed.items()}),
        MappingProxyType({n:str(p) for n,p in after.items()}),str(service_path),expected_service_sha256)
