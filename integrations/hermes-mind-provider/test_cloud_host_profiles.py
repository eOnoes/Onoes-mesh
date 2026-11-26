"""Data-only v6 to v7 preparation with unchanged existing host capabilities."""
from copy import deepcopy
import json

import pytest

from cloud_host_profiles import PROJECT,SCOPE,V6,V7,ProfileConflict,digest,encoded,prepare_host


@pytest.fixture
def selected(tmp_path):
    root=tmp_path/'private-control';old_sdk=tmp_path/'old-sdk';new_sdk=tmp_path/'new-sdk'
    store={'database_path':str(tmp_path/'store/ledger.sqlite'),'store_id':'fixture-store',
        'environment':'fixture','authority_ref':'fixture:owner','file_device':1,'file_inode':2,
        'scope_id':SCOPE,'custodian_ref':'fixture:custodian','revocation_ref':'fixture:revoke','review_ref':'fixture:review'}
    runtime={'schema':'fixture-runtime','runtime':{'python':str(tmp_path/'python'),'pwsh':str(tmp_path/'pwsh'),'mindSource':str(old_sdk)},
        'sourceHashes':{str(old_sdk/'example.py'):'a'*64},'projects':[[PROJECT,'Synthetic Mesh']],
        'unchanged_enrollment':{'id':'fixture-original','credentialPath':str(root/'existing.dpapi')}}
    service={'schema':V6,'sourceHashes':{str(tmp_path/'old-adapter.py'):'a'*64},
        'operatorProfilePath':str(root/'original-operator.json'),'operatorProfileSha256':'a'*64,
        'serviceRuntimeProfilePath':str(root/'old-runtime.json'),'serviceRuntimeProfileSha256':digest(encoded(runtime)),
        'enrolledMeshSourceDirectory':str(tmp_path/'original/mind-recovery-candidate'),
        'attemptPath':str(root/'old-attempt.json'),'readyPath':str(root/'old-ready.json'),'stopPath':str(root/'old-stop.json'),
        'agentHomeBindings':[{'agent_id':actor,'store':deepcopy(store)} for actor in ('deep','echo')],
        'agentHomePort':19124,'handoffBinding':{'store':deepcopy(store),'record_id':'rec_fixture',
            'handoff_id':'nims/onoes-mesh/current','project_id':PROJECT,'author':'nims'}}
    sources=tmp_path/'new-adapter/mind-recovery-candidate'
    args={'service_path':str(root/'old-service.json'),'mind_source':str(new_sdk),
        'runtime_source_hashes':{str(new_sdk/'example.py'):'b'*64},
        'service_source_hashes':{str(sources/name):'b'*64 for name in ('project_operator_process_candidate.py','project_service_process_candidate.py')},
        'new_runtime_path':str(root/'new-runtime.json'),'new_service_path':str(root/'new-service.json'),
        'new_attempt_path':str(root/'new-attempt.json'),'new_ready_path':str(root/'new-ready.json'),
        'new_stop_path':str(root/'new-stop.json'),'tool_grant_path':str(root/'cyony-tool-grant.json'),
        'tool_review_ref':'fixture:cyony-shared-only'}
    def prepare():
        values=dict(args);values.update(service_raw=encoded(service),runtime_raw=encoded(runtime),
            expected_service_sha256=digest(encoded(service)),expected_runtime_sha256=digest(encoded(runtime)))
        return prepare_host(**values)
    return service,runtime,args,prepare


def test_prepared_host_preserves_existing_actors_handoff_and_enrollment_without_granting_access(selected):
    service,runtime,args,prepare=selected;saved=(deepcopy(service),deepcopy(runtime),deepcopy(args))
    result=prepare();assert (service,runtime,args)==saved
    assert result.service['schema']==V7
    assert [r['agent_id'] for r in result.service['agentHomeBindings']]==['cyony','deep','echo']
    assert [r for r in result.service['agentHomeBindings'] if r['agent_id']!='cyony']==service['agentHomeBindings']
    for key in ('operatorProfilePath','operatorProfileSha256','handoffBinding','enrolledMeshSourceDirectory','agentHomePort'):
        assert result.service[key]==service[key]
    assert {k:v for k,v in result.runtime.items() if k not in ('runtime','sourceHashes')}=={k:v for k,v in runtime.items() if k not in ('runtime','sourceHashes')}
    row,=result.service['projectReaderBindings']
    assert row['binding']['principal_id']=='context-cyony' and row['binding']['project_id']==PROJECT
    assert row['binding']['store']['scope_id']==SCOPE
    report=result.descriptor()
    assert report['status']=='OWNER_APPROVAL_REQUIRED' and report['activated'] is False
    assert 'decision' not in report and 'actions' not in report


@pytest.mark.parametrize('case',['existing-cyony','different-store','different-handoff','unknown-field',
    'occupied-path','bad-pin','wrong-service-code','grant-in-store','blank-review'])
def test_changed_authority_or_unsafe_outputs_are_refused(selected,case):
    service,runtime,args,prepare=selected
    if case=='existing-cyony':service['agentHomeBindings'].insert(0,{'agent_id':'cyony','store':deepcopy(service['agentHomeBindings'][0]['store'])})
    elif case=='different-store':service['agentHomeBindings'][0]['store']['database_path']+='-other'
    elif case=='different-handoff':service['handoffBinding']['project_id']='other-project'
    elif case=='unknown-field':service['future_capability']='do-not-enable'
    elif case=='occupied-path':args['new_attempt_path']=service['attemptPath']
    elif case=='bad-pin':args['runtime_source_hashes'][next(iter(args['runtime_source_hashes']))]='not-a-hash'
    elif case=='wrong-service-code':args['service_source_hashes']={args['mind_source']+'/unknown.py':'b'*64}
    elif case=='grant-in-store':args['tool_grant_path']=service['agentHomeBindings'][0]['store']['database_path']+'.grant'
    else:args['tool_review_ref']=''
    saved=(deepcopy(service),deepcopy(runtime),deepcopy(args))
    with pytest.raises(ProfileConflict):prepare()
    assert (service,runtime,args)==saved


def test_other_existing_projects_are_retained_without_expanding_cyony_reader(selected):
    service,runtime,args,prepare=selected
    runtime['projects'].append(['other-existing-project','Keep its current writer enrollment'])
    service['serviceRuntimeProfileSha256']=digest(encoded(runtime))
    result=prepare()
    assert result.runtime['projects']==runtime['projects']
    assert [r['binding']['project_id'] for r in result.service['projectReaderBindings']]==[PROJECT]


def test_stale_raw_profile_is_refused_before_any_output_is_produced(selected):
    service,runtime,args,prepare=selected
    values={**args,'service_raw':encoded(service),'runtime_raw':encoded(runtime),
        'expected_service_sha256':'0'*64,'expected_runtime_sha256':digest(encoded(runtime))}
    with pytest.raises(ProfileConflict):prepare_host(**values)
