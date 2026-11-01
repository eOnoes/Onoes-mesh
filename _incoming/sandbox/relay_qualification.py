"""Phase C qualification with separate explicit static and Local8772 modes.

The loader, custody and cleanup tables below are declarations for later review.
Checking their AST is not execution or qualification of native behavior.
"""

import ast
import hashlib
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parent
EXPECTED_ROOT = "D:/Dev/Onoes-Mesh-sandbox"
PLAN = ".verification/RELAY-QUALIFICATION-PHASE-C-PLAN.md"
AUDIT = ".verification/RELAY-QUALIFICATION-PHASE-C-PLAN-CODEX.md"
RECEIPT = ".verification/RELAY-QUALIFICATION-PHASE-C-IMPLEMENTATION.md"
PLAN_SHA256 = "694d40edf4d25cda9a4f1963d3bb4db0b8786d91dfea48b2a806059862760ec1"
AUDIT_SHA256 = "163400a5bd32e7be3312cb8afff9c8b62ea405c92d79f3a2cb8b74e30a829ed7"
BASELINE_HEAD = "3ce7b4fc929308ce5a0a998bb40ce965cf365202"
HISTORICAL_BYTES = 14157
HISTORICAL_SHA256 = "2be9a2d45f0c16f70b4e973bfa4f989c2bb927b76b70f6fe5233dffdee41d123"
OUTPUTS = ("relay_qualification.py", "test_relay_qualification.py",
           "verify_relay_qualification.ps1",
           ".verification/RELAY-QUALIFICATION-PHASE-C-IMPLEMENTATION.md")

# No step is executed. The order is itself a static review obligation.
LOADER_STEPS = (
    "install_audit_guards", "load_relay_store", "set_exact_fixture_singleton",
    "load_relay_turn_meta", "load_relay_decisions", "replace_NativeRunClient",
    "replace_key_readers", "fix_native_reason_false", "install_fail_closed_stubs",
    "install_registered_in_memory_transport", "load_relay_chat", "load_server",
    "qualification_handler_only", "load_fresh_relay_lifecycle",
    "optional_inert_supervisor_definitions_only",
)
STUBS = ("relay_media", "relay_runner", "relay_goal", "relay_proactive",
         "relay_push", "relay_sqlite_worker")
REGISTRY_INTERFACE = ("start", "snapshot", "stop", "forget", "live_count")
ROUTES = (
    ("GET", "/api/relay/health"), ("GET", "/api/relay/state"),
    ("GET", "/api/relay/rooms"), ("GET", "/api/relay/run"),
    ("GET", "/api/relay/decisions"), ("POST", "/api/relay/room"),
    ("POST", "/api/relay/send"), ("POST", "/api/relay/stop"),
    ("POST", "/api/relay/decisions"),
)
ROUTE_POLICY = (
    "exact_Host_127.0.0.1:8772", "exact_Origin_http://127.0.0.1:8772",
    "reject_unknown_route_before_effects", "reject_aliases_and_unknown_fields",
    "text_only_no_files_attachments_reply", "run_exact_synthetic_session_recorded_id",
    "state_rooms_synthetic_rows_only", "stop_decisions_exact_session_generation_owner",
    "no_history_worker_static_initialize_push_cards",
)
ARGV_PREFIX = ("absolute-python", "-I", "-S", "-B")
CHILD_ARGV = (
    "absolute-relay_qualification.py", "--child", "--port", "8772", "--host",
    "127.0.0.1", "--mesh-service", "onoes-mesh-relay", "--mesh-role", "relay",
    "--generation", "fresh-48-hex", "--fixture-root", "canonical-root",
    "--handshake", "exact-new-file", "--nonce", "fresh-64-hex",
)
ENV_ALLOWLIST = ("SystemRoot",)
LAUNCH_POLICY = (
    "explicit_local_only", "separate_hash_bound_owner_approval",
    "shell_false_list_argv_absolute_paths", "cwd_exact_disposable_root",
    "CREATE_NO_WINDOW", "retain_original_returned_handle_immediately",
    "Global_mutex_current_SID_repo_endpoint_user_only_DACL",
    "abandoned_mutex_or_unresolved_journal_refuses_no_fallback",
    "prelaunch_8772_IPv4_IPv6_occupancy_refuses_without_HTTP",
    "one_live_child_max_two_separately_approved_launches",
)
CUSTODY_BRANCHES = (
    ("missing_stale_oversize_forged_handshake", "BLOCKED_no_HTTP"),
    ("PID_creation_executable_flags_argv_cwd_data_hash_endpoint_mismatch", "BLOCKED_no_HTTP"),
    ("wildcard_IPv6_additional_absent_wrong_owner_listener", "BLOCKED_no_HTTP"),
    ("expired_evidence_or_sampling_race", "BLOCKED_resample_before_mutation"),
    ("exact_original_handle_handshake_fresh_IPv4_loopback_listener", "health_allowed"),
    ("tag_role_generation_data_root_fake_ready_zero_violations_agree", "isolated_ready_only"),
)
NATIVE_HANDLE_APIS = (
    "GetProcessId", "GetProcessTimes", "QueryFullProcessImageNameW",
    "GetExitCodeProcess", "WaitForSingleObject",
)
HANDSHAKE_POLICY = (
    "atomic_create_new_parent_private_non_reparse_directory",
    "exact_types_tokens_paths_sys_flags_immutable_launch_intent",
    "FILETIME_unsigned_64_decimal_string", "generation_nonce_hash_not_authentication",
    "never_reopen_by_PID_never_adopt", "independent_guard_violation_counter",
    "native_sampler_8772_only_no_unrelated_rows_no_network",
    "resample_before_custody_and_every_mutation",
)
CLEANUP_BRANCHES = (
    ("confirmed_exit", "check_8772_absence_no_contact_replacement"),
    ("confirmed_exit_contained_non_reparse_root", "remove_only_invocation_root"),
    ("unknown_exit", "BLOCKED_retain_handle_lease_root_journal_holder"),
    ("forced_owned_fixture_exit", "containment_only_not_graceful"),
    ("unresolved_journal", "BLOCKED_no_new_root_no_relaunch"),
    ("confirmed_exit_resolved_journal_recovery_approved", "one_new_generation_full_requalification"),
)
LIMITS = {
    "static_command": 30.0, "event_wait": 0.25, "pure_call": 0.50,
    "join": 0.25, "pipe_ack": 1.0, "listener_age": 1.0,
    "native_sample": 1.0, "startup": 5.0, "http_connect": 1.0,
    "http_read": 1.0, "http_absolute": 2.0, "response_bytes": 65536,
    "request_bytes": 4096, "pipe_bytes": 4096, "handshake_bytes": 65536,
    "terminal_poll": 5.0, "poll_reads": 10, "poll_spacing": 0.25,
    "ordinary_case": 8.0, "recovery_case": 16.0, "drain": 5.0,
    "cleanup": 6.0, "graceful_by": 2.0, "terminate_wait_by": 4.0,
    "final_wait_by": 6.0, "local_active": 150.0, "local_outer": 156.0,
    "failure_marker": 0.25, "requests": 64, "concurrent_requests": 2,
    "captured_bytes": 1048576, "argv_chars_exclusive": 4096,
    "max_launches": 2,
}
SYNTHETIC = {
    "room": "relay-eddie-echo-cphase", "foreign_room": "relay-eddie-echo-cother",
    "key": "phase-c-text-001", "text": "Phase C qualification: reply with RELAY-C-OK.",
    "output": "RELAY-C-OK.", "uncertain_key": "phase-c-uncertain-001",
    "request_id": "phase-c-request-001", "reason": "Synthetic Phase C denial",
    "description": "synthetic approval; no tool execution",
}
TEXT_POLICY = (
    "202_exact_recorded_run_session_runs_transport", "durable_exact_output_and_room_key_ownership",
    "fresh_client_state_then_run_no_history", "replay_same_run_replayed_true_creation_count_one",
    "changed_text_or_room_409_zero_new_effect", "uncertain_accepted_timeout_retains_inflight",
    "identical_uncertain_retry_409_no_second_run_no_replacement_key",
)
APPROVAL_POLICY = (
    "real_DecisionStore_event_path_fake_client_native_reason_false",
    "pending_exact_run_request", "advertised_once_or_deny_only_no_room_permanent_grants",
    "typed_reason_Relay_local_note_not_native_payload",
    "payload_request_id_choice_resolve_all_false_no_reason",
    "stale_foreign_resolved_wrong_run_request_generation_refuses",
    "sequential_and_two_concurrent_taps_forwarded_count_exactly_one",
    "durable_decision_count_at_most_one_recovery_no_resend",
    "duplicate_forwarding_finding_BLOCKED_no_production_patch",
)
ADMISSION_POLICY = (
    "validate_then_authentic_generation_token_before_store_key_metadata_backend",
    "logical_run_token_survives_202_until_observed_persisted_terminal",
    "uncertainty_retains_obligation_no_timeout_forced_release",
    "release_exact_object_once_no_reconstructed_token",
    "owned_stop_approval_continuations_only_under_child_control_lock",
    "private_inherited_pipe_generation_nonce_bound_no_HTTP_lifecycle",
    "drain_before_send_and_send_before_drain_events_outside_locks_monotonic_order",
    "after_drain_new_mutation_503_zero_effects",
    "finish_stop_refuses_live_token_pending_approval_uncertainty",
    "STOPPED_empty_admission_not_OS_exit", "first_failure_and_obligations_retained",
    "unowned_cross_room_stop_refuses_zero_effects_observed_cancelled_required",
)
HONESTY_POLICY = (
    "offline_reconnecting_completed_empty_distinct", "fake_never_claimed_native",
    "DRAINING_STOPPING_FAILED_readonly_health_nonready", "guard_violation_caught_still_failure",
    "timeout_setup_error_skip_never_pass", "absolute_deadlines_no_renewal",
    "wedged_probe_no_further_oracle_cleanup_only", "no_sleep_order_evidence",
    "fresh_generation_after_confirmed_exit_not_production_recovery",
    "static_only_no_local_native_runtime_production_claim",
)
TRANSPORT_POLICY = (
    "registered_synthetic_Request_only", "authority_127.0.0.1:8772",
    "prefix_/_qualification_backend", "in_memory_v1_runs_sessions_capability",
    "override_BASE_before_calls_disable_keys_capability_before_client_construction",
    "unknown_method_path_URL_redirect_credential_fallback_fails",
    "worker_records_and_fails_never_fake_history", "no_pumps_SSE_tools_models",
    "parent_HTTP_only_after_custody_no_DNS_proxy_redirect_fallback",
    "child_one_IPv4_loopback_bind_accept_no_outbound",
)

