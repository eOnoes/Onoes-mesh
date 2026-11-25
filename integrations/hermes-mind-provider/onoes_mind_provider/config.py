"""Owner-reviewed profile loading and isolated imports of one pinned Mind SDK."""
from dataclasses import dataclass
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

NAME = "onoes_mind"
AGENTS = frozenset({"echo", "tripp", "cyony", "nims", "deep"})


class ProfileError(ValueError):
    pass


def require(ok):
    if not ok:raise ProfileError("Onoes-Mind profile is unavailable or differs from its review")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def unique(pairs):
    result = {}
    for key,value in pairs:
        require(key not in result);result[key] = value
    return result


def selected_home():
    from hermes_constants import get_hermes_home
    return Path(get_hermes_home()).resolve(strict=True)


def local_path(value, *, directory=False):
    require(isinstance(value,str))
    path = Path(value)
    require(path.is_absolute() and ".." not in path.parts and path.resolve(strict=True) == path)
    require(path.is_dir() if directory else path.is_file())
    return path


def source_pins(root):
    package = root/"onoes_mind"
    paths = set()
    for pattern in ("*.py","*.ps1","*.mjs","migrations/*.sql"):
        paths.update(package.glob(pattern))
    require(package/"__init__.py" in paths)
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


@dataclass(frozen=True)
class ReviewedProfile:
    home: Path
    path: Path
    sha256: str
    body: dict

    def assert_current(self):
        current = load_profile(self.home)
        require(current.path == self.path and current.sha256 == self.sha256
                and current.body == self.body)
        return current


def load_profile(home=None):
    from hermes_cli.config import load_config_readonly
    home = selected_home() if home is None else Path(home).resolve(strict=True)
    require(selected_home() == home)
    config = load_config_readonly()
    memory = config.get("memory") or {}
    require(memory.get("provider") == NAME
            and memory.get("memory_enabled") is False
            and memory.get("user_profile_enabled") is False)
    reference = memory.get(NAME)
    require(isinstance(reference,dict) and set(reference) == {"profile_path","profile_sha256"})
    pin = reference["profile_sha256"]
    require(isinstance(pin,str) and re.fullmatch("[0-9a-f]{64}",pin))
    path = local_path(reference["profile_path"])
    with path.open("rb") as stream:raw = stream.read(65537)
    require(len(raw) <= 65536 and hashlib.sha256(raw).hexdigest() == pin)
    body = json.loads(raw,object_pairs_hook=unique)
    fields = {"schema","hermes_home","agent_id","mind_source","source_hashes","store_binding",
              "credential_directory","journal_directory","home_endpoint","review_ref",
              "max_context_bytes","shared_project_tool"}
    require(isinstance(body,dict) and set(body) == fields
            and body["schema"] == "onoes-mind-hermes-provider/v1"
            and isinstance(body["agent_id"],str) and body["agent_id"] in AGENTS
            and local_path(body["hermes_home"],directory=True) == home)
    root = local_path(body["mind_source"],directory=True)
    require(body["source_hashes"] == source_pins(root))
    credential = local_path(body["credential_directory"],directory=True)
    journal = local_path(body["journal_directory"],directory=True)
    require(credential != journal and isinstance(body["store_binding"],dict))
    store_directory = Path(body["store_binding"].get("database_path","")).parent
    require(store_directory.is_absolute() and not credential.is_relative_to(store_directory)
            and not journal.is_relative_to(store_directory) and not path.is_relative_to(root))
    endpoint = urlsplit(body["home_endpoint"])
    require(endpoint.scheme == "http" and endpoint.hostname == "127.0.0.1"
            and endpoint.port and 1 <= endpoint.port <= 65535
            and endpoint.path in ("","/") and not endpoint.username and not endpoint.password
            and not endpoint.query and not endpoint.fragment)
    require(type(body["max_context_bytes"]) is int and 1024 <= body["max_context_bytes"] <= 16384)
    require(isinstance(body["review_ref"],str) and 1 <= len(body["review_ref"]) <= 512
            and not re.search(r"[\x00-\x1f\x7f]",body["review_ref"]))
    shared = body["shared_project_tool"]
    require(shared is None or (isinstance(shared,str) and re.fullmatch(r"mcp__[A-Za-z0-9_]{1,120}",shared)))
    return ReviewedProfile(home,path,pin,body)


def load_sdk(profile):
    """Code-only namespace cache; each provider keeps its own identity and custody."""
    root = Path(profile.body["mind_source"])
    require(source_pins(root) == profile.body["source_hashes"])
    identity = hashlib.sha256(canonical({"root":str(root),"pins":profile.body["source_hashes"]})).hexdigest()
    namespace = "_onoes_mind_sdk_" + identity
    package = sys.modules.get(namespace)
    if package is None:
        spec = importlib.util.spec_from_file_location(namespace,root/"onoes_mind/__init__.py",
            submodule_search_locations=[str(root/"onoes_mind")])
        require(spec is not None and spec.loader is not None)
        package = importlib.util.module_from_spec(spec)
        sys.modules[namespace] = package
        try:spec.loader.exec_module(package)
        except Exception:
            for name in list(sys.modules):
                if name == namespace or name.startswith(namespace+"."):sys.modules.pop(name,None)
            raise
    return {name:importlib.import_module(namespace+"."+name)
            for name in ("agent_home","agent_home_http","recall_binding","runtime_keys","enrollment_store","ledger")}
