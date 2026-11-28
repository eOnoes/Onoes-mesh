"""Constructor-only authority checks for NativePhases legacy-case acceptance.

All fixtures are local synthetic dicts; no file reads, no children. A spy makes
execute_once raise if any construction path ever attempts an operation. A
successful constructor is not approval, production retirement or deployment.
"""
import pytest

import cloud_phase_runner
from cloud_phase_runner import NativePhases, PhaseTransportHeld

PLAN_SHA='a'*64
POLICY_SHA='b'*64


@pytest.fixture(autouse=True)
def no_child_execution(monkeypatch):
    def spy(argv,**kwargs):
        raise AssertionError('NativePhases construction must perform no operation')
    monkeypatch.setattr(cloud_phase_runner,'execute_once',spy)


def plan(*, legacy=True):
    value={'schema':'onoes-cloud-install-window/v1','agentId':'cyony',
        'readerPrincipal':'context-cyony','sharedProject':'onoes-mesh','modelCalls':0,
        'maintenanceTask':'ONOes Mesh Workroom Recovery'}
    if legacy:
        value['legacyCasePolicy']={'path':'/srv/legacy-case.json',
            'sha256':POLICY_SHA,'originalAttempts':{'r12':{},'r13':{}}}
    return value


def auth(*, v2=True,plan_sha=PLAN_SHA,policy_sha=POLICY_SHA):
    if v2:
        return {'schema':'onoes-cloud-install-authorization/v2','owner':'Eddie',
            'decision':'approve_cyony_private_home_and_mesh_reader_with_exact_legacy_case_policy',
            'planSha256':plan_sha,'legacyCaseSha256':policy_sha}
    return {'schema':'onoes-cloud-install-authorization/v1','owner':'Eddie',
        'decision':'approve_cyony_private_home_and_mesh_reader','planSha256':plan_sha}


def build(p,plan_sha,authorization):
    return NativePhases(p,plan_sha,authorization,'unused-evidence-path')


def test_strict_v1_without_policy_key_stores_exact_plan_and_performs_no_operation():
    p=plan(legacy=False)
    runner=build(p,PLAN_SHA,auth(v2=False))
    assert runner.plan is p


def test_opt_in_v2_with_descriptor_stores_exact_plan_and_performs_no_operation():
    p=plan()
    runner=build(p,PLAN_SHA,auth())
    assert runner.plan is p


@pytest.mark.parametrize('mutation', [
    lambda p:p.pop('legacyCasePolicy'),                      # v2 auth against strict plan
    lambda p:p.pop('agentId'),                               # missing agent contract
    lambda p:p.update(agentId='other'),                      # agent deep/different
    lambda p:p.update(sharedProject='all'),                  # project all
    lambda p:p.update(readerPrincipal='context-other'),      # reader other
    lambda p:p.update(modelCalls=1),                         # modelCalls 1
    lambda p:p.update(modelCalls='0'),                       # modelCalls wrong type
    lambda p:p.update(maintenanceTask='Other Task'),         # wrong task
    lambda p:p.update(schema='onoes-cloud-install-window/v2'),
])
def test_legacy_v2_rejects_plan_contract_mutation(mutation):
    p=plan();mutation(p)
    with pytest.raises(PhaseTransportHeld):
        build(p,PLAN_SHA,auth())


@pytest.mark.parametrize('mutation', [
    lambda p:p.update(agentId='other'),
    lambda p:p.update(sharedProject='all'),
    lambda p:p.update(readerPrincipal='context-other'),
    lambda p:p.update(modelCalls=1),
    lambda p:p.update(maintenanceTask='Other Task'),
    lambda p:p.update(legacyCasePolicy={'path':'/x','sha256':POLICY_SHA,'originalAttempts':{}}),
])
def test_old_v1_rejects_plan_with_optional_policy_key_or_drift(mutation):
    p=plan(legacy=False);mutation(p)
    with pytest.raises(PhaseTransportHeld):
        build(p,PLAN_SHA,auth(v2=False))


@pytest.mark.parametrize('authorization', [
    None,
    'approve',
    {},
    auth(plan_sha='c'*64),                                   # wrong plan hash
    auth(policy_sha='c'*64),                                 # wrong policy hash
    {**auth(),'planSha256':'A'*64},                          # uppercase plan hash
    {**auth(),'planSha256':'a'*63},                          # short plan hash
    {**auth(),'decision':'approve_cyony_private_home_and_mesh_reader'},   # wrong decision
    {**auth(),'decision':'approve_development_only'},        # development decision
    {**auth(),'schema':'onoes-cloud-install-authorization/v1'},           # v1 schema
    {**auth(),'extra':'value'},                              # extra auth field
    {k:v for k,v in auth().items() if k!='legacyCaseSha256'},# missing auth field
])
def test_malformed_or_mismatched_authorization_holds(authorization):
    with pytest.raises(PhaseTransportHeld):
        build(plan(),PLAN_SHA,authorization)


@pytest.mark.parametrize('mutation', [
    lambda d:None,                                           # null descriptor
    lambda d:{},                                             # empty descriptor
    lambda d:{'path':'/x','sha256':POLICY_SHA},              # missing originalAttempts
    lambda d:{'path':'/x','sha256':POLICY_SHA,'originalAttempts':{},'extra':1},
    lambda d:{'sha256':POLICY_SHA,'originalAttempts':{}},    # missing path
    lambda d:{'path':'/x','sha256':' '+'b'*64,'originalAttempts':{}},      # whitespace
    lambda d:{'path':'/x','sha256':'+'+POLICY_SHA,'originalAttempts':{}},  # plus sign
    lambda d:{'path':'/x','sha256':'B'*64,'originalAttempts':{}},          # uppercase
    lambda d:{'path':'/x','sha256':'z'*64,'originalAttempts':{}},          # non-hex
    lambda d:{'path':'/x','sha256':'b'*63,'originalAttempts':{}},          # short
    lambda d:{'path':'/x','sha256':True,'originalAttempts':{}},            # bool
])
def test_null_or_malformed_descriptor_holds_without_v1_fallback(mutation):
    p=plan();p['legacyCasePolicy']=mutation(p['legacyCasePolicy'])
    for authorization in (auth(),auth(v2=False)):
        with pytest.raises(PhaseTransportHeld):
            build(p,PLAN_SHA,authorization)


@pytest.mark.parametrize('plan_sha', [None,'A'*64,'a'*63,'a'*65,'z'*64,0])
def test_plan_sha_must_be_lowercase_64_hex(plan_sha):
    with pytest.raises(PhaseTransportHeld):
        build(plan(legacy=False),plan_sha,auth(v2=False,plan_sha=plan_sha))


def test_malformed_authority_input_is_sanitized_not_raw_error():
    p=plan();p['legacyCasePolicy']='not-a-dict'
    with pytest.raises(PhaseTransportHeld):
        build(p,PLAN_SHA,auth())
    with pytest.raises(PhaseTransportHeld):
        build('not-a-dict',PLAN_SHA,auth())
    with pytest.raises(PhaseTransportHeld):
        build(plan(),PLAN_SHA,{k:v for k,v in auth().items() if k!='schema'})
