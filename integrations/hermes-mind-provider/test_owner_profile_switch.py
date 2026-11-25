"""Real Hermes config writer and provider, disposable profiles only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from test_provider import fixture,scope,ACL
from owner_profile_switch import SwitchError,prepare_switch,install_switch,rollback_switch


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def native(fixture,tmp_path):
    _,_,profiles=fixture
    profile=dict(profiles["deep"])
    profile["backup"]=profile["home"]/"custody"/tmp_path.name
    profile["backup"].mkdir()
    script=tmp_path/"private-test-backup.ps1";script.write_text(ACL,encoding="utf-8")
    command="& '"+str(script).replace("'","''")+"' -Paths @('"+str(profile["backup"]).replace("'","''")+"')"
    subprocess.run([shutil.which("pwsh"),"-NoProfile","-NonInteractive","-Command",command],
        check=True,timeout=30,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    # This helper deliberately permits only Echo. Use the other disposable home
    # for refusal tests; the working path gets a dedicated Echo-shaped review.
    path=profile["home"]/"config.yaml";original=path.read_bytes()
    review=profile["path"];review_original=review.read_bytes()
    body=deepcopy(profile["body"]);body["agent_id"]="echo"
    review.write_text(json.dumps(body),encoding="utf-8")
    raw='''# Keep Eddie's comments and credential templates.
model: {default: example-model}
mcp_servers:
  onoes-mind-mesh:
    command: existing-reader
    env: {EXISTING_SECRET: '${DO_NOT_EXPAND}'}
memory:
  memory_enabled: true
  user_profile_enabled: true
  custom_limit: 1500 # Keep this setting too.
platforms: {telegram: {enabled: true}}
'''
    path.write_text(raw,encoding="utf-8")
    with scope(profile["home"]):
        plan=prepare_switch(home=profile["home"],profile=review,profile_sha256=sha(review),expected_config_sha256=sha(path))
        try:yield profile,path,plan
        finally:path.write_bytes(original);review.write_bytes(review_original)


def test_comment_templates_and_mcp_preserved_then_rollback(native):
    profile,path,plan=native
    calls=[]
    receipt=install_switch(plan,backup_directory=profile["backup"],assert_quiescent=lambda:(calls.append("idle") is None))
    assert calls==["idle","idle"]
    assert receipt["activated"] and not receipt["gateway_reloaded"]
    assert "DO_NOT_EXPAND" not in repr(plan) and "existing-reader" not in repr(plan)
    text=path.read_text(encoding="utf-8")
    assert "# Keep Eddie's comments" in text and "# Keep this setting too." in text
    assert "${DO_NOT_EXPAND}" in text
    backup=Path(receipt["backup_path"])
    assert backup.read_bytes()==plan.original_raw
    result=rollback_switch(plan,receipt,assert_quiescent=lambda:True)
    assert result["restored"]
    from hermes_cli.config import require_readable_config_before_write
    assert require_readable_config_before_write(path)==plan.original
    assert backup.read_bytes()==plan.original_raw


def test_config_drift_refused_before_backup(native):
    profile,path,plan=native
    path.write_bytes(path.read_bytes()+b"\nnew_setting: keep\n")
    with pytest.raises(SwitchError):
        install_switch(plan,backup_directory=profile["backup"],assert_quiescent=lambda:True)
    assert b"new_setting: keep" in path.read_bytes()


def test_idle_refusal_changes_nothing(native):
    profile,path,plan=native
    def busy():raise RuntimeError("disposable active run")
    with pytest.raises(RuntimeError,match="disposable active run"):
        install_switch(plan,backup_directory=profile["backup"],assert_quiescent=busy)
    assert path.read_bytes()==plan.original_raw


def test_false_idle_observation_cannot_be_mistaken_for_permission(native):
    profile,path,plan=native
    with pytest.raises(SwitchError):
        install_switch(plan,backup_directory=profile["backup"],assert_quiescent=lambda:False)
    assert path.read_bytes()==plan.original_raw
    assert not (profile["backup"]/"hermes-config-before-private-home.yaml").exists()


def test_second_idle_check_drift_refuses_write(native):
    profile,path,plan=native;calls=[]
    def idle():
        calls.append(True)
        if len(calls)==2:path.write_bytes(path.read_bytes()+b"\nnew_setting: keep\n")
        return True
    with pytest.raises(SwitchError):
        install_switch(plan,backup_directory=profile["backup"],assert_quiescent=idle)
    assert b"new_setting: keep" in path.read_bytes()


def test_existing_backup_is_never_overwritten(native):
    profile,path,plan=native
    backup=profile["backup"]/"hermes-config-before-private-home.yaml"
    if not backup.exists():backup.write_bytes(b"preserve uncertain attempt")
    before=backup.read_bytes()
    with pytest.raises(FileExistsError):
        install_switch(plan,backup_directory=backup.parent,assert_quiescent=lambda:True)
    assert backup.read_bytes()==before and path.read_bytes()==plan.original_raw


def test_mutated_plan_refused(native):
    profile,path,plan=native
    plan.proposed["mcp_servers"]={}
    with pytest.raises(SwitchError):
        install_switch(plan,backup_directory=profile["backup"],assert_quiescent=lambda:True)
    assert path.read_bytes()==plan.original_raw


def test_wrong_profile_identity_and_stale_pin_refused(native):
    profile,path,plan=native
    with pytest.raises(SwitchError):
        prepare_switch(home=profile["home"],profile=plan.profile,profile_sha256="0"*64,expected_config_sha256=sha(path))
    body=json.loads(plan.profile.read_bytes());body["agent_id"]="deep"
    plan.profile.write_text(json.dumps(body),encoding="utf-8")
    with pytest.raises(SwitchError):
        prepare_switch(home=profile["home"],profile=plan.profile,profile_sha256=sha(plan.profile),expected_config_sha256=sha(path))


def test_other_provider_and_bad_config_refused(native):
    profile,path,plan=native
    for text,error in (('memory: {provider: other}\n',SwitchError),
                       ('[not, a, mapping]\n',RuntimeError),('memory: [broken\n',RuntimeError)):
        path.write_text(text,encoding="utf-8")
        with pytest.raises(error):
            prepare_switch(home=profile["home"],profile=plan.profile,profile_sha256=plan.profile_sha256,expected_config_sha256=sha(path))
        assert path.read_text()==text


def test_rollback_preserves_later_config_edit(native):
    profile,path,plan=native
    receipt=install_switch(plan,backup_directory=profile["backup"],assert_quiescent=lambda:True)
    path.write_bytes(path.read_bytes()+b"\nnew_setting: keep\n")
    before=path.read_bytes()
    with pytest.raises(SwitchError):rollback_switch(plan,receipt,assert_quiescent=lambda:True)
    assert path.read_bytes()==before


def test_rollback_refuses_changed_original_plan(native):
    profile,path,plan=native
    receipt=install_switch(plan,backup_directory=profile["backup"],assert_quiescent=lambda:True)
    before=path.read_bytes();plan.original["mcp_servers"]={}
    with pytest.raises(SwitchError):rollback_switch(plan,receipt,assert_quiescent=lambda:True)
    assert path.read_bytes()==before
