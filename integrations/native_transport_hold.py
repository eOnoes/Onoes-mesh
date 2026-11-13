"""Trusted operator-only Windows transport hold; never worker-retirement proof.

Reserve exact loopback TCP endpoints without listening or accepting requests.
Existing listeners are refused, never stopped. Importing this module does nothing.
See https://learn.microsoft.com/en-us/windows/win32/winsock/so-exclusiveaddruse
"""
from contextlib import contextmanager
import os
import socket
import sys
import threading
from weakref import WeakKeyDictionary


class _Lease:
    __slots__ = ('__weakref__',)


_holds = WeakKeyDictionary()


def _endpoints(values):
    if not isinstance(values, (tuple, list)) or not 1 <= len(values) <= 16:
        raise ValueError('One to sixteen exact loopback endpoints are required.')
    result = []
    for value in values:
        if not isinstance(value, (tuple, list)) or len(value) != 2:
            raise ValueError('An endpoint must contain an address and port.')
        address, port = value
        if address not in ('127.0.0.1', '::1') or type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError('Only literal loopback addresses and exact unprivileged ports are allowed.')
        result.append((address, port))
    if len(set(result)) != len(result):
        raise ValueError('Duplicate endpoints are not allowed.')
    return tuple(sorted(result))


def assert_loopback_hold(lease, expected_endpoints):
    if not isinstance(lease, _Lease) or lease not in _holds:
        raise RuntimeError('An authentic active transport hold is required.')
    state = _holds[lease]
    if state['pid'] != os.getpid() or state['thread'] is not threading.current_thread():
        raise RuntimeError('Transport hold belongs to another process or thread.')
    if _endpoints(expected_endpoints) != state['endpoints']:
        raise RuntimeError('Transport hold does not match the reviewed endpoints.')
    for endpoint, handle in zip(state['endpoints'], state['sockets']):
        if (handle.fileno() < 0 or handle.getsockname()[:2] != endpoint or
                handle.getsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE) != 1 or
                handle.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN) != 0 or
                handle.get_inheritable()):
            raise RuntimeError('The exclusive non-listening transport hold was lost.')
    return {'schema': 'mesh-native-transport-hold/v1', 'scope': 'loopback_tcp_admissions_only',
            'endpoints': [list(value) for value in state['endpoints']], 'held': True,
            'ownerPid': state['pid'], 'workerRetirementEstablished': False,
            'coversDirectExecution': False}


@contextmanager
def hold_loopback_transports(endpoints):
    if sys.platform != 'win32' or not hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        raise RuntimeError('Actual Windows exclusive socket support is required.')
    reviewed = _endpoints(endpoints)
    handles = []
    lease = _Lease()
    try:
        for address, port in reviewed:
            family = socket.AF_INET6 if address == '::1' else socket.AF_INET
            handle = socket.socket(family, socket.SOCK_STREAM)
            handles.append(handle)
            handle.set_inheritable(False)
            handle.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            if family == socket.AF_INET6:
                handle.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            handle.bind((address, port))
        _holds[lease] = {'pid': os.getpid(), 'thread': threading.current_thread(),
                         'endpoints': reviewed, 'sockets': tuple(handles)}
        assert_loopback_hold(lease, reviewed)
        yield lease
    finally:
        _holds.pop(lease, None)
        for handle in reversed(handles):
            handle.close()