class StaticFailure(Exception):
    """A failed gate stops the explicit runner."""


def require(condition, message):
    if not condition:
        raise StaticFailure(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_exact(relative, maximum=2097152):
    """Read only an exact authorized input, rejecting links and oversize data."""
    require(relative in READ_ALLOWLIST, "read outside explicit manifest")
    path = ROOT / relative
    require(path.is_file() and not path.is_symlink(), "missing/link input: " + relative)
    require(path.resolve() == path.absolute(), "noncanonical input: " + relative)
    size = path.stat().st_size
    require(size <= maximum, "oversize input: " + relative)
    with path.open("rb") as stream:
        data = stream.read(maximum + 1)
    require(len(data) == size and len(data) <= maximum, "changed/oversize read: " + relative)
    return data


PROTECTED = (
    "RELAY-PUNCHLIST.md", "RELAY-GAPS-RESULT.md", "MIND-INTEGRATION-GATE.md",
    ".verification/RELAY-LIFECYCLE-PHASE-A-PLAN.md",
    ".verification/RELAY-LIFECYCLE-PHASE-A-CODEX-IMPLEMENTATION.md",
    ".verification/RELAY-LIFECYCLE-PHASE-A-RECEIPT.md",
    ".verification/RELAY-LIFECYCLE-PHASE-B-PLAN.md",
    ".verification/RELAY-LIFECYCLE-PHASE-B-ROUND5-CODEX.md",
    ".verification/RELAY-LIFECYCLE-PHASE-B-IMPLEMENTATION.md",
    "relay_supervisor.py", "test_relay_supervisor.py", "relay_lifecycle.py",
    "test_relay_lifecycle.py", "server.py", "start-relay.ps1", "relay_chat.py",
    "relay_runner.py", "relay_store.py", "relay_sqlite_worker.py",
    "relay_decisions.py", "relay_turn_meta.py",
)
READ_ALLOWLIST = PROTECTED + OUTPUTS + (PLAN, AUDIT)


def literals(tree):
    result = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    result[target.id] = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    pass
    return result


def static_surface(tree, runner=False):
    """Reject executable service/import/write surfaces, including dormant code."""
    allowed = {"ast", "hashlib", "pathlib", "re", "sys", "time"}
    if runner:
        allowed |= {"importlib.util"}
    banned_calls = {
        "eval", "exec", "__import__", "open", "getattr", "setattr",
        "write", "write_text", "write_bytes", "mkdir", "unlink", "rmdir",
        "rename", "touch", "connect", "bind", "listen", "socket",
        "urlopen", "Popen", "run", "system", "start", "discover",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            require(all(n.name in allowed for n in node.names), "nonstdlib/forbidden import")
        if isinstance(node, ast.ImportFrom):
            require(node.level == 0 and node.module in allowed, "forbidden from-import")
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else (
                node.func.attr if isinstance(node.func, ast.Attribute) else "")
            require(name not in banned_calls, "forbidden call: " + name)
            if name == "open" or (isinstance(node.func, ast.Attribute) and node.func.attr == "open"):
                require(False, "unregistered open")
    # read_exact uses Path.open('rb'); validate this single read seam separately.


def inspect_source(text, filename, runner=False):
    tree = ast.parse(text, filename=filename)
    compile(tree, filename, "exec", dont_inherit=True)
    # Native/runtime imports are dormant inside this single opt-in entry point.
    local = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name == "local8772"]
    if not runner:
        require(len(local) == 1, "exact opt-in local entry point")
        tree.body.remove(local[0])
        entry = [n for n in tree.body if isinstance(n, ast.If)]
        expected_entry = ast.parse('if __name__ == "__main__":\n'
                                   '    raise SystemExit(local8772(sys.argv[1:]))\n').body[0]
        require(len(entry) == 1 and ast.dump(entry[0]) == ast.dump(expected_entry),
                "exact guarded local script entry")
        tree.body.remove(entry[0])
        require(not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                        and n.func.id == "local8772" for n in ast.walk(tree)),
                "no unguarded local activation")
    # Remove only the exact bounded read expression before surface inspection.
    opens = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "open"]
    if not runner:
        require(len(opens) == 1, "expected one manifest read seam")
        call = opens[0]
        require(isinstance(call.func.value, ast.Name) and call.func.value.id == "path"
                and len(call.args) == 1 and ast.literal_eval(call.args[0]) == "rb"
                and not call.keywords, "read seam must be rb only")
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                     and n.name == "read_exact"]
        require(len(functions) == 1 and call in list(ast.walk(functions[0])), "read seam scope")
        call.func.attr = "manifest_read_only"
    else:
        require(not opens, "runner has no file-open seam")
    static_surface(tree, runner)
    return literals(tree)


def equal_contract(context, name, expected):
    require(context["literals"].get(name) == expected, "contract mismatch: " + name)


def text_tokens(context, *tokens):
    for token in tokens:
        require(token in context["plan"], "plan anchor missing: " + token)


def case01(context):
    require(context["approved"] == PLAN_SHA256, "approval hash mismatch")
    require(str(ROOT).replace("\\", "/").casefold() == EXPECTED_ROOT.casefold(), "repository root")
    require(digest(context["plan_bytes"]) == PLAN_SHA256, "plan hash")
    require(digest(context["audit_bytes"]) == AUDIT_SHA256, "audit hash")
    require("Verdict: APPROVE-PLAN" in context["audit"] and
            "Exact finalized plan SHA-256: " + PLAN_SHA256 in context["audit"], "audit binding")
    receipt = read_exact(RECEIPT, 262144)
    require(digest(receipt[:HISTORICAL_BYTES]) == HISTORICAL_SHA256, "historical receipt changed")
    rows = re.findall(r"(?m)^\| ([^|]+?) \| `([0-9a-f]{64})` \|\r?$", context["plan"])
    require(tuple(path.strip() for path, _ in rows) == PROTECTED, "21-file manifest identity/order")
    for path, expected in rows:
        require(digest(read_exact(path.strip())) == expected, "protected hash: " + path)
    require(len(rows) == 21, "protected count")


def case02(context):
    equal_contract(context, "LOADER_STEPS", LOADER_STEPS)
    equal_contract(context, "STUBS", STUBS)
    equal_contract(context, "REGISTRY_INTERFACE", REGISTRY_INTERFACE)
    equal_contract(context, "TRANSPORT_POLICY", TRANSPORT_POLICY)
    text_tokens(context, "Install audit guards before", "before loading chat",
                "worker stub must record and fail", "No default-store construction")
    require(LOADER_STEPS.index("install_audit_guards") == 0 and
            LOADER_STEPS.index("replace_NativeRunClient") < LOADER_STEPS.index("load_relay_chat") and
            LOADER_STEPS.index("install_registered_in_memory_transport") < LOADER_STEPS.index("load_relay_chat"),
            "guard/seam ordering")
    # Parse and compile reviewed production text without importing/executing it.
    declarations = {
        "relay_store.py": "RelayStore", "relay_turn_meta.py": "set_output",
        "relay_decisions.py": "NativeRunClient", "relay_chat.py": "history",
        "server.py": "Handler", "relay_lifecycle.py": "Lifecycle",
        "relay_supervisor.py": "Controller", "relay_runner.py": "RunRegistry",
        "relay_sqlite_worker.py": "connect_outbox",
    }
    for path, required in declarations.items():
        source = read_exact(path).decode("utf-8-sig")
        tree = ast.parse(source, filename=path)
        compile(tree, path, "exec", dont_inherit=True)
        names = {node.name for node in tree.body
                 if isinstance(node, (ast.ClassDef, ast.FunctionDef))}
        require(required in names, "reviewed seam declaration missing: " + path)
    chat = ast.parse(read_exact("relay_chat.py").decode("utf-8-sig"))
    singleton_order = [node.targets[0].id for node in chat.body
                       if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
                       and node.targets[0].id in {"STORE", "DECISIONS"}]
    require(singleton_order == ["STORE", "DECISIONS"], "reviewed import-time singleton ordering")


def case03(context):
    equal_contract(context, "LAUNCH_POLICY", LAUNCH_POLICY)
    equal_contract(context, "ARGV_PREFIX", ARGV_PREFIX)
    equal_contract(context, "CHILD_ARGV", CHILD_ARGV)
    equal_contract(context, "ENV_ALLOWLIST", ENV_ALLOWLIST)
    text_tokens(context, "If any 8772 listener exists", "No endpoint probe", "SystemRoot only")


def case04(context):
    equal_contract(context, "NATIVE_HANDLE_APIS", NATIVE_HANDLE_APIS)
    equal_contract(context, "HANDSHAKE_POLICY", HANDSHAKE_POLICY)
    equal_contract(context, "CUSTODY_BRANCHES", CUSTODY_BRANCHES)
    text_tokens(context, "original handle", "unsigned 64-bit FILETIME", "Evidence expires after 1.0")


def case05(context):
    branches = context["literals"]["CUSTODY_BRANCHES"]
    require(all(action.startswith("BLOCKED") for _, action in branches[:4]), "contradictions fail closed")
    require(branches[4][1] == "health_allowed", "health requires custody")
    text_tokens(context, "simulations", "maximum 65536 bytes", "exact types/tokens")


def case06(context):
    equal_contract(context, "ROUTES", ROUTES)
    equal_contract(context, "ROUTE_POLICY", ROUTE_POLICY)
    require(len(set(ROUTES)) == 9, "exact route count")
    text_tokens(context, "Positive routes:", "X-Mesh-Service=onoes-mesh-relay", "backend_kind=in_memory_fake")


def case07(context):
    equal_contract(context, "SYNTHETIC", SYNTHETIC)
    equal_contract(context, "TEXT_POLICY", TEXT_POLICY)
    text_tokens(context, SYNTHETIC["text"], 'Fake final output: "RELAY-C-OK."', "fresh source/module context")


def case08(context):
    require("replay_same_run_replayed_true_creation_count_one" in context["literals"]["TEXT_POLICY"] and
            "changed_text_or_room_409_zero_new_effect" in context["literals"]["TEXT_POLICY"], "replay policy")
    text_tokens(context, "replayed=true", "409 and zero new backend effect")


def case09(context):
    require("uncertain_accepted_timeout_retains_inflight" in context["literals"]["TEXT_POLICY"] and
            "identical_uncertain_retry_409_no_second_run_no_replacement_key" in context["literals"]["TEXT_POLICY"],
            "uncertainty policy")
    text_tokens(context, "Local key remains inflight", "must return 409", "blind resubmission")


