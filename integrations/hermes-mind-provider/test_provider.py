"""Native disposable acceptance through the installed Hermes plugin/manager seams.

Run with MIND_SOURCE and HERMES_SOURCE pointing to reviewed source checkouts.
No real profile, model, native memory, or live ledger is opened.
"""
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys

import pytest

MIND = Path(os.environ["MIND_SOURCE"]).resolve()
HERMES = Path(os.environ["HERMES_SOURCE"]).resolve()
sys.path[:0] = [str(MIND),str(HERMES)]
from onoes_mind import Ledger
from onoes_mind.agent_home import AgentHome, AgentHomeBinding, WindowsAgentHomeCustody, enroll_agent_home
from onoes_mind.agent_home_http import AgentHomeServer
from onoes_mind.recall_binding import RecallBinding, prepare_store_identity, prepare_mesh_principal
from hermes_constants import set_hermes_home_override, reset_hermes_home_override
from plugins.memory import load_memory_provider
from agent.memory_manager import MemoryManager

PLUGIN = Path(__file__).parent/"onoes_mind_provider"
ACL = r'''param([string[]]$Paths)
$ErrorActionPreference='Stop'
foreach($Path in $Paths){
$acl=[Security.AccessControl.DirectorySecurity]::new()
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User
$acl.SetOwner($sid);$acl.SetAccessRuleProtection($true,$false)
foreach($identity in @($sid,[Security.Principal.SecurityIdentifier]::new('S-1-5-18'),[Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))){
$rule=[Security.AccessControl.FileSystemAccessRule]::new($identity,[Security.AccessControl.FileSystemRights]::FullControl,([Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [Security.AccessControl.InheritanceFlags]::ObjectInherit),[Security.AccessControl.PropagationFlags]::None,[Security.AccessControl.AccessControlType]::Allow)
$acl.AddAccessRule($rule)}
Set-Acl -LiteralPath $Path -AclObject $acl}
'''


def canonical(value):return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()


@contextmanager
def scope(home):
    token = set_hermes_home_override(home)
    try:yield
    finally:reset_hermes_home_override(token)


