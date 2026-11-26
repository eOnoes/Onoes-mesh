"""Exact owner-selected POSIX provider profile; no Windows paths or store opener."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re

from .config import AGENTS, NAME, local_path, require, selected_home, source_pins, unique


@dataclass(frozen=True)
class PortableReviewedProfile:
    home: Path
    path: Path
    sha256: str
    body: dict

    def assert_current(self):
        current = load_portable_profile(self.home)
        require(current == self)
        return current


def load_portable_profile(home=None):
    from hermes_cli.config import load_config_readonly
    require(os.name == 'posix')
    home = selected_home() if home is None else Path(home).resolve(strict=True)
    require(selected_home() == home)
    config = load_config_readonly()
    memory = config.get('memory') or {}
    require(memory.get('provider') == NAME and memory.get('memory_enabled') is False
            and memory.get('user_profile_enabled') is False)
    reference = memory.get(NAME)
    require(isinstance(reference, dict) and set(reference) == {'profile_path','profile_sha256'})
    pin = reference['profile_sha256']
    require(isinstance(pin, str) and re.fullmatch('[0-9a-f]{64}', pin))
    path = local_path(reference['profile_path'])
    with path.open('rb') as stream:
        raw = stream.read(65537)
    require(len(raw) <= 65536 and hashlib.sha256(raw).hexdigest() == pin)
    body = json.loads(raw, object_pairs_hook=unique)
    fields = {'schema','hermes_home','agent_id','mind_source','source_hashes',
              'home_binding_sha256','credential_file','intent_key_file','journal_directory',
              'home_endpoint','review_ref','max_context_bytes','shared_project_tool'}
    require(isinstance(body, dict) and set(body) == fields
            and body['schema'] == 'onoes-mind-hermes-provider/posix-v1'
            and isinstance(body['agent_id'], str) and body['agent_id'] in AGENTS
            and local_path(body['hermes_home'], directory=True) == home)
    root = local_path(body['mind_source'], directory=True)
    require(body['source_hashes'] == source_pins(root) and not path.is_relative_to(root))
    require(isinstance(body['home_binding_sha256'], str)
            and re.fullmatch('[0-9a-f]{64}', body['home_binding_sha256']))
    credential = local_path(body['credential_file'])
    key = local_path(body['intent_key_file'])
    journal = local_path(body['journal_directory'], directory=True)
    require(credential != key and not credential.is_relative_to(journal)
            and not key.is_relative_to(journal) and not journal.is_relative_to(root)
            and not credential.is_relative_to(root) and not key.is_relative_to(root))
    require(isinstance(body['home_endpoint'], str))
    require(type(body['max_context_bytes']) is int and 1024 <= body['max_context_bytes'] <= 16384)
    require(isinstance(body['review_ref'], str) and 1 <= len(body['review_ref']) <= 512
            and not re.search(r'[\x00-\x1f\x7f]', body['review_ref']))
    shared = body['shared_project_tool']
    require(shared is None or (isinstance(shared, str) and re.fullmatch(r'mcp__[A-Za-z0-9_]{1,120}', shared)))
    return PortableReviewedProfile(home, path, pin, body)