def case10(context):
    equal_contract(context, "APPROVAL_POLICY", APPROVAL_POLICY)
    text_tokens(context, 'reason="Synthetic Phase C denial"', "reason_native=false", "resolve_all=false and no reason")


def case11(context):
    require("duplicate_forwarding_finding_BLOCKED_no_production_patch" in context["literals"]["APPROVAL_POLICY"],
            "duplicate-forward finding must block")
    text_tokens(context, "two bounded concurrent contenders", "actual forwarded request count", "cannot be resent after recovery")


def case12(context):
    equal_contract(context, "ADMISSION_POLICY", ADMISSION_POLICY)
    text_tokens(context, "observes terminal cancelled", "unowned or cross-room run refuses", "Response \"stopping\" is not terminal")


def case13(context):
    text_tokens(context, "before room creation, key reservation", "not merely until the 202 response",
                "Event acknowledgments outside locks", "finish_stop refuses", "exact objects only")
    require("STOPPED_empty_admission_not_OS_exit" in context["literals"]["ADMISSION_POLICY"], "STOPPED distinction")


def case14(context):
    equal_contract(context, "HONESTY_POLICY", HONESTY_POLICY)
    text_tokens(context, "completed-empty", "no readiness=true", "No skipped case", "No sleep as race-order evidence")


def case15(context):
    equal_contract(context, "CLEANUP_BRANCHES", CLEANUP_BRANCHES)
    require(context["literals"]["CLEANUP_BRANCHES"][2][1] ==
            "BLOCKED_retain_handle_lease_root_journal_holder", "unknown exit preserves custody")
    text_tokens(context, "do not kill the custody holder", "one recovery child", "confirmed exit")


def case16(context):
    equal_contract(context, "LIMITS", LIMITS)
    equal_contract(context, "OUTPUTS", OUTPUTS)
    wrapper = context["sources"]["verify_relay_qualification.ps1"]
    for token in ("'Static'", "'Local8772'", "'--local-8772'",
                  "'-I'", "'-S'", "'-B'", "'--static'", "$deadlineSeconds = 30.0",
                  "UseShellExecute = $false", "CreateNoWindow = $true",
                  ".Environment.Clear()", "1048576", "FileMode]::Append"):
        require(token in wrapper, "wrapper contract missing: " + token)
    for token in ("Start-Process", "Invoke-WebRequest", "Get-NetTCPConnection", "-EncodedCommand",
                  "Remove-Item", "Set-Content", "LocalAppData", "PYTHONPATH"):
        require(token not in wrapper, "forbidden wrapper surface: " + token)
    # Reject representative in-memory AST/text mutants, never disk mutants.
    mutants = (
        ("LOADER_STEPS", LOADER_STEPS[1:] + LOADER_STEPS[:1]),
        ("ROUTES", ROUTES + (("GET", "/api/relay/history"),)),
        ("ENV_ALLOWLIST", ENV_ALLOWLIST + ("API_SERVER_KEY",)),
        ("ARGV_PREFIX", ("absolute-python", "-I", "-S")),
        ("CLEANUP_BRANCHES", CLEANUP_BRANCHES[:2] + (("unknown_exit", "delete_root"),) + CLEANUP_BRANCHES[3:]),
        ("LIMITS", dict(LIMITS, static_command=31.0)),
    )
    for name, bad in mutants:
        changed = dict(context, literals=dict(context["literals"], **{name: bad}))
        try:
            equal_contract(changed, name, context["literals"][name])
        except StaticFailure:
            continue
        raise StaticFailure("accepted in-memory contract mutant: " + name)
    for bad in ("import socket\n", "import relay_chat\n", "exec('pass')\n", "p.write_bytes(b'x')\n"):
        try:
            static_surface(ast.parse(bad))
        except StaticFailure:
            continue
        raise StaticFailure("accepted forbidden AST mutant")
    # Final full hash recheck, still data only.
    case01(context)


CASE_REGISTRY = (
    ("C01", "input/hash/root/approval/receipt", case01),
    ("C02", "loader/guard/seam declarations", case02),
    ("C03", "occupancy/argv/environment declarations", case03),
    ("C04", "retained-handle/custody declarations", case04),
    ("C05", "handshake contradiction branches", case05),
    ("C06", "exact route/health declarations", case06),
    ("C07", "synthetic text/durable-read declarations", case07),
    ("C08", "idempotency declarations", case08),
    ("C09", "uncertainty declarations", case09),
    ("C10", "approval/reason declarations", case10),
    ("C11", "duplicate/concurrency declarations", case11),
    ("C12", "owned cancellation declarations", case12),
    ("C13", "admission/drain declarations", case13),
    ("C14", "state/evidence honesty declarations", case14),
    ("C15", "cleanup/recovery declarations", case15),
    ("C16", "bounds/wrapper/negative/hash checks", case16),
)


def prepare(approved):
    require(sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode,
            "requires -I -S -B")
    sources = {path: read_exact(path).decode("utf-8") for path in OUTPUTS[:3]}
    own = inspect_source(sources[OUTPUTS[0]], OUTPUTS[0])
    inspect_source(sources[OUTPUTS[1]], OUTPUTS[1], runner=True)
    for path, text in sources.items():
        require(text.endswith("\n"), "missing final newline: " + path)
        require(not any(line.rstrip(" \t") != line or "\t" in line
                        for line in text.splitlines()), "whitespace: " + path)
    plan = read_exact(PLAN, 65536)
    audit = read_exact(AUDIT, 65536)
    return {"approved": approved, "sources": sources, "literals": own,
            "plan_bytes": plan, "audit_bytes": audit,
            "plan": plan.decode("utf-8"), "audit": audit.decode("utf-8")}


