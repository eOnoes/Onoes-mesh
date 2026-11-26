"""Inactive nested startup graph, integrity refusals and preserved existing paths."""
from copy import deepcopy
import json

import pytest

from cloud_startup_profiles import NAMES,StartupConflict,prepare_startup,encoded,digest


@pytest.fixture
def graph(tmp_path):
    root=tmp_path/'operations';workspace=tmp_path/'mesh'
    source=str(workspace/'integrations/mind-recovery-candidate/project_service_process_candidate.py')
    old_paths={n:str(root/('old-'+n+'.json')) for n in NAMES}
    new_paths={n:str(root/('new-'+n+'.json')) for n in NAMES}
    store={'store_id':'synthetic','scope_id':'project/onoes-mind/shared','authority_ref':'owner:caf\u00e9'}
    homes=[{'agent_id':n,'store':deepcopy(store)} for n in ('cyony','deep','echo')]
    handoff={'store':deepcopy(store),'author':'nims','record_id':'rec_fixed','project_id':'onoes-mesh'}
    bound={'store':deepcopy(store),'principal_id':'context-cyony','project_id':'onoes-mesh'}
    host={'schema':'onoes-mind-project-service/v7','agentHomeBindings':homes,'agentHomePort':19124,
        'handoffBinding':handoff,'projectReaderBindings':[{'binding':bound,'toolGrantPath':str(root/'tool.json'),'toolReviewRef':'synthetic:review'}]}
    hd={'decision':'approve_exact_private_agent_homes','port':19124,'bindings':{r['agent_id']:digest(encoded(r)) for r in homes}}
    pd={'decision':'approve_exact_shared_project_readers','port':19124,'readers':{'context-cyony':{
        'bindingSha256':digest(encoded(bound)),'projectId':'onoes-mesh','scopeId':store['scope_id'],
        'toolGrantPath':str(root/'tool.json'),'toolReviewRef':'synthetic:review'}}}
    def raw(body):return json.dumps(body,indent=2,ensure_ascii=False).encode()
    def pin(body):return digest(raw(body))
    def node(schema,name):return {'schema':schema,'sourceHashes':{source:'a'*64},'workspace':str(workspace),
        **{k:str(root/('old-'+name+'-'+k+'.json')) for k in ('attemptPath','stdoutPath','stderrPath')}}
    cap=node('onoes-mesh-native-capture-launch/v1','capture');cap['projectCapture']={'sentinel':'same source binding'}
    cap['settings']={'MESH_RELAY':'1'};cap['runtime']={'mindSource':'keep old offline SDK'}
    ca={'schema':'onoes-mesh-offline-capture-approval/v1','profileSha256':pin(cap)}
    c=node('onoes-mesh-native-launch/v2','connected')
    c.update(readerProfile='same-reader.json',readerProfileSha256='d'*64,
        settings={'MESH_RELAY':'1','MESH_SIMPLE_FLOW':'0'},projectSync={
            'approvalPath':old_paths['writer-approval'],'serviceProfile':str(root/'old-service.json'),
            'serviceProfileSha256':'b'*64,'links':[{'cardId':'existing-card','fields':['title','goal']}],
            'source':{'databasePath':'existing-tasks.sqlite','fileInode':'keep'}})
    wa={'profiles':['b'*64,pin(c)],'actions':['run_agent_homes','run_handoff_refresh','run_mesh_sync','run_service'],
        'agentHomes':{**hd,'bindings':{n:h for n,h in hd['bindings'].items() if n!='cyony'}},
        'handoffRefresh':{'bindingSha256':digest(json.dumps(handoff,ensure_ascii=True,sort_keys=True,separators=(',',':')).encode()),
            'recordId':'rec_fixed'},'reviewRef':'preserve-review','projects':['onoes-mesh']}
    a={'profiles':['c'*64,'d'*64,pin(c)],'scopeId':store['scope_id'],'reviewRef':'preserve-reader-review'}
    h={'schema':'onoes-mesh-capture-handoff-approval/v1','workspace':str(workspace),
        'capture':{'profilePath':old_paths['capture'],'profileSha256':pin(cap),
            'approvalPath':old_paths['capture-approval'],'approvalSha256':pin(ca)},
        'connected':{'profilePath':old_paths['connected'],'profileSha256':pin(c),
            'approvalPath':old_paths['connected-approval'],'approvalSha256':pin(a),
            'projectApprovalPath':old_paths['writer-approval'],'projectApprovalSha256':pin(wa)}}
    m={'schema':'onoes-mesh-native-recovery-approval/v1','profilePath':old_paths['connected'],
        'profileSha256':pin(c),'readerServiceProfile':'same-reader-service.json','readerServiceSha256':'e'*64}
    s={'schema':'onoes-mesh-capture-first-approval/v1','handoffApprovalPath':old_paths['handoff'],
        'handoffApprovalSha256':pin(h),'memoryApprovalPath':old_paths['memory'],'memoryApprovalSha256':pin(m)}
    bodies={'capture':cap,'capture-approval':ca,'connected':c,'connected-approval':a,
        'writer-approval':wa,'handoff':h,'memory':m,'startup':s}
    originals={n:raw(b) for n,b in bodies.items()}
    return dict(originals=originals,original_paths=old_paths,original_sha256={n:digest(b) for n,b in originals.items()},
        new_paths=new_paths,service_path=str(root/'new-service.json'),service_raw=encoded(host),
        expected_service_sha256=digest(encoded(host)),home_descriptor=hd,project_descriptor=pd,
        source_replacements={source:{'before':'a'*64,'after':'f'*64}},
        launch_paths={n:{k:str(root/('new-'+n+'-'+k+'.json')) for k in ('attemptPath','stdoutPath','stderrPath')}
            for n in ('capture','connected')})


