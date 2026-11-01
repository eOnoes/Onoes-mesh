"""Explicit static/Local8772 case dispatch; no test discovery."""

import importlib.util
import hashlib
from pathlib import Path
import sys
import time

CASE_IDS = ("C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08",
            "C09", "C10", "C11", "C12", "C13", "C14", "C15", "C16")
PLAN_SHA256 = "694d40edf4d25cda9a4f1963d3bb4db0b8786d91dfea48b2a806059862760ec1"
QUALIFICATION_SHA256 = "2e4699a33628b1e9ddca55a414f7b57bfb3f8e9c575c8bc2382d07afc536cb18"
VIOLATIONS = 0


def audit_guard(event, args):
    """Independent guard remains active even when application code catches errors."""
    global VIOLATIONS
    forbidden = event.startswith(("socket.", "subprocess.", "sqlite3.", "ctypes."))
    forbidden = forbidden or event in {
        "os.system", "os.remove", "os.rename", "os.rmdir", "os.mkdir",
        "os.truncate", "os.chmod", "os.putenv", "os.unsetenv", "os.startfile",
    }
    if event == "open":
        mode, flags = args[1], args[2]
        forbidden = forbidden or (isinstance(mode, str) and any(c in mode for c in "wax+"))
        forbidden = forbidden or (isinstance(flags, int) and bool(flags & (1 | 2 | 8 | 256 | 512 | 1024)))
        path = args[0]
        if isinstance(path, str):
            normalized = path.replace("\\", "/").casefold()
            root = str(Path(__file__).resolve().parent).replace("\\", "/").casefold() + "/"
            if normalized.startswith(root):
                relative = normalized[len(root):]
                allowed = {
                    "relay_qualification.py", "test_relay_qualification.py", "verify_relay_qualification.ps1",
                    ".verification/relay-qualification-phase-c-plan.md",
                    ".verification/relay-qualification-phase-c-plan-codex.md",
                    ".verification/relay-qualification-phase-c-implementation.md",
                    "relay-punchlist.md", "relay-gaps-result.md", "mind-integration-gate.md",
                    ".verification/relay-lifecycle-phase-a-plan.md",
                    ".verification/relay-lifecycle-phase-a-codex-implementation.md",
                    ".verification/relay-lifecycle-phase-a-receipt.md",
                    ".verification/relay-lifecycle-phase-b-plan.md",
                    ".verification/relay-lifecycle-phase-b-round5-codex.md",
                    ".verification/relay-lifecycle-phase-b-implementation.md",
                    "relay_supervisor.py", "test_relay_supervisor.py", "relay_lifecycle.py",
                    "test_relay_lifecycle.py", "server.py", "start-relay.ps1", "relay_chat.py",
                    "relay_runner.py", "relay_store.py", "relay_sqlite_worker.py",
                    "relay_decisions.py", "relay_turn_meta.py",
                }
                # importlib may check only this absent bytecode path; -B prevents writes.
                bytecode = relative.startswith("__pycache__/relay_qualification.") and relative.endswith(".pyc")
                forbidden = forbidden or (relative not in allowed and not bytecode)
            else:
                library = str(Path(sys.base_prefix).resolve()).replace("\\", "/").casefold() + "/"
                forbidden = forbidden or not normalized.startswith(library)
    if event == "exec":
        filename = args[0].co_filename.replace("\\", "/").rsplit("/", 1)[-1]
        forbidden = forbidden or filename in {
            "relay_supervisor.py", "test_relay_supervisor.py", "relay_lifecycle.py",
            "test_relay_lifecycle.py", "server.py", "relay_chat.py", "relay_runner.py",
            "relay_store.py", "relay_sqlite_worker.py", "relay_decisions.py", "relay_turn_meta.py",
        }
    if event == "import":
        name = args[0]
        forbidden = forbidden or name == "server" or name.startswith("relay_")
    if forbidden:
        VIOLATIONS += 1
        raise RuntimeError("static audit guard refused " + event)


def main():
    started = time.monotonic()
    passed = 0
    attempted = 0
    local = False
    try:
        arguments = sys.argv[1:]
        local = arguments == ["--local-8772", "--plan-sha256", PLAN_SHA256, "--max-launches", "2"]
        if not local and arguments != ["--static", "--plan-sha256", PLAN_SHA256]:
            raise RuntimeError("explicit approved static or Local8772 mode required")
        if not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode):
            raise RuntimeError("requires isolated -I -S -B")
        if not local:
            sys.addaudithook(audit_guard)
        source = Path(__file__).resolve().parent / "relay_qualification.py"
        if source.is_symlink() or source.resolve() != source.absolute():
            raise RuntimeError("qualification source path is not canonical")
        if source.stat().st_size > 131072 or hashlib.sha256(source.read_bytes()).hexdigest() != QUALIFICATION_SHA256:
            raise RuntimeError("qualification implementation hash binding")
        spec = importlib.util.spec_from_file_location("phase_c_static_only", source)
        if spec is None or spec.loader is None or spec.origin != str(source):
            raise RuntimeError("explicit new-source loader refused")
        qualification = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(qualification)
        if local:
            return qualification.local8772(arguments)
        registry = qualification.CASE_REGISTRY
        if tuple(case[0] for case in registry) != CASE_IDS or len(registry) != 16:
            raise RuntimeError("explicit registry mismatch")
        context = qualification.prepare(PLAN_SHA256)
        for case_id, label, check in registry:
            if time.monotonic() - started >= 29.0:
                raise RuntimeError("static absolute runner deadline")
            attempted += 1
            check(context)
            if VIOLATIONS:
                raise RuntimeError("guard violations cannot pass")
            passed += 1
            print(case_id + " PASS static " + label)
        print("RESULT mode=static cases=16 pass=16 fail=0 skip=0 not_run=0 violations=0")
        print("EVIDENCE declarations/AST/text/hash/in-memory-compile only; no local/native/runtime/production qualification")
        return 0
    except Exception as error:
        detail = (type(error).__name__ + ": " + str(error)).replace("\n", " ")[:1024]
        print("BLOCKED " + detail)
        print("RESULT mode=" + ("local-8772" if local else "static") + " cases=16 pass=" + str(passed) +
              " fail=1 skip=0 not_run=" + str(16 - attempted) + " violations=" + str(VIOLATIONS))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
