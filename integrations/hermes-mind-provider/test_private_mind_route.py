"""One private Mind route, preserving Mesh and independently managed routes."""
from copy import deepcopy

import pytest

from private_mind_route import MOUNT,RouteConflict,commands,fingerprint,prepare,rollback

HOST='echo.synthetic.ts.net'
KEY=HOST+':8453'


def existing():
    return {'TCP':{'8453':{'HTTPS':True},'8443':{'HTTPS':True}},
        'Web':{KEY:{'Handlers':{'/':{'Proxy':'http://127.0.0.1:4320'},'/existing/':{'Proxy':'http://127.0.0.1:8080'}}},
            HOST+':8443':{'Handlers':{'/':{'Proxy':'http://127.0.0.1:9000'}}}},
        'AllowFunnel':{KEY:False},'ExistingSetting':{'preserve':True}}


def proposed(before):
    return prepare(before,hostname=HOST,expected_sha256=fingerprint(before))


def test_only_adds_the_reviewed_path_and_never_mutates_input():
    before=existing();saved=deepcopy(before);after=proposed(before)
    assert before==saved
    assert after['Web'][KEY]['Handlers'].pop(MOUNT)=={'Proxy':'http://127.0.0.1:19124'}
    assert after==before
    calls=commands()
    assert calls['add']==['tailscale','serve','--bg','--https=8453','--set-path=/mind-agents/','http://127.0.0.1:19124']
    assert calls['remove'][-1]=='off' and '--set-path=/mind-agents/' in calls['remove']
    assert not any('reset' in part or 'funnel' in part for call in calls.values() for part in call)


@pytest.mark.parametrize('conflict',['snapshot','root','tls','funnel','exact','alias','child'])
def test_conflicting_or_unreviewed_input_is_refused(conflict):
    before=existing();pin=fingerprint(before)
    handlers=before['Web'][KEY]['Handlers']
    if conflict=='snapshot':before['ExistingSetting']['later']=True
    elif conflict=='root':handlers['/']['Proxy']='http://127.0.0.1:9999'
    elif conflict=='tls':before['TCP']['8453']={'HTTPS':False}
    elif conflict=='funnel':before['AllowFunnel'][KEY]=True
    else:
        path={'exact':MOUNT,'alias':MOUNT.rstrip('/'),'child':MOUNT+'child/'}[conflict]
        handlers[path]={'Proxy':'http://127.0.0.1:9999'}
    if conflict!='snapshot':pin=fingerprint(before)
    saved=deepcopy(before)
    with pytest.raises(RouteConflict):prepare(before,hostname=HOST,expected_sha256=pin)
    assert before==saved


def test_rollback_removes_only_its_own_unchanged_route_and_retains_concurrent_updates():
    original=existing();after=proposed(original);current=deepcopy(after)
    current['Web'][KEY]['Handlers']['/later/']={'Proxy':'http://127.0.0.1:9001'}
    current['ExistingSetting']['later']=True
    restored=rollback(current,original=original,proposed=after,hostname=HOST)
    assert MOUNT in current['Web'][KEY]['Handlers'] and MOUNT not in restored['Web'][KEY]['Handlers']
    expected=deepcopy(current);del expected['Web'][KEY]['Handlers'][MOUNT]
    assert restored==expected


def test_rollback_refuses_a_later_owner_of_the_same_path():
    original=existing();after=proposed(original);current=deepcopy(after)
    current['Web'][KEY]['Handlers'][MOUNT]={'Proxy':'http://127.0.0.1:9002'}
    with pytest.raises(RouteConflict):rollback(current,original=original,proposed=after,hostname=HOST)


def test_another_listener_funnel_setting_stays_under_its_existing_owner():
    before=existing();before['AllowFunnel'][HOST+':8443']=True
    after=proposed(before)
    assert after['AllowFunnel']==before['AllowFunnel']
    assert after['AllowFunnel'][KEY] is False