def test_nested_fingerprints_agree_and_existing_reader_settings_links_and_raw_backups_are_preserved(graph):
    original=deepcopy(graph);plan=prepare_startup(**graph);v={n:json.loads(raw) for n,raw in plan.files.items()}
    assert graph==original and dict(plan.originals)==graph['originals']
    meta=plan.descriptor();assert meta['status']=='OWNER_APPROVAL_REQUIRED' and meta['activated'] is False
    assert v['startup']['handoffApprovalSha256']==digest(plan.files['handoff'])
    assert v['startup']['memoryApprovalSha256']==digest(plan.files['memory'])
    for label in ('capture','connected'):
        assert v['handoff'][label]['profileSha256']==digest(plan.files[label])
        assert v['handoff'][label]['approvalSha256']==digest(plan.files[label+'-approval'])
    assert v['capture-approval']['profileSha256']==digest(plan.files['capture'])
    assert v['handoff']['connected']['projectApprovalSha256']==digest(plan.files['writer-approval'])
    assert digest(plan.files['connected']) in v['writer-approval']['profiles']
    assert digest(plan.files['connected']) in v['connected-approval']['profiles']
    old={n:json.loads(b) for n,b in graph['originals'].items()}
    for key in ('settings','readerProfile','readerProfileSha256'):
        assert v['connected'][key]==old['connected'][key]
    for key in ('links','source'):assert v['connected']['projectSync'][key]==old['connected']['projectSync'][key]
    assert v['memory']['readerServiceProfile']==old['memory']['readerServiceProfile']
    assert v['capture']['runtime']==old['capture']['runtime']
    assert v['writer-approval']['handoffRefresh']==old['writer-approval']['handoffRefresh']
    with pytest.raises(TypeError):plan.files['connected']=b'changed'


@pytest.mark.parametrize('case',['changed-raw','broken-link','wrong-scope','wrong-actor','changed-source',
    'occupied-launch','old-target','wrong-service-pin','existing-project-grant'])
def test_changed_or_expanded_inputs_refuse_before_any_view_is_selected(graph,case):
    if case=='changed-raw':graph['originals']['startup']+=b' '
    elif case in ('broken-link','existing-project-grant'):
        name='startup' if case=='broken-link' else 'writer-approval'
        v=json.loads(graph['originals'][name])
        if case=='broken-link':v['memoryApprovalSha256']='0'*64
        else:v['projectReads']={'unreviewed':'existing'}
        graph['originals'][name]=encoded(v);graph['original_sha256'][name]=digest(encoded(v))
    elif case=='wrong-scope':graph['project_descriptor']['readers']['context-cyony']['scopeId']='agent/echo/private'
    elif case=='wrong-actor':graph['home_descriptor']['bindings']['cyony']='0'*64
    elif case=='changed-source':next(iter(graph['source_replacements'].values()))['before']='0'*64
    elif case=='occupied-launch':graph['launch_paths']['capture']['attemptPath']=json.loads(graph['originals']['capture'])['attemptPath']
    elif case=='old-target':graph['new_paths']['startup']=graph['original_paths']['startup']
    else:graph['expected_service_sha256']='0'*64
    with pytest.raises(StartupConflict):prepare_startup(**graph)
