"""Content-free instrumentation for disposable worker diagnostics, never live injection."""
import ast
import re


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


def instrument_constructor(source: bytes) -> bytes:
    """Time route resolution and construction; never log arguments or returned values."""
    text = source.decode('utf-8')
    if 'MESH_WORKER_CONSTRUCT ' in text:
        raise ValueError('constructor_markers_already_present')
    anchor = '        return factory(**{**kwargs, **worker_route(policy, kwargs)})\n'
    if text.count(anchor) != 1:
        raise ValueError('unexpected_constructor_seam')
    lines = []
    def event(phase):
        lines.append('        print("MESH_WORKER_CONSTRUCT ' + phase
                     + '", __import__("time").monotonic_ns(), '
                     + 'file=__import__("sys").stderr, flush=True)\n')
    event('route_begin')
    lines.append('        _mesh_startup_route = worker_route(policy, kwargs)\n')
    event('route_complete')
    event('factory_begin')
    lines.append('        _mesh_startup_agent = factory(**{**kwargs, **_mesh_startup_route})\n')
    event('factory_complete')
    lines.append('        return _mesh_startup_agent\n')
    text = text.replace(anchor, ''.join(lines))
    ast.parse(text)
    return text.encode('utf-8')


def instrument_constructor_stacks(source: bytes, session_id: str, *, seconds: int = 15) -> bytes:
    """Arm no-locals stack capture before construction, only for a named diagnostic session."""
    if not re.fullmatch(r'local-[0-9a-f]{64}', session_id) or seconds not in (1, 15):
        raise ValueError('invalid_diagnostic_stack_scope')
    text = source.decode('utf-8')
    anchor = '        _mesh_startup_agent = factory(**{**kwargs, **_mesh_startup_route})\n'
    if '_mesh_startup_faults' in text or text.count(anchor) != 1:
        raise ValueError('unexpected_or_instrumented_factory_seam')
    replacement = (
        '        _mesh_startup_faults = None\n'
        '        if frame.get("scope", {}).get("session_id") == ' + repr(session_id) + ':\n'
        '            import faulthandler as _mesh_startup_faults\n'
        '            _mesh_startup_faults.dump_traceback_later(' + str(seconds)
        + ', repeat=True, file=__import__("sys").stderr)\n'
        '        try:\n'
        '    ' + anchor +
        '        finally:\n'
        '            if _mesh_startup_faults is not None:\n'
        '                _mesh_startup_faults.cancel_dump_traceback_later()\n'
    )
    text = text.replace(anchor, replacement)
    ast.parse(text)
    return text.encode('utf-8')


def constructor_timings(log: str) -> list[dict]:
    """Only accept complete, ordered per-process timing records."""
    groups = {}
    for pid, phase, timestamp in re.findall(
            r'\[pid (\d+)\] MESH_WORKER_CONSTRUCT (\w+) (\d+)', log):
        groups.setdefault(pid, []).append((phase, int(timestamp)))
    expected = ['route_begin', 'route_complete', 'factory_begin', 'factory_complete']
    results = []
    for pid, events in groups.items():
        if [phase for phase, _ in events] != expected:
            raise ValueError('incomplete_or_duplicate_constructor_timing')
        ticks = [tick for _, tick in events]
        if ticks != sorted(ticks):
            raise ValueError('nonmonotonic_constructor_timing')
        results.append({'pid': int(pid), 'routeMilliseconds': (ticks[1]-ticks[0])/1e6,
                        'factoryMilliseconds': (ticks[3]-ticks[2])/1e6})
    if not results:
        raise ValueError('missing_constructor_timing')
    return results