@pytest.fixture(scope="module")
def fixture(tmp_path_factory):
    root = tmp_path_factory.mktemp("native-provider").resolve()
    (root/"store").mkdir()
    database = root/"store/synthetic.sqlite"
    writer = Ledger(database,environment_id="synthetic-provider",
                    audit_key=secrets.token_bytes(32),deletion_key=secrets.token_bytes(32))
    writer.create_principal("operator");writer.issue_credential("operator","synthetic-operator")
    store_id = prepare_store_identity(writer,environment="synthetic-provider",authority_ref="fixture:owner")
    prepare_mesh_principal(writer,scope_id="project/onoes-mind/shared")
    info = database.stat()
    store = RecallBinding(str(database),store_id,"synthetic-provider","fixture:owner",
        "project/onoes-mind/shared",info.st_dev,info.st_ino,"fixture:custody","fixture:revoke","fixture:review")
    profiles = {}
    private = []
    for actor in ("nims","deep"):
        home = root/actor;home.mkdir()
        for name in ("custody","intents","review"):
            path = home/name;path.mkdir();private.append(path)
        shutil.copytree(PLUGIN,home/"plugins/onoes_mind")
        profiles[actor] = {"home":home}
    # Private ACLs apply only to disposable test directories.
    script = root/"fixture-acl.ps1"
    script.write_text(ACL,encoding="utf-8")
    command = "& '"+str(script).replace("'","''")+"' -Paths @("+",".join("'"+str(p).replace("'","''")+"'" for p in private)+")"
    subprocess.run([shutil.which("pwsh") or shutil.which("powershell"),"-NoProfile","-NonInteractive","-Command",command],
                   check=True,timeout=30,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
    homes = []
    pins = {p.relative_to(MIND).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for pattern in ("*.py","*.ps1","*.mjs","migrations/*.sql") for p in (MIND/"onoes_mind").glob(pattern)}
    for actor,profile in profiles.items():
        home = profile["home"];binding = AgentHomeBinding(store,actor)
        custody = WindowsAgentHomeCustody(home/"custody",binding)
        enroll_agent_home(writer,binding,operator_token="synthetic-operator",save_new_token=custody.save_new)
        profile.update(binding=binding,custody=custody)
        homes.append(AgentHome(writer,binding))
    server = AgentHomeServer(homes);server.start()
    for actor,profile in profiles.items():
        home = profile["home"]
        body = {"schema":"onoes-mind-hermes-provider/v1","hermes_home":str(home),"agent_id":actor,
            "mind_source":str(MIND),"source_hashes":pins,"store_binding":asdict(store),
            "credential_directory":str(home/"custody"),"journal_directory":str(home/"intents"),
            "home_endpoint":server.base_url,"review_ref":"fixture:review","max_context_bytes":8192,
            "shared_project_tool":None}
        path = home/"review/provider.json";path.write_bytes(canonical(body))
        config = {"memory":{"provider":"onoes_mind","memory_enabled":False,"user_profile_enabled":False,
            "onoes_mind":{"profile_path":str(path),"profile_sha256":hashlib.sha256(path.read_bytes()).hexdigest()}}}
        (home/"config.yaml").write_bytes(canonical(config))
        profile.update(body=body,config=config,path=path)
    try:yield writer,server,profiles
    finally:server.close();writer.close()


def loaded(profile, *, context="primary"):
    provider = load_memory_provider("onoes_mind",register_skills=False)
    if provider is not None and not provider.is_available():
        sys.modules[provider.__module__].load_profile()
    assert provider is not None and provider.is_available()
    manager = MemoryManager()
    manager.add_provider(provider)
    manager.initialize_all(session_id="fixture",hermes_home=str(profile["home"]),agent_context=context)
    return provider,manager


def call(manager,action,**kwargs):
    return json.loads(manager.handle_tool_call("onoes_memory",{"action":action,**kwargs}))


def test_real_loader_manager_selected_fact_correction_forget_and_no_transcript_ingestion(fixture):
    writer,server,profiles = fixture
    with scope(profiles["nims"]["home"]):
        provider,manager = loaded(profiles["nims"])
        assert manager.has_tool("onoes_memory")
        assert [s["name"] for s in manager.get_all_tool_schemas()] == ["onoes_memory"]
        saved = call(manager,"remember",event_id="initial",text="Lighthouse oldmarker",kind="profile")
        assert saved["ok"] and saved["receipt"]["durable"]
        context = manager.prefetch_all("lighthouse")
        assert "oldmarker" in context and provider.recall_status().count == 1
        row, = call(manager,"recall",query="lighthouse")["result"]["records"]
        assert call(manager,"correct",event_id="updated",record_id=row["record_id"],
            expected_revision_id=row["revision_id"],text="Lighthouse newmarker")["ok"]
        context = manager.prefetch_all("lighthouse")
        assert "newmarker" in context and "oldmarker" not in context
        row, = call(manager,"recall",query="lighthouse")["result"]["records"]
        assert call(manager,"forget",event_id="forgotten",record_id=row["record_id"],
            expected_revision_id=row["revision_id"])["ok"]
        assert "newmarker" not in manager.prefetch_all("lighthouse")
        before = writer.db.total_changes
        provider.sync_turn("raw transcript unselected", "agent answer unselected",session_id="fixture")
        assert writer.db.total_changes == before
        # Acknowledged intents retain receipts and hashes, never plaintext payloads.
        for path in (profiles["nims"]["home"]/"intents").glob("*.ack.dpapi"):
            value = provider._journal._read(path)
            assert "payload" not in value and "marker" not in path.read_bytes().decode(errors="ignore")
        manager.shutdown_all()


def test_distinct_profiles_do_not_share_provider_or_private_context(fixture):
    _,_,profiles = fixture
    with scope(profiles["deep"]["home"]):
        deep,dm = loaded(profiles["deep"])
        assert call(dm,"remember",event_id="deep-only",text="Deepprivate telescope")["ok"]
    with scope(profiles["nims"]["home"]):
        nims,nm = loaded(profiles["nims"])
        assert nims is not deep
        assert call(nm,"recall",query="deepprivate")["result"]["records"] == []
        assert not json.loads(deep.handle_tool_call("onoes_memory",{"action":"recall"}))["ok"]
    with scope(profiles["deep"]["home"]):dm.shutdown_all()
    with scope(profiles["nims"]["home"]):nm.shutdown_all()


def test_uncertain_commit_survives_new_instance_and_reconciles_once(fixture,monkeypatch):
    writer,server,profiles = fixture
    profile = profiles["nims"]
    handler = server._server.RequestHandlerClass;original = handler.reply
    sends = []
    def lose(self,status,value):
        if status == 200 and self.path == "/v1/home/remember":
            sends.append(True);self.close_connection=True
            self.connection.shutdown(socket.SHUT_RDWR);self.connection.close()
        else:original(self,status,value)
    with scope(profile["home"]):
        provider,manager = loaded(profile)
        monkeypatch.setattr(handler,"reply",lose)
        text = "Longprivate " + "x"*7600
        result = call(manager,"remember",event_id="lost-reply",text=text)
        assert result["code"] == "outcome_unconfirmed" and len(sends) == 1
        assert not call(manager,"remember",event_id="new-event",text="do not resend")["ok"]
        assert len(sends) == 1
        pending, = call(manager,"pending")["pending"]
        assert pending["event_id"] == "lost-reply" and "payload" not in pending
        assert all(b"Longprivate" not in p.read_bytes() for p in (profile["home"]/"intents").glob("*.dpapi"))
        manager.shutdown_all()
        monkeypatch.setattr(handler,"reply",original)
        recovered,recovered_manager = loaded(profile)
        assert recovered is not provider
        assert len(call(recovered_manager,"pending")["pending"]) == 1
        before = writer.db.total_changes
        result = call(recovered_manager,"reconcile",event_id="lost-reply")
        assert result["ok"] and writer.db.total_changes == before
        assert call(recovered_manager,"pending")["pending"] == []
        assert len(call(recovered_manager,"recall",query="Longprivate",max_bytes=16384)["result"]["records"]) == 1
        assert "payload" not in recovered._journal.read("lost-reply")
        recovered_manager.shutdown_all()


@pytest.mark.parametrize("context",["subagent","cron","flush"])
def test_background_context_cannot_write(fixture,context):
    writer,_,profiles = fixture
    with scope(profiles["nims"]["home"]):
        provider,manager = loaded(profiles["nims"],context=context)
        before = writer.db.total_changes
        assert not call(manager,"remember",event_id="background-"+context,text="not authorized")["ok"]
        assert provider.prefetch("anything") == "" and writer.db.total_changes == before
        manager.shutdown_all()


def test_credentials_are_rejected_before_journaling(fixture):
    writer,_,profiles = fixture
    with scope(profiles["nims"]["home"]):
        provider,manager = loaded(profiles["nims"])
        before = writer.db.total_changes
        # Direct provider path: Hermes itself may redact credential-like input.
        result = json.loads(provider.handle_tool_call("onoes_memory",{"action":"remember",
            "event_id":"secret-refused","text":profiles["nims"]["custody"].read()}))
        assert not result["ok"] and provider._journal.read("secret-refused") is None
        assert writer.db.total_changes == before
        manager.shutdown_all()


def test_profile_edit_revokes_existing_instance_and_native_flags_prevent_fallback(fixture):
    writer,_,profiles = fixture
    profile = profiles["nims"];config_path = profile["home"]/"config.yaml"
    original = config_path.read_bytes()
    with scope(profile["home"]):
        provider,manager = loaded(profile)
        try:
            changed = json.loads(original);changed["memory"]["memory_enabled"] = True
            config_path.write_bytes(canonical(changed))
            before = writer.db.total_changes
            assert not provider.is_available()
            assert not call(manager,"remember",event_id="native-flag",text="not written")["ok"]
            assert "unavailable" in provider.prefetch("longprivate") and writer.db.total_changes == before
        finally:config_path.write_bytes(original);manager.shutdown_all()


def test_kernel_lock_and_encrypted_segment_tampering_are_refused(fixture):
    _,_,profiles = fixture
    with scope(profiles["nims"]["home"]):
        provider,manager = loaded(profiles["nims"])
        second,other = loaded(profiles["nims"])
        with provider._journal.hold():
            assert not call(other,"remember",event_id="locked",text="not sent")["ok"]
        assert second._journal.read("locked") is None
        raw = canonical({"message":"z"*4000})
        sealed = provider._journal._sealed(raw)
        assert provider._journal._opened(sealed) == raw
        envelope = json.loads(sealed);envelope["chunks"].reverse()
        with pytest.raises(Exception):provider._journal._opened(canonical(envelope))
        manager.shutdown_all();other.shutdown_all()


def test_replay_divergent_event_and_definite_refusal_do_not_create_extra_writes(fixture):
    writer,_,profiles = fixture
    with scope(profiles["deep"]["home"]):
        provider,manager = loaded(profiles["deep"])
        first = call(manager,"remember",event_id="stable-event",text="Stable selected fact")
        assert first["ok"]
        before = writer.db.total_changes
        assert call(manager,"remember",event_id="stable-event",text="Stable selected fact") == first
        assert not call(manager,"remember",event_id="stable-event",text="Divergent replacement")["ok"]
        assert writer.db.total_changes == before
        row, = call(manager,"recall",query="Stable selected")["result"]["records"]
        refused = call(manager,"correct",event_id="stale-edit",record_id=row["record_id"],
            expected_revision_id=row["revision_id"]+1,text="Must be refused")
        assert not refused["ok"] and refused["outcome_uncertain"] is False
        assert call(manager,"pending")["pending"] == []
        assert call(manager,"remember",event_id="after-refusal",text="Separate selected fact")["ok"]
        assert provider._sdk["ledger"].Ledger is not Ledger
        manager.shutdown_all()


def test_changed_profile_pin_or_source_pins_refuse_before_writing(fixture):
    writer,_,profiles = fixture
    profile = profiles["deep"];path = profile["path"];config_path=profile["home"]/"config.yaml"
    original,config_original = path.read_bytes(),config_path.read_bytes()
    with scope(profile["home"]):
        provider,manager = loaded(profile)
        try:
            body = json.loads(original);body["review_ref"]="unreviewed-change"
            path.write_bytes(canonical(body))
            before=writer.db.total_changes
            assert not provider.is_available()
            assert not call(manager,"remember",event_id="pin-changed",text="Must not be sent")["ok"]
            body=json.loads(original)
            key=next(iter(body["source_hashes"]));body["source_hashes"][key]="0"*64
            path.write_bytes(canonical(body))
            config=json.loads(config_original)
            config["memory"]["onoes_mind"]["profile_sha256"]=hashlib.sha256(path.read_bytes()).hexdigest()
            config_path.write_bytes(canonical(config))
            assert not provider.is_available()
            assert not call(manager,"remember",event_id="source-changed",text="Must not be sent")["ok"]
            assert writer.db.total_changes == before
        finally:
            path.write_bytes(original);config_path.write_bytes(config_original);manager.shutdown_all()


@pytest.mark.parametrize("field",["agent_id","scope_id","database_path"])
def test_callers_cannot_select_another_home_or_store(fixture,field):
    writer,_,profiles=fixture
    with scope(profiles["nims"]["home"]):
        _,manager=loaded(profiles["nims"])
        before=writer.db.total_changes
        assert not call(manager,"remember",event_id="foreign-"+field,text="Must not be sent",**{field:"other"})["ok"]
        assert writer.db.total_changes == before
        manager.shutdown_all()


def test_natural_question_recall_and_current_edits_need_no_manual_keyword_search(fixture):
    _,_,profiles=fixture
    with scope(profiles["nims"]["home"]):
        provider,manager=loaded(profiles["nims"])
        try:
            saved=call(manager,"remember",event_id="natural-cover",text="GPU covers use removable armor around a black frame. Fit oldmarker.")
            assert saved["ok"]
            question="Hey Echo, what did Eddie want for the GPU covers?"
            assert "oldmarker" in manager.prefetch_all(question)
            row,=call(manager,"recall",query="gpu covers")["result"]["records"]
            assert call(manager,"correct",event_id="natural-cover-corrected",record_id=row["record_id"],
                expected_revision_id=row["revision_id"],text="GPU covers use removable armor around a black frame. Fit newmarker.")["ok"]
            context=manager.prefetch_all(question)
            assert "newmarker" in context and "oldmarker" not in context
            assert call(manager,"recall",query="covers absentword")["result"]["records"] == []
            row,=call(manager,"recall",query="covers absentword",match_mode="any")["result"]["records"]
            assert call(manager,"forget",event_id="natural-cover-forgotten",record_id=row["record_id"],
                expected_revision_id=row["revision_id"])["ok"]
            assert "newmarker" not in manager.prefetch_all(question)
            module=sys.modules[provider.__module__]
            assert module.recall_terms("Hey, can you please remind me?") == ""
            terms=module.recall_terms("GPU gpu 3D covers black armor panels clips keyed removable alpha beta gamma")
            assert len(terms.split()) == 8 and terms.split().count("gpu") == 1 and "3d" in terms.split()
            assert len(module.recall_terms(" ".join(chr(97+i)*64 for i in range(8)))) <= 512
            assert module.recall_terms("--- ---") == ""
        finally:manager.shutdown_all()


def test_imported_curated_context_comes_from_mind_after_native_files_retire(fixture):
    from onoes_mind.curated_home_import import prepare_curated_import,import_curated_home
    writer,server,profiles=fixture
    profile=profiles["nims"];native=profile["home"]/"memories";native.mkdir(exist_ok=True)
    files={"MEMORY.md":"Saved fact: removable armor stays on a black frame.",
           "USER.md":"Saved preference: concise handoff summaries."}
    for name,text in files.items():(native/name).write_text(text,encoding="utf-8")
    hashes={name:hashlib.sha256((native/name).read_bytes()).hexdigest() for name in files}
    prepared=prepare_curated_import(profile["binding"],hermes_home=profile["home"],expected_sha256=hashes)
    with server._lock:
        receipt=import_curated_home(writer,profile["binding"],operator_token="synthetic-operator",
            home_token=profile["custody"].read(),prepared=prepared)
    assert receipt["durable"]
    # Only these disposable test files move. The provider must read canonical
    # context, without any native-file fallback or second import path.
    for name in files:(native/name).rename(native/(name+".retired"))
    with scope(profile["home"]):
        for iteration in range(2):
            _,manager=loaded(profile)
            try:
                context=manager.prefetch_all("Where are we now?")
                assert all(text in context for text in files.values())
                assert "hermes-curated-bootstrap:nims:v1" in context
                assert not call(manager,"import")["ok"]
            finally:manager.shutdown_all()
        _,manager=loaded(profile)
        try:
            row,=call(manager,"recall",query="concise handoff")["result"]["records"]
            assert call(manager,"correct",event_id="curated-current-edit",record_id=row["record_id"],
                expected_revision_id=row["revision_id"],text="Current preference: clear short summaries.")["ok"]
            context=manager.prefetch_all("Where are we now?")
            assert "Current preference: clear short summaries." in context
            assert "removable armor stays on a black frame" not in context
        finally:manager.shutdown_all()


def test_unavailable_transport_never_serves_old_memory(fixture):
    _,server,profiles = fixture
    with scope(profiles["deep"]["home"]):
        provider,manager = loaded(profiles["deep"])
        assert "Deepprivate" in manager.prefetch_all("deepprivate")
        server.close()
        result = manager.prefetch_all("deepprivate")
        assert "unavailable" in result and "Deepprivate" not in result
        assert provider.recall_status() is None
        assert not call(manager,"recall",query="deepprivate")["ok"]
        manager.shutdown_all()
