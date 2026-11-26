"""Finite owner switch refusal/recovery against actual Hermes config writers."""
from dataclasses import replace
import json
import os

import pytest

from test_native_shared_reader import staged_native_reader,profile,shared,tls_home,context_store,scope,canonical
from portable_owner_switch import SERVER,TOOL,SwitchError,prepare_switch,install_switch,rollback_switch,digest,read_config

pytestmark=pytest.mark.skipif(os.name!='posix',reason='Owner POSIX switch uses real private storage')


@pytest.mark.parametrize('case',['actor','project','principal','prompt-tool','home-pin','reader-pin','occupied-key','http-endpoint'])
def test_wrong_or_occupied_target_never_changes_config_or_creates_backup(staged_native_reader,case):
    f=staged_native_reader;a=dict(f['arguments']);home=f['profile']['home']
    if case=='actor':a['agent_id']='deep'
    elif case=='project':a['project_id']='other-project'
    elif case=='principal':a['principal_id']='context-deep'
    elif case=='home-pin':a['home_sha256']='0'*64
    elif case=='reader-pin':a['reader_sha256']='0'*64
    elif case=='prompt-tool':
        body=json.loads(a['home_profile'].read_bytes());body['shared_project_tool']='mcp__old__project_context'
        a['home_profile'].write_bytes(canonical(body));a['home_sha256']=digest(a['home_profile'].read_bytes())
    elif case=='occupied-key':
        import hermes_yaml as yaml
        value=yaml.safe_load((home/'config.yaml').read_text(encoding='utf-8'))
        value['mcp_servers'][SERVER]={'command':'keep-another-owner-reader'}
        (home/'config.yaml').write_bytes(canonical(value));a['expected_config_sha256']=digest((home/'config.yaml').read_bytes())
    else:
        for field,pin,endpoint in [('home_profile','home_sha256','home_endpoint'),('reader_profile','reader_sha256','endpoint')]:
            body=json.loads(a[field].read_bytes());body[endpoint]=body[endpoint].replace('https://','http://')
            a[field].write_bytes(canonical(body));a[pin]=digest(a[field].read_bytes())
    original=(home/'config.yaml').read_bytes()
    with scope(home):
        with pytest.raises(SwitchError):prepare_switch(**a)
    assert (home/'config.yaml').read_bytes()==original
    assert not list(f['backup'].iterdir())


@pytest.mark.parametrize('idle',[False,1])
def test_busy_or_non_boolean_idle_creates_no_backup(staged_native_reader,idle):
    f=staged_native_reader;home=f['profile']['home']
    with scope(home):
        plan=prepare_switch(**f['arguments'])
        with pytest.raises(SwitchError):install_switch(plan,backup_directory=f['backup'],assert_quiescent=lambda:idle)
    assert (home/'config.yaml').read_bytes()==f['original'] and not list(f['backup'].iterdir())


def test_config_drift_before_install_is_preserved(staged_native_reader):
    f=staged_native_reader;home=f['profile']['home']
    with scope(home):
        plan=prepare_switch(**f['arguments']);changed=f['original']+b'new_owner_setting: keep\n'
        (home/'config.yaml').write_bytes(changed)
        with pytest.raises(SwitchError):install_switch(plan,backup_directory=f['backup'],assert_quiescent=lambda:True)
    assert (home/'config.yaml').read_bytes()==changed and not list(f['backup'].iterdir())


def test_second_idle_check_drift_keeps_original_backup_and_new_edit(staged_native_reader):
    f=staged_native_reader;home=f['profile']['home'];calls=[];changed=f['original']+b'new_owner_setting: keep\n'
    def idle():
        calls.append(True)
        if len(calls)==2:(home/'config.yaml').write_bytes(changed)
        return True
    with scope(home):
        plan=prepare_switch(**f['arguments'])
        with pytest.raises(SwitchError):install_switch(plan,backup_directory=f['backup'],assert_quiescent=idle)
    assert calls==[True,True] and (home/'config.yaml').read_bytes()==changed
    assert (f['backup']/'hermes-config-before-mind.yaml').read_bytes()==f['original']


def test_withdrawn_profile_files_do_not_prevent_exact_config_rollback(staged_native_reader):
    f=staged_native_reader;home=f['profile']['home']
    with scope(home):
        plan=prepare_switch(**f['arguments']);receipt=install_switch(plan,backup_directory=f['backup'],assert_quiescent=lambda:True)
        plan.home_profile.unlink();plan.reader_profile.unlink()
        assert rollback_switch(plan,receipt,assert_quiescent=lambda:True)['restored']
        assert read_config(home/'config.yaml')[1]==plan.original
    for name,raw in f['native_files'].items():assert (home/name).read_bytes()==raw


def test_rollback_refuses_to_erase_another_config_writer(staged_native_reader):
    f=staged_native_reader;home=f['profile']['home']
    with scope(home):
        plan=prepare_switch(**f['arguments']);receipt=install_switch(plan,backup_directory=f['backup'],assert_quiescent=lambda:True)
        changed=(home/'config.yaml').read_bytes()+b'new_owner_setting: keep\n';(home/'config.yaml').write_bytes(changed)
        with pytest.raises(SwitchError):rollback_switch(plan,receipt,assert_quiescent=lambda:True)
    assert (home/'config.yaml').read_bytes()==changed


def test_second_install_preserves_the_original_backup(staged_native_reader):
    f=staged_native_reader;home=f['profile']['home']
    with scope(home):
        plan=prepare_switch(**f['arguments']);receipt=install_switch(plan,backup_directory=f['backup'],assert_quiescent=lambda:True)
        installed=(home/'config.yaml').read_bytes()
        with pytest.raises(SwitchError):install_switch(plan,backup_directory=f['backup'],assert_quiescent=lambda:True)
        assert (home/'config.yaml').read_bytes()==installed
        assert (f['backup']/'hermes-config-before-mind.yaml').read_bytes()==f['original']
        rollback_switch(plan,receipt,assert_quiescent=lambda:True)


def test_tampered_plan_cannot_enable_unrelated_work(staged_native_reader):
    f=staged_native_reader;home=f['profile']['home']
    with scope(home):
        plan=prepare_switch(**f['arguments']);bad=replace(plan,proposed={**plan.proposed,'automatic_workers':True})
        with pytest.raises(SwitchError):install_switch(bad,backup_directory=f['backup'],assert_quiescent=lambda:True)
    assert (home/'config.yaml').read_bytes()==f['original'] and not list(f['backup'].iterdir())


def test_native_cache_identity_tracks_the_approved_switch_and_rollback(staged_native_reader):
    from gateway.run import GatewayRunner as Cache
    f=staged_native_reader;home=f['profile']['home']
    with scope(home):
        plan=prepare_switch(**f['arguments'])
        before=Cache._extract_cache_busting_config(plan.original)
        receipt=install_switch(plan,backup_directory=f['backup'],assert_quiescent=lambda:True)
        try:
            current=read_config(home/'config.yaml')[1]
            after=Cache._extract_cache_busting_config(current)
            assert after['memory.provider']=='onoes_mind'
            assert after['memory.agent_id']=='cyony'
            assert after['memory.profile_sha256']==plan.home_sha256
            assert Cache._agent_config_signature('synthetic',{},[], '',before)!=Cache._agent_config_signature('synthetic',{},[], '',after)
        finally:rollback_switch(plan,receipt,assert_quiescent=lambda:True)
        restored=Cache._extract_cache_busting_config(read_config(home/'config.yaml')[1])
        assert {k:v for k,v in restored.items() if k.startswith('memory.')}=={k:v for k,v in before.items() if k.startswith('memory.')}
