"""Owner-only POSIX profile switch; no enrollment, network or service control.

The caller must hold a stable maintenance window for configuration writers.
Two idle assertions detect changes; they do not create an admission/drain gate.
"""
from copy import deepcopy
from dataclasses import dataclass,field
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from owner_profile_switch import SwitchError,current_path,read_config,digest

SERVER='onoes-mind-mesh'
TOOL='mcp__onoes_mind_mesh__read_project_context'


def require(ok):
    if not ok:raise SwitchError('Portable Mind switch inputs changed or are not ready; preserve current files')


def private_document(path,pin):
    from onoes_mind.posix_home_state import _directory,_read_private
    from onoes_mind_provider.config import unique
    path=Path(path)
    require(path.is_absolute() and path.resolve(strict=True)==path)
    _,identity=_directory(path.parent)
    raw,_=_read_private(path,65536,identity)
    require(digest(raw)==pin)
    value=json.loads(raw,object_pairs_hook=unique);require(type(value) is dict)
    return value


@dataclass(frozen=True)
class PortableSwitch:
    home:Path
    home_profile:Path
    home_sha256:str
    reader_profile:Path
    reader_sha256:str
    reader_python:Path
    reader_entry:Path
    agent_id:str
    project_id:str
    principal_id:str
    original_sha256:str
    original_raw:bytes=field(repr=False)
    original:dict=field(repr=False)
    proposed:dict=field(repr=False)

    def metadata(self):
        return dict(schema='onoes-portable-memory-switch/v1',agent_id=self.agent_id,
            project_id=self.project_id,principal_id=self.principal_id,hermes_home=str(self.home),
            home_profile=str(self.home_profile),home_sha256=self.home_sha256,
            reader_profile=str(self.reader_profile),reader_sha256=self.reader_sha256,
            reader_python=str(self.reader_python),reader_entry=str(self.reader_entry),mcp_server=SERVER,shared_tool=TOOL,
            original_config_sha256=self.original_sha256,activated=False)


def proposed_settings(plan):
    expected=deepcopy(plan.original)
    memory=expected.get('memory') or {};servers=expected.get('mcp_servers') or {}
    require(type(memory) is dict and type(servers) is dict
        and memory.get('provider','') in (None,'') and 'onoes_mind' not in memory
        and memory.get('memory_enabled',True) is True and memory.get('user_profile_enabled',True) is True
        and SERVER not in servers)
    expected['memory']={**memory,'provider':'onoes_mind','memory_enabled':False,'user_profile_enabled':False,
        'onoes_mind':{'profile_path':str(plan.home_profile),'profile_sha256':plan.home_sha256}}
    expected['mcp_servers']={**servers,SERVER:{'command':str(plan.reader_python),
        'args':['-I','-B',str(plan.reader_entry),
                '--profile',str(plan.reader_profile),'--sha256',plan.reader_sha256],
        'trust':'untrusted','connect_timeout':15,'tool_timeout':15}}
    return expected


def verify_profiles(plan):
    from onoes_mind_provider.config import AGENTS,source_pins
    require(os.name=='posix' and type(plan.agent_id) is str and plan.agent_id in AGENTS
        and type(plan.principal_id) is str and type(plan.project_id) is str
        and re.fullmatch(r'context-[a-z][a-z0-9_-]{0,47}',plan.principal_id)
        and (plan.principal_id=='context-'+plan.agent_id or plan.principal_id.startswith('context-'+plan.agent_id+'-'))
        and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,95}',plan.project_id))
    h=private_document(plan.home_profile,plan.home_sha256)
    r=private_document(plan.reader_profile,plan.reader_sha256)
    require(h.get('schema')=='onoes-mind-hermes-provider/posix-v1' and h.get('agent_id')==plan.agent_id
        and Path(h.get('hermes_home',''))==plan.home and h.get('shared_project_tool')==TOOL
        and r.get('schema')=='onoes-mind/remote-project-mcp/v1' and r.get('project_id')==plan.project_id
        and r.get('principal_id')==plan.principal_id and r.get('scope_id')=='project/onoes-mind/shared'
        and h.get('mind_source')==r.get('mind_source') and h.get('home_endpoint')==r.get('endpoint'))
    url=urlsplit(h['home_endpoint'])
    require(url.scheme=='https' and url.hostname and url.hostname.endswith('.ts.net')
        and not url.username and not url.password and not url.query and not url.fragment)
    root=Path(h['mind_source']);entry=root/'scripts/remote_project_stdio.py'
    require(root.is_absolute() and root.resolve(strict=True)==root and entry.resolve(strict=True)==entry and plan.reader_entry==entry
        and h.get('source_hashes')==source_pins(root)
        and plan.home_profile.is_relative_to(plan.home) and plan.reader_profile.is_relative_to(plan.home)
        and not plan.home_profile.is_relative_to(root) and not plan.reader_profile.is_relative_to(root)
        and plan.reader_python.is_absolute() and plan.reader_python.is_relative_to(plan.home)
        and '..' not in plan.reader_python.parts and plan.reader_python.is_file())
    paths={entry,plan.reader_python.resolve(strict=True)}
    for pattern in ('*.py','*.ps1','*.mjs','migrations/*.sql'):paths.update((root/'onoes_mind').glob(pattern))
    require(r.get('source_hashes')=={str(path):digest(path.read_bytes()) for path in sorted(paths)})
    require(all(type(value) is str and re.fullmatch('[0-9a-f]{64}',value)
        for value in (h.get('home_binding_sha256'),r.get('binding_sha256')))
        and h['home_binding_sha256']!=r['binding_sha256'])


