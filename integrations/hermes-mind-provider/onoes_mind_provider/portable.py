"""POSIX implementation of the existing Hermes provider, inactive until enrolled."""
import hashlib
import importlib
import os
from pathlib import Path

from . import OnoesMindProvider, wire
from .config import NAME, ProfileError, load_sdk, require, selected_home
from .portable_profile import load_portable_profile


def components(profile):
    # Fail availability before selecting a writable provider if its cipher is absent.
    importlib.import_module('cryptography.hazmat.primitives.ciphers.aead')
    sdk = load_sdk(profile)
    namespace = sdk['agent_home'].__package__
    for name in ('agent_home_tool','remote_home_client','posix_home_state'):
        sdk[name] = importlib.import_module(namespace+'.'+name)
    state = sdk['posix_home_state']
    _, identity = state._directory(profile.path.parent)
    raw, _ = state._read_private(profile.path, 65536, identity)
    require(hashlib.sha256(raw).hexdigest() == profile.sha256)
    body = profile.body
    custody = state.PosixHomeCredential(body['credential_file'], agent_id=body['agent_id'],
        binding_sha256=body['home_binding_sha256'])
    client = sdk['remote_home_client'].RemoteAgentHomeClient(body['home_endpoint'],
        agent_id=body['agent_id'], binding_sha256=body['home_binding_sha256'],
        credential_provider=custody.read, timeout=3)
    journal = state.PosixIntentJournal(body['journal_directory'], key_path=body['intent_key_file'],
        agent_id=body['agent_id'], binding_sha256=body['home_binding_sha256'],
        runtime_ref='hermes-home:'+str(profile.home))
    return sdk, client, journal, identity


class PortableOnoesMindProvider(OnoesMindProvider):
    def is_available(self):
        try:
            if os.name != 'posix':
                return False
            components(load_portable_profile())
            return True
        except Exception:
            return False

    def unavailable_reason(self):
        return 'Requires an enrolled POSIX profile, verified HTTPS endpoint, private custody and encrypted intent key; native memory must be disabled.'

    def identity_signature(self):
        try:
            profile = load_portable_profile()
            return {'provider':NAME,'profile_sha256':profile.sha256,'agent_id':profile.body['agent_id']}
        except Exception:
            return {'provider':NAME,'configured':False}

    def initialize(self, session_id, **kwargs):
        home = Path(kwargs.get('hermes_home') or selected_home()).resolve(strict=True)
        if self._profile is not None and self._profile.home != home:
            raise ProfileError('a provider instance cannot be rebound to another profile')
        if kwargs.get('agent_context', 'primary') != 'primary':
            self._enabled = False
            return
        profile = load_portable_profile(home)
        sdk, client, journal, parent_identity = components(profile)
        self._profile,self._sdk,self._client,self._journal = profile,sdk,client,journal
        self._parent_identity = parent_identity
        self._session = sdk['agent_home_tool'].AgentHomeSession(client, journal=journal,
            allow_writes=True, check_current=self._guard)
        self._session_id,self._enabled = session_id,True

    def _guard(self, hermes_home=None):
        if not self._enabled or self._profile is None:
            raise ProfileError('home is not active for this caller')
        require(selected_home() == self._profile.home)
        if hermes_home is not None:
            require(Path(hermes_home).resolve(strict=True) == self._profile.home)
        self._profile.assert_current()
        raw, _ = self._sdk['posix_home_state']._read_private(self._profile.path, 65536, self._parent_identity)
        require(hashlib.sha256(raw).hexdigest() == self._profile.sha256)

    def handle_tool_call(self, tool_name, args, **kwargs):
        try:
            self._guard(kwargs.get('hermes_home'))
            require(tool_name == 'onoes_memory')
            return wire(self._session.call(args))
        except Exception:
            return wire({'ok':False,'code':'invalid_or_unavailable_profile_request'})