def local8772(arguments):
    """The only runtime entry point; no native import occurs in static mode."""
    import ctypes as C
    from ctypes import wintypes as W
    import copy
    import http.client
    import http.server
    import importlib.util
    import io
    import json
    import os
    import queue
    import secrets
    import socket
    import sqlite3
    import stat
    import subprocess
    import threading
    import types
    import urllib.error
    import urllib.parse
    import urllib.request
    import uuid
    # Preload ordinary stdlib dependencies before guarding repository execution.
    import dataclasses
    import datetime
    import inspect
    import mimetypes

    require(os.name == "nt" and sys.flags.isolated and sys.flags.no_site
            and sys.dont_write_bytecode, "Local8772 requires Windows -I -S -B")
    child_mode = bool(arguments and arguments[0] == "--child")
    require(child_mode or arguments == ["--local-8772", "--plan-sha256",
                                       PLAN_SHA256, "--max-launches", "2"],
            "explicit hash-bound Local8772 invocation required")
    temp = Path("C:/Users/eMitchell109/AppData/Local/Temp")
    control = temp / "OnoesMesh-PhaseC-8772-control"
    source_hashes = {p: digest(read_exact(p)) for p in OUTPUTS[:3]}
    manifest = dict(re.findall(r"(?m)^\| ([^|]+?) \| `([0-9a-f]{64})` \|\r?$",
                              read_exact(PLAN).decode("utf-8")))
    require(len(manifest) == 21, "Local8772 protected manifest")
    require(digest(read_exact(PLAN)) == PLAN_SHA256 and
            digest(read_exact(AUDIT)) == AUDIT_SHA256, "Local8772 plan/audit hash")
    for path, expected in manifest.items():
        require(digest(read_exact(path.strip())) == expected, "protected hash: " + path)

    def canonical(path):
        path = Path(path)
        require(path.is_absolute(), "relative native path")
        for item in (path, *path.parents):
            require(not item.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT,
                    "native reparse path")
        return str(path.resolve(strict=True)).casefold()

    canonical(ROOT)
    canonical(temp)
    executable = str(Path(sys.executable).resolve(strict=True))
    canonical(executable)
    fixture = None
    allowed_files = set()
    allowed_dirs = set()
    violations = [0]
    bind_count = [0]
    library = canonical(sys.base_prefix).rstrip("\\/") + os.sep
    repo_files = {canonical(ROOT / p) for p in READ_ALLOWLIST}
    source_exec = {str(ROOT / p).casefold() for p in
                   ("relay_supervisor.py", "relay_store.py", "relay_turn_meta.py",
                    "relay_decisions.py", "relay_chat.py", "server.py", "relay_lifecycle.py")}
    launch_intent = [None]

    def policy(event, args):
        if event == "open":
            path, mode, flags = args
            if isinstance(path, int):
                return path in (0, 1, 2) or (not child_mode and launch_intent[0] is not None)
            value = os.path.abspath(os.fspath(path)).casefold()
            write = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
                isinstance(flags, int) and bool(flags & (1 | 2 | 8 | 256 | 512 | 1024)))
            return value in allowed_files if write else (
                value in allowed_files or value in repo_files or value.startswith(library))
        if event == "sqlite3.connect":
            return fixture is not None and os.path.abspath(os.fspath(args[0])).casefold() == str(
                fixture / "fixture-data/relay-state.db").casefold()
        if event.startswith("sqlite3."):
            return event == "sqlite3.connect/handle"
        if event in {"os.mkdir", "os.rmdir"}:
            return os.path.abspath(os.fspath(args[0])).casefold() in allowed_dirs
        if event == "os.remove":
            return not child_mode and os.path.abspath(os.fspath(args[0])).casefold() in allowed_files
        if event in {"os.rename", "os.chmod", "os.truncate", "os.system", "os.startfile",
                     "os.putenv", "os.unsetenv"}:
            return False
        if event == "subprocess.Popen":
            intent = launch_intent[0]
            return not child_mode and intent is not None and args == intent
        if event.startswith("subprocess."):
            return False
        if event == "socket.__new__":
            return args[1:3] == (socket.AF_INET, socket.SOCK_STREAM)
        if event == "socket.bind":
            return child_mode and bind_count[0] == 0 and args[1] == ("127.0.0.1", 8772)
        if event == "socket.connect":
            return not child_mode and args[1] == ("127.0.0.1", 8772)
        if event.startswith("socket."):
            return False
        if event == "exec":
            filename = args[0].co_filename.casefold()
            if filename.startswith(str(ROOT).casefold()):
                return filename in source_exec
        if event == "import":
            return not (args[0] == "server" or args[0].startswith("relay_"))
        if event == "ctypes.dlopen":
            return str(args[0]).casefold() in {"kernel32", "advapi32", "iphlpapi"}
        return True

    def guard(event, args):
        if not policy(event, args):
            violations[0] += 1
            raise RuntimeError("Local8772 audit guard refused " + event)
        if event == "socket.bind":
            bind_count[0] += 1

    sys.addaudithook(guard)

    def load(name, path):
        raw = read_exact(path)
        require(digest(raw) == manifest[path], "guard-bound loader source hash")
        spec = importlib.util.spec_from_file_location(name, ROOT / path)
        require(spec is not None and spec.loader is not None, "explicit loader missing")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        # Execute the hash-verified unmodified bytes, with no bytecode lookup/write.
        exec(spec.loader.source_to_code(raw, str(ROOT / path)), module.__dict__)
        return module

    supervisor = load("phase_c_native_definitions", "relay_supervisor.py")
    native = supervisor.Native()

    def sampler():
        started = time.monotonic()
        rows = []
        for family, width, port_at, address_at, pid_at, state_at in (
                (2, 24, 8, 4, 20, 0), (23, 56, 20, 0, 52, 48)):
            size = W.DWORD()
            code = native.ip.GetExtendedTcpTable(None, C.byref(size), False, family, 3, 0)
            require(code == 122 and 4 <= size.value <= 16777216,
                    "GetExtendedTcpTable size/status AF=" + str(family) + " rc=" + str(code))
            capacity = size.value
            table = C.create_string_buffer(capacity)
            code = native.ip.GetExtendedTcpTable(table, C.byref(size), False, family, 3, 0)
            require(code == 0 and size.value <= capacity,
                    "GetExtendedTcpTable data/status AF=" + str(family) + " rc=" + str(code))
            count = int.from_bytes(table.raw[:4], "little")
            require(4 + count * width <= size.value, "native table bounds")
            for i in range(count):
                offset = 4 + i * width
                if int.from_bytes(table.raw[offset + port_at:offset + port_at + 2], "big") != 8772:
                    continue
                require(int.from_bytes(table.raw[offset + state_at:offset + state_at + 4], "little") == 2,
                        "native listener state contradiction")
                address = table.raw[offset + address_at:offset + address_at + (4 if family == 2 else 16)]
                rows.append((family, address.hex(), int.from_bytes(
                    table.raw[offset + pid_at:offset + pid_at + 4], "little")))
            del table
            require(time.monotonic() - started < 1.0, "native sampling deadline")
        return rows, time.monotonic()

    def set_paths(root):
        nonlocal fixture
        require(root.parent == temp and re.fullmatch(r"OnoesMesh-PhaseC-[0-9a-f]{32}", root.name),
                "exact disposable Temp root")
        fixture = root
        for value in (root, root / "fixture-data", root / "handshake", control):
            allowed_dirs.add(str(value).casefold())
        for value in (root / "fixture-data/relay-state.db", root / "fixture-data/relay-state.db-wal",
                      root / "fixture-data/relay-state.db-shm", root / "handshake/record.json",
                      root / "control-stop", control / "custody.jsonl"):
            allowed_files.add(str(value).casefold())

    def bounded(call, seconds=0.5):
        result = queue.Queue(1)
        def probe():
            try:
                result.put((True, call()))
            except BaseException as error:
                result.put((False, error))
        thread = threading.Thread(target=probe, daemon=True)
        thread.start()
        try:
            okay, value = result.get(timeout=seconds)
        except queue.Empty:
            raise StaticFailure("bounded probe timeout; object abandoned") from None
        thread.join(0.25)
        require(not thread.is_alive(), "bounded probe join timeout")
        if not okay:
            raise value
        return value

    def child_main():
        expected_names = ["--port", "--host", "--mesh-service", "--mesh-role", "--generation",
                          "--fixture-root", "--handshake", "--nonce"]
        require(len(arguments) == 17 and arguments[1::2] == expected_names, "exact child argv")
        config = dict(zip(arguments[1::2], arguments[2::2]))
        require([config[n] for n in expected_names[:4]] ==
                ["8772", "127.0.0.1", "onoes-mesh-relay", "relay"], "child endpoint/tag/role")
        generation, nonce = config["--generation"], config["--nonce"]
        require(re.fullmatch("[0-9a-f]{48}", generation) and re.fullmatch("[0-9a-f]{64}", nonce),
                "child correlation tokens")
        root = Path(config["--fixture-root"])
        set_paths(root)
        require(canonical(root) == canonical(Path.cwd()) and
                config["--handshake"] == str(root / "handshake/record.json"), "child root/handshake")
        for path in (root, root / "fixture-data", root / "handshake"):
            native.assert_user_only(path=path)
        environment_keys = sorted(os.environ)
        require(len(environment_keys) == 1 and environment_keys[0].casefold() == "systemroot",
                "child SystemRoot-only environment")
        nonce_hash = digest(nonce.encode())

        def receive():
            raw = sys.stdin.buffer.readline(4097)
            require(0 < len(raw) <= 4096 and raw.endswith(b"\n"), "private pipe frame bound/EOF")
            frame = json.loads(raw)
            require(isinstance(frame, dict) and frame.get("generation") == generation and
                    frame.get("nonce_hash") == nonce_hash, "private pipe binding")
            return frame

        def emit(value):
            raw = json.dumps(value, separators=(",", ":")).encode() + b"\n"
            require(len(raw) <= 4096, "private acknowledgment bound")
            sys.stdout.buffer.write(raw)
            sys.stdout.buffer.flush()

        intent = receive()
        require(intent.get("command") == "intent" and intent.get("sources") == source_hashes,
                "parent immutable source intent")
        store_module = load("relay_store", "relay_store.py")
        store_module._STORE = store_module.RelayStore(root / "fixture-data/relay-state.db")
        store = store_module._STORE
        metadata = load("relay_turn_meta", "relay_turn_meta.py")
        decisions = load("relay_decisions", "relay_decisions.py")
        effect_lock = threading.RLock()
        backend_runs = {}
        forwarded = []
        created = [0]
        stops = [0]
        registered = set()
        original_request = urllib.request.Request

        def reject(detail):
            violations[0] += 1
            raise RuntimeError("synthetic boundary refused " + detail)

        class Request(original_request):
            def __init__(self, url, *args, **kwargs):
                if not isinstance(url, str) or not url.startswith(
                        "http://127.0.0.1:8772/_qualification_backend/"):
                    reject("unregistered URL")
                super().__init__(url, *args, **kwargs)
                registered.add(id(self))

        class Response:
            def __init__(self, payload, status=200):
                self.payload, self.status, self.headers = payload, status, {}
            def __enter__(self):
                return self
            def __exit__(self, *unused):
                return False
            def read(self):
                return json.dumps(self.payload).encode()

        def snapshot(run):
            with effect_lock:
                if run in backend_runs:
                    return dict(backend_runs[run])
            db = store.connect()
            try:
                row = db.execute("SELECT state FROM relay_runs WHERE run_id=?", (run,)).fetchone()
                output = metadata.local_result(store, run) if row else None
            finally:
                db.close()
            require(row is not None and row["state"] in chat.TERMINAL, "unregistered recovered fake run")
            return {"status": row["state"], "output": output or "", "error": ""}

        def transport(request, timeout=None):
            if type(request) is not Request or id(request) not in registered:
                reject("unregistered Request")
            registered.remove(id(request))
            path = request.full_url.removeprefix("http://127.0.0.1:8772/_qualification_backend")
            method = request.get_method()
            payload = json.loads(request.data) if request.data else None
            with effect_lock:
                if method == "GET" and path == "/v1/capabilities":
                    return Response({"features": {"approval_events": True, "run_approval_response": True,
                                                  "runs_idempotency": {"supported": True}}})
                if method == "POST" and path == "/v1/runs":
                    require(isinstance(payload, dict) and set(payload) ==
                            {"input", "session_id", "instructions"}, "synthetic run payload")
                    require(payload["session_id"] in (SYNTHETIC["room"], SYNTHETIC["foreign_room"]),
                            "synthetic room boundary")
                    created[0] += 1
                    run = "cphase-" + str(created[0])
                    backend_runs[run] = {"status": "running", "output": "", "error": ""}
                    if request.get_header("Idempotency-key") == SYNTHETIC["uncertain_key"]:
                        raise TimeoutError("synthetic accepted-before-ack timeout")
                    return Response({"run_id": run, "status": "running"}, 202)
                match = re.fullmatch(r"/v1/runs/([A-Za-z0-9_-]+)(/stop|/approval)?", path)
                if match:
                    run, operation = match.groups()
                    if method == "GET" and operation is None:
                        return Response(snapshot(run))
                    require(run in backend_runs, "fake control run missing")
                    if method == "POST" and operation == "/stop" and payload == {}:
                        stops[0] += 1
                        backend_runs[run].update(status="cancelled", output="")
                        return Response({"status": "cancelled"})
                    if method == "POST" and operation == "/approval":
                        require(set(payload) == {"request_id", "choice", "resolve_all"} and
                                payload["resolve_all"] is False and payload["choice"] in ("once", "deny"),
                                "fake approval payload")
                        forwarded.append({"run_id": run, **payload})
                        return Response({"resolved": 1})
                reject("unknown method/path")

        urllib.request.Request = Request
        urllib.request.urlopen = transport

        class FakeClient:
            def __init__(self, base=None, key=None):
                self.base = "http://127.0.0.1:8772/_qualification_backend"
            def _call(self, method, path, payload, timeout=1):
                request = Request(self.base + path, method=method,
                                  data=None if payload is None else json.dumps(payload).encode())
                with transport(request, timeout) as response:
                    return response.payload
            def post_approval(self, run, payload):
                return self._call("POST", "/v1/runs/" + run + "/approval", payload)

        decisions.NativeRunClient = FakeClient
        decisions.read_api_server_key = lambda: "phase-c-synthetic-placeholder"
        fixed_capability = lambda *args, **kwargs: {
            "native": False, "detail": "Synthetic capability; reason stays Relay-local", "how": "fixture"}
        decisions.reason_capability = fixed_capability
        decisions.detect_reason_support = fixed_capability
        decisions._resolve_gateway_accepts_reason = lambda: False
        decisions.BASE = "http://127.0.0.1:8772/_qualification_backend"

        class Registry:
            def __init__(self, *args, **kwargs):
                self.live = set()
            def start(self, run, room):
                self.live.add(run)
            def snapshot(self, run):
                return snapshot(run)
            def stop(self, run):
                require(run in backend_runs, "registry stop owner")
            def forget(self, run):
                self.live.discard(run)
            def live_count(self):
                return len(self.live)

        def unsupported(attribute):
            if attribute.startswith("__"):
                raise AttributeError(attribute)
            reject("unsupported stub attribute " + attribute)

        for name in STUBS:
            stub = types.ModuleType(name)
            stub.__getattr__ = unsupported
            if name == "relay_runner":
                stub.RunRegistry = Registry
            sys.modules[name] = stub
        chat = load("relay_chat", "relay_chat.py")
        chat._key = lambda: "phase-c-synthetic-placeholder"
        chat.BASE = decisions.BASE
        chat.SESSION_ID = SYNTHETIC["room"]
        server_module = load("server", "server.py")
        server_module.SERVICE_TAG, server_module.SERVICE_ROLE = "onoes-mesh-relay", "relay"
        server_module.ALLOWED_HOSTS = {"127.0.0.1:8772"}
        server_module.ALLOWED_ORIGINS = {"http://127.0.0.1:8772"}
        lifecycle_module = load("phase_c_lifecycle", "relay_lifecycle.py")
        lifecycle = lifecycle_module.Lifecycle()
        lifecycle.start(generation)
        obligations = {}
        control_lock = threading.RLock()
        operations = [0]
        for room in (SYNTHETIC["room"], SYNTHETIC["foreign_room"]):
            store.ensure_room(room)
        store.set_selected(SYNTHETIC["room"])

        def release_terminal(payload):
            run = payload.get("run_id")
            if payload.get("done") is True or payload.get("status") == "cancelled":
                store.update_run_state(run, payload["status"])
                token = obligations.pop(run, None)
                if token is not None:
                    lifecycle.release(token)

        class Handler(server_module.Handler):
            def log_message(self, *unused):
                pass
            def reply(self, status, payload, content_type="application/json; charset=utf-8"):
                self.result_status, self.result_payload = status, payload
                if self.command == "GET" and self.path == "/api/relay/health":
                    payload.update(backend_kind="in_memory_fake", qualification_only=True,
                                   generation=generation, data_root=str(root), violations=violations[0],
                                   fixture_state=lifecycle.snapshot().state,
                                   ready=lifecycle.snapshot().state == "READY")
                require(len(json.dumps(payload).encode()) <= 65536, "fixture response bound")
                super().reply(status, payload, content_type)
            def do_GET(self):
                with control_lock:
                    parsed = urllib.parse.urlsplit(self.path)
                    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
                    route = parsed.path
                    allowed_query = {"/api/relay/run": {"id", "session"},
                                     "/api/relay/decisions": {"session"}}
                    valid = (("GET", route) in ROUTES and set(query) == allowed_query.get(route, set())
                             and all(len(v) == 1 for v in query.values()) and not parsed.fragment)
                    if self.headers.get_all("Host") != ["127.0.0.1:8772"]:
                        return self.reply(403, {"error": "exact Host required"})
                    if self.headers.get("Origin") not in (None, "http://127.0.0.1:8772"):
                        return self.reply(403, {"error": "exact Origin required"})
                    if not valid:
                        return self.reply(404, {"error": "qualification route refused"})
                    if "session" in query and query["session"][0] not in (
                            SYNTHETIC["room"], SYNTHETIC["foreign_room"]):
                        return self.reply(403, {"error": "fixture scope required"})
                    if route == "/api/relay/run" and store.run_room(query["id"][0]) != query["session"][0]:
                        return self.reply(403, {"error": "run ownership required"})
                    super().do_GET()
                    if route == "/api/relay/run" and self.result_status == 200:
                        release_terminal(self.result_payload)
            def do_POST(self):
                with control_lock:
                    route = self.path
                    if self.headers.get_all("Host") != ["127.0.0.1:8772"] or self.headers.get_all(
                            "Origin") != ["http://127.0.0.1:8772"]:
                        return self.reply(403, {"error": "exact Host/Origin required"})
                    if ("POST", route) not in ROUTES:
                        return self.reply(404, {"error": "qualification route refused"})
                    if self.headers.get("Content-Type") != "application/json" or self.headers.get("Transfer-Encoding"):
                        return self.reply(415, {"error": "bounded JSON required"})
                    try:
                        length = int(self.headers.get("Content-Length", "0"))
                        require(0 < length <= 4096, "fixture request bound")
                        raw = self.rfile.read(length)
                        body = json.loads(raw)
                        fields = {"/api/relay/send": {"session_id", "text"},
                                  "/api/relay/room": {"session_id"},
                                  "/api/relay/stop": {"session_id", "generation", "run_id"},
                                  "/api/relay/decisions": {"session_id", "generation", "run_id",
                                                           "request_id", "action", "choice", "reason", "allow_reason"}}
                        require(isinstance(body, dict) and set(body) <= fields[route] and
                                body.get("session_id") in (SYNTHETIC["room"], SYNTHETIC["foreign_room"]),
                                "exact fixture payload/scope")
                        if route == "/api/relay/send":
                            require(set(body) == fields[route] and isinstance(body["text"], str) and
                                    0 < len(body["text"]) <= 1000 and
                                    re.fullmatch(r"phase-c-[a-z0-9-]{1,64}", self.headers.get("Idempotency-Key", "")),
                                    "synthetic text/key required")
                        if route in ("/api/relay/stop", "/api/relay/decisions"):
                            require(body.get("generation") == generation and
                                    store.run_room(body.get("run_id", "")) == body["session_id"] and
                                    body.get("run_id") in obligations, "owned live generation obligation required")
                            if route.endswith("decisions"):
                                require(body.get("action") == "resolve" and body.get("choice") in ("once", "deny")
                                        and type(body.get("allow_reason", False)) is bool,
                                        "bounded synthetic approval choice")
                    except (ValueError, TypeError, StaticFailure):
                        return self.reply(403, {"error": "qualification payload refused"})
                    token = None
                    if route in ("/api/relay/send", "/api/relay/room"):
                        operations[0] += 1
                        try:
                            token = lifecycle.admit_mutation(generation, "http:" + str(operations[0]))
                        except lifecycle_module.Refusal:
                            return self.reply(503, {"error": "draining", "state": lifecycle.snapshot().state})
                    self.rfile = io.BytesIO(raw)
                    super().do_POST()
                    if token is not None:
                        if self.result_status == 202 and not self.result_payload.get("replayed"):
                            obligations[self.result_payload["run_id"]] = token
                        elif self.result_status >= 500 and route.endswith("send"):
                            obligations["uncertain:" + self.headers["Idempotency-Key"]] = token
                        else:
                            lifecycle.release(token)
                    if route.endswith("stop") and self.result_status == 200:
                        release_terminal(self.result_payload)

        class Server(http.server.ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = False
            def server_bind(self):
                self.socket.bind(("127.0.0.1", 8772))
                self.server_address = ("127.0.0.1", 8772)
                self.server_name, self.server_port = "127.0.0.1", 8772
            def verify_request(self, request, client_address):
                request.settimeout(1.0)
                return client_address[0] == "127.0.0.1"

        server = Server(("127.0.0.1", 8772), Handler)
        lifecycle.mark_ready(generation)
        serving = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        serving.start()
        identity = native.identity(native.k.GetCurrentProcess())
        record = {"pid": identity.pid, "creation": identity.creation_time,
                  "executable": identity.executable, "argv": sys.argv,
                  "flags": [bool(sys.flags.isolated), bool(sys.flags.no_site), bool(sys.dont_write_bytecode)],
                  "generation": generation, "nonce_hash": nonce_hash, "root": str(root),
                  "cwd": str(Path.cwd()), "host": "127.0.0.1", "port": 8772,
                  "service": "onoes-mesh-relay", "role": "relay", "sources": source_hashes,
                  "plan": PLAN_SHA256, "guard": violations[0]}
        encoded = json.dumps(record, separators=(",", ":")).encode()
        require(len(encoded) <= 65536, "handshake size")
        with (root / "handshake/record.json").open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        emit({"ready": True, "generation": generation, "nonce_hash": nonce_hash,
              "environment_keys": environment_keys})

        def evidence():
            db = store.connect()
            try:
                counts = {table: db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] for table in
                          ("relay_rooms", "relay_runs", "relay_sent_keys", "relay_pending", "relay_decisions")}
                keys = [list(row) for row in db.execute("SELECT key,state,run_id FROM relay_sent_keys ORDER BY key")]
            finally:
                db.close()
            return {"counts": counts, "keys": keys, "selected": store.get_selected(), "created": created[0],
                    "forwarded": list(forwarded), "stops": stops[0], "violations": violations[0],
                    "state": lifecycle.snapshot()._asdict(), "obligations": sorted(obligations)}

        while True:
            frame = receive()
            command = frame.get("command")
            with control_lock:
                if command == "snapshot":
                    reply = evidence()
                elif command == "advance":
                    run = frame.get("run")
                    require(run in backend_runs and frame.get("state") in
                            {"running", "offline", "reconnecting", "completed"}, "registered fake step")
                    backend_runs[run].update(status=frame["state"], output=frame.get("output", ""))
                    reply = {"advanced": run}
                elif command == "approval":
                    run = frame["run"]
                    require(run in obligations, "approval accepted obligation")
                    card = chat.accept_approval_event({"event": "approval.request", "run_id": run,
                        "request_id": frame["request"], "choices": ["once", "deny"],
                        "description": SYNTHETIC["description"]}, session_id=SYNTHETIC["room"])
                    store.update_run_state(run, "waiting_for_approval")
                    reply = {"pending": card}
                elif command == "fresh_decisions":
                    fresh = decisions.DecisionStore(client=FakeClient(), store=store)
                    run, request = frame["run"], frame["request"]
                    pending = fresh.pending_for_run(run)
                    reply = {"pending": pending, "resolved": fresh.has_decision(run, request)}
                elif command == "drain":
                    lifecycle.begin_drain(generation)
                    reply = {"state": lifecycle.snapshot().state, "completed_at": time.monotonic()}
                elif command == "finish_live":
                    lifecycle.begin_stop(generation)
                    try:
                        lifecycle.finish_stop(generation)
                    except lifecycle_module.Refusal:
                        reply = {"refused": True, "active": lifecycle.snapshot().active}
                    else:
                        raise StaticFailure("finish_stop accepted live tokens")
                elif command == "ordered_models":
                    histories = []
                    for send_first in (False, True):
                        model = lifecycle_module.Lifecycle()
                        model.start(generation)
                        model.mark_ready(generation)
                        event = threading.Event()
                        completed = []
                        if send_first:
                            token = bounded(lambda: model.admit_mutation(generation, "ordered-send"))
                            completed.append(time.monotonic())
                            event.set()
                        else:
                            bounded(lambda: model.begin_drain(generation))
                            completed.append(time.monotonic())
                            event.set()
                        require(event.wait(0.25), "ordered acknowledgment")
                        if send_first:
                            bounded(lambda: model.begin_drain(generation))
                            completed.append(time.monotonic())
                            model.release(token)
                        else:
                            try:
                                bounded(lambda: model.admit_mutation(generation, "ordered-send"))
                            except lifecycle_module.Refusal:
                                completed.append(time.monotonic())
                            else:
                                raise StaticFailure("drain-before-send admitted")
                        require(completed[0] <= completed[1], "completed-call monotonic order")
                        histories.append({"send_first": send_first, "times": completed})
                    reply = {"synthetic_histories": histories}
                elif command == "exit":
                    lifecycle.begin_stop(generation)
                    if obligations:
                        reply = {"exit": False, "live": len(obligations)}
                    else:
                        lifecycle.finish_stop(generation)
                        emit({"exit": True, "guard": violations[0]})
                        server.shutdown()
                        server.server_close()
                        serving.join(0.25)
                        require(not serving.is_alive() and violations[0] == 0, "child exit guard/thread")
                        return 0
                else:
                    raise StaticFailure("unregistered private command")
                require(violations[0] == 0, "caught child guard violation")
                reply.update(generation=generation, nonce_hash=nonce_hash)
                emit(reply)

    def parent_main():
        start = time.monotonic()
        root = temp / ("OnoesMesh-PhaseC-" + secrets.token_hex(16))
        set_paths(root)
        journal = control / "custody.jsonl"
        holder = {"process": None, "handle": None, "identity": None,
                  "generation": None, "nonce": None, "argv": None, "custody": False,
                  "queue": None, "stderr": bytearray(), "launches": 0, "lease": None,
                  "lease_held": False, "created_root": False, "readers": ()}
        requests = [0]
        request_lock = threading.Lock()
        request_slots = threading.BoundedSemaphore(2)
        outer_cleanup = threading.Event()
        def outer_control():
            try:
                raw = os.read(sys.stdin.fileno(), 4097)
                if raw and len(raw) <= 4096:
                    frame = json.loads(raw)
                    if frame == {"command": "cleanup", "plan": PLAN_SHA256}:
                        outer_cleanup.set()
            except BaseException:
                outer_cleanup.set()
        threading.Thread(target=outer_control, daemon=True).start()
        passed, attempted = 0, 0
        run_primary, run_approval, run_states = [None], [None], [None]

        def append(event, **fields):
            record = {"event": event, "generation": holder["generation"], **fields}
            raw = json.dumps(record, separators=(",", ":")).encode() + b"\n"
            require(len(raw) <= 4096, "custody journal record bound")
            with journal.open("ab") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())

        def lease():
            name = "Global\\RelayPhaseC-" + digest((native.sid + "|" + canonical(ROOT) +
                                                    "|127.0.0.1:8772").encode())
            sd, attributes = native._security()
            try:
                handle = native.k.CreateMutexW(C.byref(attributes), False, name)
                native.check(handle)
            finally:
                native.k.LocalFree(sd)
            holder["lease"] = handle
            native.assert_user_only(handle=handle)
            wait = native.k.WaitForSingleObject(handle, 0)
            holder["lease_held"] = wait in (0, 128)
            require(wait == 0, "exclusive Global lease refused wait=" + str(wait))
            if control.exists():
                canonical(control)
                native.assert_user_only(path=control)
                require({p.name for p in control.iterdir()} <= {"custody.jsonl"}, "control contents")
                if journal.exists():
                    canonical(journal)
                    require(journal.stat().st_size <= 65536, "control journal oversized")
                    records = [json.loads(line) for line in journal.read_bytes().splitlines()]
                    unresolved = set()
                    for record in records:
                        require(isinstance(record, dict) and record.get("event") in
                                {"launch_intent", "confirmed_exit"}, "malformed custody journal")
                        generation = record.get("generation")
                        require(isinstance(generation, str) and re.fullmatch("[0-9a-f]{48}", generation),
                                "journal generation")
                        if record["event"] == "launch_intent":
                            require(generation not in unresolved, "duplicate journal launch")
                            unresolved.add(generation)
                        else:
                            require(generation in unresolved, "journal exit without launch")
                            unresolved.remove(generation)
                    require(not unresolved, "unresolved stable custody journal; no launch")
            else:
                native.private_directory(control)
            require(not root.exists(), "create-new disposable root required")
            native.private_directory(root)
            holder["created_root"] = True
            canonical(root)
            require(not canonical(root).startswith(canonical(ROOT) + os.sep), "fixture overlaps repository")
            for directory in (root / "fixture-data", root / "handshake"):
                native.private_directory(directory)

        def confirmed_exit(reason):
            handle = holder["handle"]
            require(handle is not None and native.wait(handle, 0), "child exit unknown")
            code = native.exit_code(handle)
            append("confirmed_exit", pid=holder["identity"].pid if holder["identity"] else None,
                   exit_code=code, reason=reason, custody_from_original_handle=True)
            print("NATIVE confirmed_exit generation=" + holder["generation"] + " code=" + str(code))
            holder["custody"] = False
            holder["handle"] = None
            process = holder["process"]
            process.wait(timeout=0.25)
            for reader in holder["readers"]:
                reader.join(0.25)
                require(not reader.is_alive(), "child pipe reader join timeout")
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
            holder["readers"] = ()
            holder["process"] = None
            return code

        def pipe(command, **payload):
            require(holder["process"] is not None and holder["handle"] is not None, "private pipe owner absent")
            frame = {"command": command, "generation": holder["generation"],
                     "nonce_hash": digest(holder["nonce"].encode()), **payload}
            raw = json.dumps(frame, separators=(",", ":")).encode() + b"\n"
            require(len(raw) <= 4096, "parent pipe frame bound")
            holder["process"].stdin.write(raw)
            holder["process"].stdin.flush()
            try:
                value = holder["queue"].get(timeout=1.0)
            except queue.Empty:
                raise StaticFailure("private pipe acknowledgment timeout") from None
            if isinstance(value, BaseException):
                raise value
            require(isinstance(value, dict), "private acknowledgment type")
            if command != "exit":
                require(value.get("generation") == holder["generation"] and
                        value.get("nonce_hash") == digest(holder["nonce"].encode()), "private ack identity")
            require(not holder["stderr"], "child stderr: " + holder["stderr"].decode("utf-8", "replace")[:2048])
            return value

        def validate_record(record):
            identity = native.identity(holder["handle"])
            expected = {"pid": identity.pid, "creation": identity.creation_time,
                        "executable": identity.executable, "argv": holder["argv"][4:],
                        "flags": [True, True, True], "generation": holder["generation"],
                        "nonce_hash": digest(holder["nonce"].encode()), "root": str(root),
                        "cwd": str(root), "host": "127.0.0.1", "port": 8772,
                        "service": "onoes-mesh-relay", "role": "relay", "sources": source_hashes,
                        "plan": PLAN_SHA256, "guard": 0}
            require(isinstance(record, dict) and set(record) == set(expected), "handshake exact fields")
            require(type(record["pid"]) is int and type(record["port"]) is int and
                    type(record["guard"]) is int and isinstance(record["creation"], str) and
                    re.fullmatch("[0-9]+", record["creation"]), "handshake scalar types")
            require(record == expected and all(type(v) is bool for v in record["flags"]),
                    "handshake immutable launch/native contradiction")
            require(canonical(record["executable"]) == canonical(executable) and
                    canonical(record["root"]) == canonical(root), "handshake canonical paths")

        def owned(rows, identity):
            return rows == [(2, "7f000001", identity.pid)]

        def custody():
            require(holder["handle"] is not None and not native.wait(holder["handle"], 0),
                    "custody original handle is not live")
            first = native.identity(holder["handle"])
            rows, sampled = sampler()
            second = native.identity(holder["handle"])
            require(first == second == holder["identity"] and owned(rows, first) and
                    time.monotonic() - sampled < 1.0 and not native.wait(holder["handle"], 0),
                    "fresh native 8772 owner/creation contradiction")

        def launch():
            require(holder["launches"] < 2 and holder["handle"] is None and not sampler()[0],
                    "prelaunch occupancy/custody/launch-count refusal")
            generation, nonce = secrets.token_hex(24), secrets.token_hex(32)
            argv = [executable, "-I", "-S", "-B", str(ROOT / OUTPUTS[0]), "--child",
                    "--port", "8772", "--host", "127.0.0.1", "--mesh-service", "onoes-mesh-relay",
                    "--mesh-role", "relay", "--generation", generation, "--fixture-root", str(root),
                    "--handshake", str(root / "handshake/record.json"), "--nonce", nonce]
            require(len(subprocess.list2cmdline(argv)) < 4096, "child argv bound")
            holder.update(generation=generation, nonce=nonce, argv=argv, custody=False,
                          queue=queue.Queue(), stderr=bytearray())
            append("launch_intent", argv=argv, root=str(root), sources=source_hashes, plan=PLAN_SHA256)
            env = {"SystemRoot": os.environ["SystemRoot"]}
            audit_argv = subprocess.list2cmdline(argv)
            launch_intent[0] = (executable, audit_argv, str(root), env)
            startup = time.monotonic()
            process = subprocess.Popen(argv, executable=executable, shell=False, cwd=str(root), env=env,
                                       creationflags=subprocess.CREATE_NO_WINDOW,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       bufsize=0)
            holder["process"], holder["handle"] = process, int(process._handle)
            holder["launches"] += 1
            holder["identity"] = native.identity(holder["handle"])
            require(holder["identity"].executable == canonical(executable), "original child executable")
            captured = [0]
            destination, error_output = holder["queue"], holder["stderr"]
            def read_output():
                try:
                    while True:
                        raw = process.stdout.readline(4097)
                        if not raw:
                            raise StaticFailure("child control EOF before acknowledgment")
                        captured[0] += len(raw)
                        require(len(raw) <= 4096 and captured[0] <= 1048576, "child pipe/capture bound")
                        destination.put(json.loads(raw))
                except BaseException as error:
                    destination.put(error)
            def read_error():
                while True:
                    raw = process.stderr.read(2048)
                    if not raw:
                        return
                    error_output.extend(raw)
                    if len(error_output) > 1048576:
                        destination.put(StaticFailure("child stderr capture bound"))
                        return
            readers = (threading.Thread(target=read_output, daemon=True),
                       threading.Thread(target=read_error, daemon=True))
            holder["readers"] = readers
            for reader in readers:
                reader.start()
            reply = pipe("intent", sources=source_hashes)
            environment_keys = reply.get("environment_keys")
            require(reply.get("ready") is True and isinstance(environment_keys, list) and
                    len(environment_keys) == 1 and isinstance(environment_keys[0], str) and
                    environment_keys[0].casefold() == "systemroot", "child startup acknowledgment/environment")
            print("NATIVE child_environment_keys=" + json.dumps(environment_keys))
            handshake = root / "handshake/record.json"
            canonical(handshake)
            require(0 < handshake.stat().st_size <= 65536, "fresh handshake size")
            record = json.loads(handshake.read_bytes())
            validate_record(record)
            custody()
            require(time.monotonic() - startup < 5.0, "per-generation startup deadline")
            holder["custody"] = True
            print("NATIVE retained_handle pid=" + str(holder["identity"].pid) +
                  " creation_FILETIME=" + holder["identity"].creation_time +
                  " executable=" + holder["identity"].executable + " generation=" + generation)

        class Connection(http.client.HTTPConnection):
            def connect(self):
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(1.0)
                self.sock.connect(("127.0.0.1", 8772))

        def request_http(method, path, body=None, key=None, extra=None):
            require(holder["custody"], "no HTTP before custody")
            if method == "POST":
                custody()
            with request_lock:
                requests[0] += 1
                require(requests[0] <= 64, "qualification HTTP request count")
            require(request_slots.acquire(timeout=0.25), "HTTP concurrency bound")
            started = time.monotonic()
            connection = Connection("127.0.0.1", 8772, timeout=1.0)
            try:
                headers = {"Host": "127.0.0.1:8772", "Origin": "http://127.0.0.1:8772"}
                raw = None
                if body is not None:
                    raw = json.dumps(body).encode()
                    require(len(raw) <= 4096, "parent request body bound")
                    headers["Content-Type"] = "application/json"
                if key:
                    headers["Idempotency-Key"] = key
                headers.update(extra or {})
                connection.request(method, path, raw, headers)
                response = connection.getresponse()
                data = response.read(65537)
                require(len(data) <= 65536 and time.monotonic() - started < 2.0, "HTTP response/deadline")
                return response.status, json.loads(data), dict(response.getheaders())
            finally:
                connection.close()
                request_slots.release()

        def send(key, text=None, room=None):
            return request_http("POST", "/api/relay/send", {"session_id": room or SYNTHETIC["room"],
                                "text": text or SYNTHETIC["text"]}, key)

        def poll(run):
            return request_http("GET", "/api/relay/run?id=" + run + "&session=" + SYNTHETIC["room"])

        def control_body(run, **fields):
            return {"run_id": run, "session_id": SYNTHETIC["room"],
                    "generation": holder["generation"], **fields}

        def check_http(result, expected):
            require(result[0] == expected, "HTTP expected " + str(expected) + " got " + str(result[:2]))
            return result[1]

        def equal_effects(before, after):
            require(all(before[k] == after[k] for k in
                        ("counts", "keys", "selected", "created", "forwarded", "stops")),
                    "refused request produced durable/backend effects")

        def cleanup(reason, remove):
            deadline = time.monotonic() + 6.0
            if holder["handle"] is not None:
                if not native.wait(holder["handle"], 0):
                    try:
                        pipe("exit")
                    except BaseException:
                        pass
                    remaining = min(2.0, max(0, deadline - time.monotonic() - 4.0))
                    if not native.wait(holder["handle"], remaining):
                        native.check(native.k.TerminateProcess(holder["handle"], 94))
                        require(native.wait(holder["handle"], max(0, deadline - time.monotonic() - 2.0)) or
                                native.wait(holder["handle"], max(0, deadline - time.monotonic())),
                                "unknown exit: retain custody holder/root/journal")
                        print("NATIVE forced fixture containment; no graceful drain assertion")
                confirmed_exit(reason)
            require(not sampler()[0], "post-exit 8772 listener remains; no replacement contact")
            if remove and holder["created_root"]:
                canonical(root)
                require(root.parent == temp and canonical(root).startswith(canonical(temp) + os.sep),
                        "cleanup containment")
                files = []
                directories = []
                for directory, dirnames, filenames in os.walk(root):
                    path = Path(directory)
                    canonical(path)
                    require(str(path).casefold() in allowed_dirs, "unexpected fixture directory")
                    directories.append(path)
                    for name in dirnames:
                        require(str(path / name).casefold() in allowed_dirs, "unexpected fixture subdirectory")
                        canonical(path / name)
                    for name in filenames:
                        file = path / name
                        canonical(file)
                        require(str(file).casefold() in allowed_files, "unexpected fixture file")
                        files.append(file)
                print("NATIVE exact_fixture_inventory=" + json.dumps(sorted(str(p.relative_to(root)) for p in files)))
                for file in files:
                    os.remove(file)
                for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
                    os.rmdir(directory)
                require(not root.exists(), "owned root cleanup unknown")
                print("NATIVE cleanup root=" + str(root) + " confirmed_absent; stable_control_preserved=" + str(journal))
                holder["created_root"] = False
            require(time.monotonic() <= deadline, "cleanup six-second deadline")

        def c01():
            context = prepare(PLAN_SHA256)
            case01(context)
            bad = dict(context, approved="0" * 64)
            try:
                case01(bad)
            except StaticFailure:
                pass
            else:
                raise StaticFailure("wrong approval candidate accepted")

        def c02():
            for event, args in (("socket.connect", (None, ("127.0.0.1", 8642))),
                                ("socket.getaddrinfo", ("invalid", 8772, 0, 0, 0)),
                                ("sqlite3.connect", (str(ROOT / "data/forbidden.db"),)),
                                ("open", (str(ROOT / "data/forbidden"), "rb", 0)),
                                ("subprocess.Popen", ("unregistered", [], str(root), {})),
                                ("import", ("relay_sqlite_worker",))):
                require(policy(event, args) is False, "guard candidate accepted: " + event)
            require(violations[0] == 0, "guard candidate unexpectedly executed")

        def c03():
            require(not sampler()[0], "native occupied 8772 preflight; no launch/adoption/HTTP")
            identity = native.identity(native.k.GetCurrentProcess())
            for rows in ([(2, "00000000", identity.pid)], [(23, "00" * 16, identity.pid)],
                         [(2, "7f000001", identity.pid + 1)], [],
                         [(2, "7f000001", identity.pid)] * 2):
                require(not owned(rows, identity), "synthetic occupancy candidate accepted")

        def c04():
            launch()
            custody()

        def c05():
            record = json.loads((root / "handshake/record.json").read_bytes())
            mutants = [None, {}, dict(record, pid=record["pid"] + 1),
                       dict(record, creation="0"), dict(record, generation="0" * 48),
                       dict(record, nonce_hash="0" * 64), dict(record, executable="unregistered"),
                       dict(record, argv=record["argv"] + ["extra"]), dict(record, flags=[1, True, True])]
            for mutant in mutants:
                try:
                    validate_record(mutant)
                except (StaticFailure, KeyError, TypeError):
                    continue
                raise StaticFailure("forged handshake candidate accepted")
            require(len(b"x" * 65537) > 65536, "oversize simulated record refused")
            require(not (time.monotonic() - (time.monotonic() - 1.01) < 1.0), "stale simulated evidence")
            require(holder["custody"] and holder["handle"] is not None, "unknown-exit simulation retains holder")

        def c06():
            before = pipe("snapshot")
            status, health, headers = request_http("GET", "/api/relay/health")
            require(status == 200 and headers.get("X-Mesh-Service") == "onoes-mesh-relay" and
                    headers.get("X-Mesh-Role") == "relay" and health.get("service") == "relay" and
                    health.get("service_tag") == "onoes-mesh-relay" and health.get("service_role") == "relay" and
                    health.get("backend_kind") == "in_memory_fake" and health.get("qualification_only") is True and
                    health.get("generation") == holder["generation"] and health.get("data_root") == str(root) and
                    health.get("fixture_state") == "READY" and health.get("ready") is True and
                    health.get("violations") == 0, "exact tagged synthetic health")
            for path in ("/api/relay/history", "/api/relay/health?alias=1", "/"):
                check_http(request_http("GET", path), 404)
            check_http(request_http("GET", "/api/relay/health", extra={"Host": "wrong"}), 403)
            check_http(request_http("GET", "/api/relay/health", extra={"Origin": "http://wrong"}), 403)
            check_http(request_http("POST", "/api/relay/send", {"session_id": SYNTHETIC["room"],
                                "text": "synthetic", "files": []}, "phase-c-forbidden-001"), 403)
            equal_effects(before, pipe("snapshot"))

        def c07():
            response = check_http(send(SYNTHETIC["key"]), 202)
            run_primary[0] = response["run_id"]
            require(response["session_id"] == SYNTHETIC["room"] and response["transport"] == "runs", "text owner/transport")
            pipe("advance", run=run_primary[0], state="completed", output=SYNTHETIC["output"])
            result = check_http(poll(run_primary[0]), 200)
            require(result["status"] == "completed" and result["done"] is True and
                    result["output"] == SYNTHETIC["output"], "exact text terminal output")
            require(check_http(request_http("GET", "/api/relay/state"), 200)["session_id"] == SYNTHETIC["room"],
                    "fresh-client selected room")
            require(check_http(poll(run_primary[0]), 200)["output"] == SYNTHETIC["output"], "fresh-client output")
            db = sqlite3.connect(root / "fixture-data/relay-state.db")
            try:
                require(db.execute("SELECT session_id,output FROM relay_turn_meta WHERE run_id=?",
                                   (run_primary[0],)).fetchone() == (SYNTHETIC["room"], SYNTHETIC["output"]), "durable output")
                require(db.execute("SELECT state,run_id FROM relay_sent_keys WHERE key=?",
                                   (SYNTHETIC["key"],)).fetchone() == ("accepted", run_primary[0]), "durable sent key")
            finally:
                db.close()

        def c08():
            before = pipe("snapshot")
            response = check_http(send(SYNTHETIC["key"]), 202)
            require(response["replayed"] is True and response["run_id"] == run_primary[0] and
                    before["created"] == 1, "idempotent replay")
            check_http(send(SYNTHETIC["key"], text="changed synthetic text"), 409)
            check_http(send(SYNTHETIC["key"], room=SYNTHETIC["foreign_room"]), 409)
            equal_effects(before, pipe("snapshot"))

        def c09():
            check_http(send(SYNTHETIC["uncertain_key"]), 504)
            before = pipe("snapshot")
            require(before["created"] == 2 and any(k[:2] == [SYNTHETIC["uncertain_key"], "inflight"]
                    for k in before["keys"]) and "uncertain:" + SYNTHETIC["uncertain_key"] in before["obligations"],
                    "uncertain accepted submit must retain marker/token")
            check_http(send(SYNTHETIC["uncertain_key"]), 409)
            equal_effects(before, pipe("snapshot"))

        def c10():
            run_approval[0] = check_http(send("phase-c-approval-001"), 202)["run_id"]
            pipe("approval", run=run_approval[0], request=SYNTHETIC["request_id"])
            fresh = pipe("fresh_decisions", run=run_approval[0], request=SYNTHETIC["request_id"])
            require(any(card["request_id"] == SYNTHETIC["request_id"] for card in fresh["pending"]), "fresh pending store")
            pending = check_http(request_http("GET", "/api/relay/decisions?session=" + SYNTHETIC["room"]), 200)
            require(any(card["request_id"] == SYNTHETIC["request_id"] for card in pending["pending"]), "pending HTTP request")
            body = control_body(run_approval[0], action="resolve", request_id=SYNTHETIC["request_id"],
                                choice="deny", reason=SYNTHETIC["reason"], allow_reason=True)
            result = check_http(request_http("POST", "/api/relay/decisions", body), 200)
            require(result["reason_native"] is False and result["reason"] == SYNTHETIC["reason"] and
                    "Relay only" in result["reason_note"], "typed Relay-local denial")
            evidence = pipe("snapshot")
            require(evidence["forwarded"] == [{"run_id": run_approval[0], "choice": "deny",
                    "request_id": SYNTHETIC["request_id"], "resolve_all": False}], "exact forwarded payload")

        def c11():
            body = control_body(run_approval[0], action="resolve", request_id=SYNTHETIC["request_id"], choice="deny")
            before = pipe("snapshot")
            for mutant in (body, dict(body, request_id="wrong"), dict(body, run_id="unowned"),
                           dict(body, session_id=SYNTHETIC["foreign_room"]), dict(body, generation="0" * 48)):
                require(request_http("POST", "/api/relay/decisions", mutant)[0] in (403, 409), "stale/foreign approval refusal")
            equal_effects(before, pipe("snapshot"))
            request = "phase-c-request-concurrent"
            pipe("approval", run=run_approval[0], request=request)
            body = control_body(run_approval[0], action="resolve", request_id=request, choice="once")
            barrier, results = threading.Barrier(2, timeout=0.25), queue.Queue()
            def tap():
                try:
                    barrier.wait()
                    results.put(request_http("POST", "/api/relay/decisions", body)[0])
                except BaseException as error:
                    results.put(error)
            contenders = [threading.Thread(target=tap, daemon=True) for _ in range(2)]
            for contender in contenders:
                contender.start()
            outcomes = [results.get(timeout=2.0) for _ in range(2)]
            for contender in contenders:
                contender.join(0.25)
                require(not contender.is_alive(), "concurrent tap join")
            require(sorted(outcomes) == [200, 409], "exactly one concurrent tap resolved")
            after = pipe("snapshot")
            require(len(after["forwarded"]) == 2 and after["counts"]["relay_decisions"] == 2,
                    "duplicate forwarding finding: stop progression")
            fresh = pipe("fresh_decisions", run=run_approval[0], request=request)
            require(fresh["resolved"] is True and not fresh["pending"], "resolved fresh-store ledger")

        def c12():
            before = pipe("snapshot")
            body = control_body(run_approval[0])
            for mutant in (dict(body, run_id="unowned"), dict(body, session_id=SYNTHETIC["foreign_room"])):
                check_http(request_http("POST", "/api/relay/stop", mutant), 403)
            equal_effects(before, pipe("snapshot"))
            result = check_http(request_http("POST", "/api/relay/stop", body), 200)
            require(result["status"] == "cancelled" and check_http(poll(run_approval[0]), 200)["done"] is True,
                    "truthful observed cancellation")
            require(pipe("snapshot")["stops"] == 1, "owned cancellation count")

        def c13():
            require(len(pipe("ordered_models")["synthetic_histories"]) == 2, "ordered synthetic lease histories")
            run_states[0] = check_http(send("phase-c-states-001"), 202)["run_id"]
            sent_at = time.monotonic()
            drained = pipe("drain")
            require(drained["state"] == "DRAINING" and sent_at <= drained["completed_at"], "accepted send before drain")
            before = pipe("snapshot")
            check_http(send("phase-c-after-drain-001"), 503)
            check_http(request_http("POST", "/api/relay/room", {"session_id": SYNTHETIC["foreign_room"]}), 503)
            equal_effects(before, pipe("snapshot"))
            health = check_http(request_http("GET", "/api/relay/health"), 200)
            require(health["ready"] is False and health["fixture_state"] == "DRAINING", "nonready drain health")
            require(pipe("finish_live")["refused"] is True, "finish_stop must refuse live/uncertain obligations")

        def c14():
            for state in ("offline", "reconnecting", "completed"):
                pipe("advance", run=run_states[0], state=state, output="")
                result = check_http(poll(run_states[0]), 200)
                require(result["status"] == state and result["output"] == "" and
                        result["done"] is (state == "completed"), "fake status/output honesty")
            health = check_http(request_http("GET", "/api/relay/health"), 200)
            require(health["fixture_state"] == "STOPPING" and health["ready"] is False, "STOPPING nonready health")

        def c15():
            before = pipe("snapshot")
            require("uncertain:" + SYNTHETIC["uncertain_key"] in before["obligations"], "precrash uncertainty retained")
            native.check(native.k.TerminateProcess(holder["handle"], 93))
            require(native.wait(holder["handle"], 2.0), "intentional owned crash exit unknown")
            confirmed_exit("intentional synthetic fault; not graceful drain; uncertainty preserved")
            require(not sampler()[0], "crash listener absence")
            os.remove(root / "handshake/record.json")
            old_generation = holder["generation"]
            launch()
            require(holder["generation"] != old_generation and holder["launches"] == 2, "fresh recovery generation")
            check_http(request_http("GET", "/api/relay/health"), 200)
            require(check_http(request_http("GET", "/api/relay/state"), 200)["session_id"] == SYNTHETIC["room"], "recovery room")
            require(check_http(poll(run_primary[0]), 200)["output"] == SYNTHETIC["output"], "recovery durable output")
            before = pipe("snapshot")
            check_http(send(SYNTHETIC["uncertain_key"]), 409)
            equal_effects(before, pipe("snapshot"))
            require(before["created"] == 0 and not before["obligations"], "recovery read-back confers no live authority")
            require(pipe("fresh_decisions", run=run_approval[0], request=SYNTHETIC["request_id"])["resolved"],
                    "recovery exact decision ledger")
            print("SYNTHETIC recovery preserves inflight marker; no recovered token/upstream completion claim")

        def c16():
            require(pipe("snapshot")["violations"] == 0 and violations[0] == 0, "zero unexpected guard violations")
            cleanup("normal recovery-fixture shutdown", True)
            require({p.name for p in control.iterdir()} == {"custody.jsonl"}, "exact stable control contents")
            for path, expected in manifest.items():
                require(digest(read_exact(path.strip())) == expected, "postrun protected source")
            require(source_hashes == {p: digest(read_exact(p)) for p in OUTPUTS[:3]}, "postrun implementation hashes")

        registry = (("C01", "static", c01), ("C02", "synthetic/static guard policy candidates", c02),
                    ("C03", "native occupancy; synthetic contradictions", c03),
                    ("C04", "native handle/handshake/listener", c04),
                    ("C05", "synthetic handshake/unknown-exit candidates", c05),
                    ("C06", "native HTTP; synthetic health/routes", c06),
                    ("C07", "synthetic real handler/store text/read-back", c07),
                    ("C08", "synthetic idempotency", c08), ("C09", "synthetic uncertainty", c09),
                    ("C10", "synthetic real approval/local reason", c10),
                    ("C11", "synthetic duplicate/concurrent forwarding", c11),
                    ("C12", "synthetic owned cancellation", c12),
                    ("C13", "synthetic genuine lifecycle ordered histories/drain", c13),
                    ("C14", "synthetic offline/reconnecting/empty", c14),
                    ("C15", "native crash/recovery; synthetic durable read-back", c15),
                    ("C16", "native exit/listener/cleanup; static hashes", c16))
        try:
            for case_id, evidence, check in registry:
                attempted += 1
                require(not outer_cleanup.is_set(), "outer requested owned cleanup")
                remaining = 150.0 - (time.monotonic() - start)
                require(remaining > 0, "whole local active deadline")
                bounded(check, min(16.0 if case_id == "C15" else 8.0, remaining))
                if case_id == "C03":
                    # Windows mutex ownership must remain on this live main thread.
                    lease()
                require(violations[0] == 0, "caught parent guard violation")
                passed += 1
                print(case_id + " PASS " + evidence, flush=True)
            print("RESULT mode=local-8772 cases=16 pass=16 fail=0 skip=0 not_run=0 violations=0 launches=2 requests=" +
                  str(requests[0]), flush=True)
            print("CUSTODY_CLEAN child_exits_confirmed root_removed no_8772_listener", flush=True)
            print("LIMIT disposable fixture rehearsal only; no production/Hermes/phone/PWA/deployment/Mind/release readiness")
            return 0
        except BaseException as error:
            print("BLOCKED " + type(error).__name__ + ": " + str(error)[:4096], flush=True)
            try:
                cleanup("failed gate containment only", True)
                print("CUSTODY_CLEAN child_exits_confirmed root_removed no_8772_listener", flush=True)
            except BaseException as cleanup_error:
                print("BLOCKED CLEANUP " + type(cleanup_error).__name__ + ": " + str(cleanup_error)[:4096], flush=True)
                if holder["handle"] is not None:
                    print("UNKNOWN_CUSTODY holder/root/journal retained; no further qualification", flush=True)
                    threading.Event().wait()
            if holder["stderr"]:
                print("CHILD_STDERR " + holder["stderr"].decode("utf-8", "replace")[:4096], flush=True)
            print("RESULT mode=local-8772 cases=16 pass=" + str(passed) + " fail=1 skip=0 not_run=" +
                  str(16 - attempted) + " violations=" + str(violations[0]) + " launches=" +
                  str(holder["launches"]), flush=True)
            return 1
        finally:
            if holder["handle"] is None and holder["lease"] is not None:
                if holder["lease_held"]:
                    native.check(native.k.ReleaseMutex(holder["lease"]))
                native.k.CloseHandle(holder["lease"])

    if child_mode:
        return child_main()
    return parent_main()


if __name__ == "__main__":
    raise SystemExit(local8772(sys.argv[1:]))