def verify_plan(plan,*,profiles=True):
    import hermes_yaml as yaml
    require(isinstance(plan,PortableSwitch) and digest(plan.original_raw)==plan.original_sha256
        and yaml.safe_load(plan.original_raw.decode('utf-8-sig'))==plan.original)
    if profiles:verify_profiles(plan)
    require(plan.proposed==proposed_settings(plan))


def prepare_switch(*,home,home_profile,home_sha256,reader_profile,reader_sha256,reader_python,
                   agent_id,project_id,principal_id,expected_config_sha256):
    require(all(type(value) is str and re.fullmatch('[0-9a-f]{64}',value)
        for value in (home_sha256,reader_sha256,expected_config_sha256)))
    home=Path(home);path=current_path(home);raw,original=read_config(path)
    require(digest(raw)==expected_config_sha256)
    reader=private_document(reader_profile,reader_sha256)
    plan=PortableSwitch(home,Path(home_profile),home_sha256,Path(reader_profile),reader_sha256,
        Path(reader_python),Path(reader['mind_source'])/'scripts/remote_project_stdio.py',
        agent_id,project_id,principal_id,expected_config_sha256,raw,deepcopy(original),{})
    verify_profiles(plan)
    from dataclasses import replace
    return replace(plan,proposed=proposed_settings(plan))


def install_switch(plan,*,backup_directory,assert_quiescent):
    from hermes_cli.config import atomic_config_write
    from onoes_mind.posix_home_state import _directory,_read_private
    verify_plan(plan);path=current_path(plan.home)
    require(callable(assert_quiescent) and assert_quiescent() is True)
    require(read_config(path)==(plan.original_raw,plan.original))
    root,identity=_directory(backup_directory);backup=root/'hermes-config-before-mind.yaml'
    require(root.is_relative_to(plan.home) and not root.is_relative_to(plan.reader_entry.parents[1]))
    descriptor=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'wb') as stream:stream.write(plan.original_raw);stream.flush();os.fsync(stream.fileno())
    saved,_=_read_private(backup,1024*1024,identity);require(saved==plan.original_raw)
    require(assert_quiescent() is True);verify_plan(plan)
    require(read_config(path)==(plan.original_raw,plan.original))
    atomic_config_write(path,deepcopy(plan.proposed))
    raw,body=read_config(path);require(body==plan.proposed)
    return {**plan.metadata(),'activated':True,'installed_config_sha256':digest(raw),'backup_path':str(backup),'gateway_reloaded':False}


def rollback_switch(plan,receipt,*,assert_quiescent):
    from hermes_cli.config import atomic_config_replace
    from onoes_mind.posix_home_state import _directory,_read_private
    # New profile files can be unavailable precisely when rollback is needed.
    # The exact installed config, plan/receipt and original backup remain required.
    verify_plan(plan,profiles=False);path=current_path(plan.home)
    require(type(receipt) is dict and all(receipt.get(k)==v for k,v in plan.metadata().items() if k!='activated')
        and receipt.get('activated') is True and callable(assert_quiescent) and assert_quiescent() is True)
    raw,body=read_config(path)
    require(digest(raw)==receipt.get('installed_config_sha256') and body==plan.proposed)
    backup=Path(receipt['backup_path'])
    require(backup.name=='hermes-config-before-mind.yaml' and backup.is_relative_to(plan.home)
        and not backup.is_relative_to(plan.reader_entry.parents[1]))
    _,identity=_directory(backup.parent)
    saved,_=_read_private(backup,1024*1024,identity);require(saved==plan.original_raw)
    require(assert_quiescent() is True and read_config(path)==(raw,body))
    atomic_config_replace(path,deepcopy(plan.original))
    restored,body=read_config(path);require(body==plan.original)
    return dict(restored=True,restored_config_sha256=digest(restored),gateway_reloaded=False)
