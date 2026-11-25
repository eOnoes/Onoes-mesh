"""Finite owner-side Hermes configuration switch; never a model-facing tool.

The approved installer owns gateway quiescence and the maintenance window. This
module neither stops services nor enrolls credentials. Callers must keep other
configuration writers stopped throughout install/rollback; digest checks detect
drift, but are not a cross-process compare-and-swap lock.
"""
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
import re


class SwitchError(ValueError):
    pass


def require(ok):
    if not ok:raise SwitchError("Echo memory configuration changed or is not ready; preserve the current files")


def digest(raw):return hashlib.sha256(raw).hexdigest()


def current_path(home):
    from hermes_cli.config import get_config_path
    from hermes_constants import get_hermes_home
    home=Path(home)
    require(home.is_absolute() and home.resolve(strict=True)==home
        and Path(get_hermes_home()).resolve(strict=True)==home)
    path=home/"config.yaml"
    require(get_config_path()==path and path.is_file() and path.resolve(strict=True)==path
        and not path.is_symlink())
    return path


def read_config(path):
    # Read raw settings, never merged defaults or expanded credential templates.
    from hermes_cli.config import require_readable_config_before_write
    raw=path.read_bytes()
    require(len(raw)<=1024*1024)
    body=require_readable_config_before_write(path)
    require(isinstance(body,dict) and path.read_bytes()==raw)
    return raw,body


def verify_plan(plan):
    import hermes_yaml as yaml
    require(isinstance(plan,PreparedSwitch)
        and digest(plan.original_raw)==plan.original_sha256
        and yaml.safe_load(plan.original_raw.decode("utf-8-sig"))==plan.original)
    expected=deepcopy(plan.original)
    expected["memory"]={**expected.get("memory",{}),"provider":"onoes_mind",
        "memory_enabled":False,"user_profile_enabled":False,
        "onoes_mind":{"profile_path":str(plan.profile),"profile_sha256":plan.profile_sha256}}
    require(plan.proposed==expected)


@dataclass(frozen=True)
class PreparedSwitch:
    home:Path
    profile:Path
    profile_sha256:str
    original_sha256:str
    original_raw:bytes=field(repr=False)
    original:dict=field(repr=False)
    proposed:dict=field(repr=False)

    def metadata(self):
        return dict(schema="onoes-echo-memory-config-switch/v1",hermes_home=str(self.home),
            profile_path=str(self.profile),profile_sha256=self.profile_sha256,
            original_config_sha256=self.original_sha256,agent_id="echo",
            changed_settings=["memory.provider","memory.memory_enabled",
                "memory.user_profile_enabled","memory.onoes_mind"],activated=False)


def prepare_switch(*,home,profile,profile_sha256,expected_config_sha256):
    require(all(isinstance(value,str) and re.fullmatch("[0-9a-f]{64}",value)
        for value in (profile_sha256,expected_config_sha256)))
    path=current_path(home);raw,original=read_config(path)
    require(digest(raw)==expected_config_sha256)
    profile=Path(profile)
    require(profile.is_absolute() and profile.resolve(strict=True)==profile
        and profile.is_file() and not profile.is_symlink())
    profile_raw=profile.read_bytes()
    require(len(profile_raw)<=65536 and digest(profile_raw)==profile_sha256)
    body=json.loads(profile_raw)
    require(body.get("schema")=="onoes-mind-hermes-provider/v1"
        and body.get("agent_id")=="echo" and Path(body.get("hermes_home",""))==Path(home))
    memory=original.get("memory",{})
    require(isinstance(memory,dict) and memory.get("provider","") in (None,"")
        and "onoes_mind" not in memory
        and memory.get("memory_enabled",True) is True
        and memory.get("user_profile_enabled",True) is True)
    proposed=deepcopy(original)
    proposed["memory"]={**deepcopy(memory),"provider":"onoes_mind",
        "memory_enabled":False,"user_profile_enabled":False,
        "onoes_mind":{"profile_path":str(profile),"profile_sha256":profile_sha256}}
    return PreparedSwitch(Path(home),profile,profile_sha256,expected_config_sha256,raw,deepcopy(original),proposed)


def install_switch(plan,*,backup_directory,assert_quiescent):
    from hermes_cli.config import atomic_config_write
    from onoes_mind.enrollment_store import qualify_private_storage
    verify_plan(plan);require(callable(assert_quiescent))
    path=current_path(plan.home)
    require(assert_quiescent() is True)
    require(prepare_switch(home=plan.home,profile=plan.profile,profile_sha256=plan.profile_sha256,
        expected_config_sha256=plan.original_sha256)==plan)
    root=qualify_private_storage(backup_directory)
    backup=root/"hermes-config-before-private-home.yaml"
    # Exclusive backup first. An uncertain prior attempt is never overwritten.
    with backup.open("xb") as stream:
        stream.write(plan.original_raw);stream.flush();os.fsync(stream.fileno())
    qualify_private_storage(backup,kind="file")
    require(backup.read_bytes()==plan.original_raw)
    require(assert_quiescent() is True)
    require(read_config(path)==(plan.original_raw,plan.original)
        and digest(plan.profile.read_bytes())==plan.profile_sha256)
    # Hermes's one-document writer preserves comments, templates and all sibling
    # settings. Do not use its grouped dotted-key API (local writes are separate).
    atomic_config_write(path,deepcopy(plan.proposed))
    raw,current=read_config(path)
    require(current==plan.proposed)
    return {**plan.metadata(),"activated":True,"installed_config_sha256":digest(raw),
        "backup_path":str(backup),"gateway_reloaded":False}


def rollback_switch(plan,receipt,*,assert_quiescent):
    from hermes_cli.config import atomic_config_replace
    from onoes_mind.enrollment_store import qualify_private_storage
    verify_plan(plan)
    require(callable(assert_quiescent)
        and isinstance(receipt,dict)
        and all(receipt.get(k)==v for k,v in plan.metadata().items() if k!="activated")
        and receipt.get("activated") is True)
    path=current_path(plan.home);require(assert_quiescent() is True)
    raw,current=read_config(path)
    require(digest(raw)==receipt.get("installed_config_sha256") and current==plan.proposed)
    backup=qualify_private_storage(receipt["backup_path"],kind="file")
    require(backup.read_bytes()==plan.original_raw)
    # Deleting only the introduced provider reference is deliberate. Hermes's
    # replacement API retains comments; original raw bytes remain in the backup.
    require(assert_quiescent() is True)
    require(read_config(path)==(raw,current))
    atomic_config_replace(path,deepcopy(plan.original))
    restored,body=read_config(path);require(body==plan.original)
    return dict(restored=True,restored_config_sha256=digest(restored),
        original_settings_preserved=True,gateway_reloaded=False)
