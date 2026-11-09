"""Content-free instrumentation for disposable worker diagnostics, never live injection."""
import ast


MARKERS = (
    ("    bind_worker_policy(frame)\n", "policy_bound", False),
    ("    adopted = rpc('worker.adopt'", "owner_adopt_begin", True),
    ("    if adopted['owner_epoch']", "owner_adopt_returned", True),
    ("    from gateway.session_kanban import bind_worker_context\n", "store_created", True),
    ("    process_registry.recover_from_checkpoint()\n", "process_recovery_complete", False),
    ("    discover_profile_mcp(policy)\n", "mcp_discovery_begin", True),
    ("    discover_profile_mcp(policy)\n", "mcp_discovery_complete", False),
    ("    from run_agent import AIAgent\n", "agent_import_complete", False),
    ("            agent = _construct_agent(", "agent_construct_begin", True),
    ("            controls.agent = agent\n", "agent_construct_complete", True),
    ("            channel.send('ready', pid=os.getpid())\n", "ready_sent", False),
)


def instrument_worker(source: bytes) -> bytes:
    """Refuse unexpected/previously patched source; emit fixed labels on stderr only."""
    text = source.decode('utf-8')
    if 'MESH_WORKER_STARTUP ' in text:
        raise ValueError('startup_markers_already_present')
    for anchor, phase, before in MARKERS:
        if text.count(anchor) != 1:
            raise ValueError('unexpected_startup_seam:' + phase)
        start = text.index(anchor)
        end = text.index('\n', start) + 1
        indent = anchor[:len(anchor) - len(anchor.lstrip())]
        marker = indent + 'print("MESH_WORKER_STARTUP ' + phase + '", file=__import__("sys").stderr, flush=True)\n'
        point = start if before else end
        text = text[:point] + marker + text[point:]
    ast.parse(text)
    return text.encode('utf-8')
