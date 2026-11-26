"""Native Hermes loader/manager, synthetic canonical homes and real local TLS."""
from contextlib import contextmanager
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import ssl
import sys

import pytest

MIND = Path(os.environ['MIND_SOURCE']).resolve()
HERMES = Path(os.environ['HERMES_SOURCE']).resolve()
sys.path[:0] = [str(MIND), str(MIND/'tests'), str(HERMES)]
from onoes_mind.agent_home_http import home_binding_sha256
from test_agent_context import context_store
from test_remote_home_client import tls_home
from hermes_constants import set_hermes_home_override, reset_hermes_home_override
from plugins.memory import load_memory_provider
from agent.memory_manager import MemoryManager

PLUGIN = Path(__file__).parent/'onoes_mind_provider'
pytestmark = pytest.mark.skipif(os.name != 'posix', reason='Portable provider qualification requires native POSIX storage')

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',',':'), ensure_ascii=False).encode()

@contextmanager
def scope(home):
    token = set_hermes_home_override(home)
    try:
        yield
    finally:
        reset_hermes_home_override(token)

def private(path, raw):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as stream:
        stream.write(raw)

@pytest.fixture
def profile(tls_home, tmp_path, monkeypatch):
    _, server, _, client = tls_home
    home = tmp_path/'hermes-profile'
    home.mkdir(mode=0o700)
    for name in ('custody','intents','review'):
        (home/name).mkdir(mode=0o700)
    shutil.copytree(PLUGIN, home/'plugins/onoes_mind')
    binding = home_binding_sha256(server.homes['cyony'].binding)
    token = client().credential_provider()
    private(home/'custody/home.json', canonical({'schema':'onoes-mind/posix-home-credential/v1',
        'agent_id':'cyony','binding_sha256':binding,'token':token}))
    private(home/'custody/intent.key', os.urandom(32))
    trusted = client()._tls_context.get_ca_certs(binary_form=True)
    assert len(trusted) == 1
    ca = home/'review/fixture-ca.pem'
    private(ca, ssl.DER_cert_to_PEM_cert(trusted[0]).encode())
    monkeypatch.setenv('SSL_CERT_FILE', str(ca))
    pins = {p.relative_to(MIND).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for pattern in ('*.py','*.ps1','*.mjs','migrations/*.sql') for p in (MIND/'onoes_mind').glob(pattern)}
    body = {'schema':'onoes-mind-hermes-provider/posix-v1','hermes_home':str(home),'agent_id':'cyony',
        'mind_source':str(MIND),'source_hashes':pins,'home_binding_sha256':binding,
        'credential_file':str(home/'custody/home.json'),'intent_key_file':str(home/'custody/intent.key'),
        'journal_directory':str(home/'intents'),'home_endpoint':client().base_url,
        'review_ref':'fixture:portable-provider','max_context_bytes':8192,
        'shared_project_tool':'mcp__mind__project_context'}
    path = home/'review/provider.json'
    private(path, canonical(body))
    config = {'memory':{'provider':'onoes_mind','memory_enabled':False,'user_profile_enabled':False,
        'onoes_mind':{'profile_path':str(path),'profile_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}}}
    private(home/'config.yaml', canonical(config))
    return {'home':home, 'path':path, 'body':body, 'config':config}

def loaded(profile, context='primary'):
    provider = load_memory_provider('onoes_mind', register_skills=False)
    assert provider is not None and provider.is_available()
    assert type(provider).__name__ == 'PortableOnoesMindProvider'
    manager = MemoryManager()
    manager.add_provider(provider)
    manager.initialize_all(session_id='synthetic', hermes_home=str(profile['home']), agent_context=context)
    return provider, manager

def call(manager, action, **arguments):
    return json.loads(manager.handle_tool_call('onoes_memory', {'action':action, **arguments}))

def test_real_native_loader_manager_prefetch_correct_forget_and_no_raw_ingestion(profile, tls_home):
    writer, _, _, _ = tls_home
    with scope(profile['home']):
        provider, manager = loaded(profile)
        try:
            assert manager.has_tool('onoes_memory')
            assert call(manager, 'remember', event_id='native-start', kind='profile', text='Workshop oldmarker')['ok']
            assert 'oldmarker' in manager.prefetch_all('Workshop')
            row, = call(manager,'recall',query='workshop')['result']['records']
            assert row['provenance']
            assert call(manager,'correct',event_id='native-correct',record_id=row['record_id'],
                expected_revision_id=row['revision_id'],text='Workshop newmarker')['ok']
            result = manager.prefetch_all('Workshop')
            assert 'newmarker' in result and 'oldmarker' not in result
            row, = call(manager,'recall',query='newmarker')['result']['records']
            assert call(manager,'forget',event_id='native-forget',record_id=row['record_id'],
                expected_revision_id=row['revision_id'])['ok']
            assert 'newmarker' not in manager.prefetch_all('Workshop')
            before = writer.db.total_changes
            provider.sync_turn('raw unselected conversation','unselected reply',session_id='synthetic')
            assert writer.db.total_changes == before
            assert 'mcp__mind__project_context' in provider.system_prompt_block()
        finally:
            manager.shutdown_all()

def test_native_restart_retains_exact_uncertain_intent_and_refuses_ordinary_resend(profile, tls_home):
    writer, _, proxy, _ = tls_home
    with scope(profile['home']):
        _, manager = loaded(profile)
        payload = {'event_id':'native-uncertain','text':'Privateharbor selected fact'}
        proxy['mode'] = 'disconnect_after_commit'
        assert call(manager,'remember',**payload)['code'] == 'outcome_unconfirmed'
        manager.shutdown_all()
        provider, manager = loaded(profile)
        try:
            assert call(manager,'remember',**payload)['code'] == 'reconcile_saved_intent'
            assert not call(manager,'remember',event_id='replacement',text=payload['text'])['ok']
            assert len(proxy['requests']) == 1
            pending, = call(manager,'pending')['pending']
            assert pending['attempts'] == 1 and 'payload' not in pending
            proxy['mode'] = 'normal'
            assert call(manager,'reconcile',event_id=payload['event_id'])['ok']
            assert len(proxy['requests']) == 2
            assert writer.db.execute("SELECT count(*) FROM submission_events WHERE event_id='native-uncertain'").fetchone()[0] == 1
            assert call(manager,'pending')['pending'] == []
            assert 'payload' not in provider._journal.read(payload['event_id'])
        finally:
            manager.shutdown_all()

@pytest.mark.parametrize('context',['subagent','cron','flush'])
def test_background_context_has_no_primary_memory_access(profile,tls_home,context):
    writer, _, proxy, _ = tls_home
    with scope(profile['home']):
        provider, manager = loaded(profile,context=context)
        try:
            before = writer.db.total_changes
            assert not call(manager,'remember',event_id='background',text='Not authorized')['ok']
            assert provider.prefetch('anything') == ''
            assert writer.db.total_changes == before and proxy['requests'] == []
        finally:
            manager.shutdown_all()

def test_changed_profile_and_relaxed_permissions_revoke_existing_instance(profile,tls_home):
    _, _, proxy, _ = tls_home
    with scope(profile['home']):
        provider, manager = loaded(profile)
        try:
            profile['path'].chmod(0o644)
            assert not call(manager,'recall',query='anything')['ok']
            assert proxy['requests'] == []
            profile['path'].chmod(0o600)
            profile['path'].write_bytes(profile['path'].read_bytes()+b' ')
            assert not call(manager,'recall',query='anything')['ok']
            assert proxy['requests'] == []
        finally:
            manager.shutdown_all()

@pytest.mark.parametrize('flag',['memory_enabled','user_profile_enabled'])
def test_native_fallback_flags_refuse_availability(profile,flag):
    with scope(profile['home']):
        config = profile['config']
        config['memory'][flag] = True
        (profile['home']/'config.yaml').write_bytes(canonical(config))
        provider = load_memory_provider('onoes_mind',register_skills=False)
        assert provider is None or not provider.is_available()


def test_missing_cipher_refuses_availability_without_http(profile,tls_home,monkeypatch):
    _, _, proxy, _ = tls_home
    original = importlib.import_module
    def missing(name, *args, **kwargs):
        if name == 'cryptography.hazmat.primitives.ciphers.aead':
            raise ModuleNotFoundError('synthetic missing cipher')
        return original(name, *args, **kwargs)
    with scope(profile['home']):
        monkeypatch.setattr(importlib, 'import_module', missing)
        provider = load_memory_provider('onoes_mind', register_skills=False)
        assert provider is None or not provider.is_available()
        assert proxy['requests'] == []


def test_existing_instance_cannot_follow_a_different_hermes_home(profile,tls_home,tmp_path):
    _, _, proxy, _ = tls_home
    with scope(profile['home']):
        provider, manager = loaded(profile)
        try:
            other = tmp_path/'other-home'
            other.mkdir(mode=0o700)
            with scope(other):
                assert not json.loads(provider.handle_tool_call('onoes_memory', {'action':'recall'}))['ok']
                assert 'unavailable' in provider.prefetch('anything')
                assert proxy['requests'] == []
        finally:
            manager.shutdown_all()
