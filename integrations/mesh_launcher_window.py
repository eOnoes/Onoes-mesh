"""Share the existing named Mesh launcher's mutex during an approved cutover.

This module changes no task, process, or enrollment. Receipt publication only
records the exact child the caller already launched. The caller must keep
the context open from the final owner check through publication of the new
named-launcher receipt, performing any owned rollback inside that context.
Exiting the context releases the lock; it does not retire a child or roll back.
"""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import uuid
from datetime import datetime, timedelta, timezone


class LauncherWindowError(RuntimeError):
    pass


def launcher_mutex_name(workspace):
    path = Path(workspace)
    if not path.is_absolute() or path.resolve() != path or not path.is_dir():
        raise LauncherWindowError('An existing canonical workspace is required.')
    return 'Local\\ONOesMeshWorkroom-' + hashlib.sha256(str(path).encode('utf-8')).hexdigest().upper()[:16]


class MeshLauncherWindow:
    def __init__(self, workspace, launcher_sha256):
        if os.name != 'nt' or not re.fullmatch('[0-9a-f]{64}', launcher_sha256):
            raise LauncherWindowError('Windows and an exact launcher fingerprint are required.')
        self.workspace = Path(workspace)
        self.name = launcher_mutex_name(self.workspace)
        self.launcher = self.workspace / 'integrations/restart-workroom-preview.ps1'
        self.sha256 = launcher_sha256
        self.handle = None
        self.owner_thread = None
        self.abandoned = False
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        for name, args, result in (
            ('CreateMutexW', [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
            ('WaitForSingleObject', [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            ('ReleaseMutex', [wintypes.HANDLE], wintypes.BOOL),
            ('CloseHandle', [wintypes.HANDLE], wintypes.BOOL),
            ('GetCurrentThreadId', [], wintypes.DWORD),
            ('GetProcessTimes', [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)]*4, wintypes.BOOL),
            ('OpenProcess', [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            ('QueryFullProcessImageNameW', [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                          ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
        ):
            fn = getattr(self.kernel, name)
            fn.argtypes, fn.restype = args, result

    def _check_source(self):
        if (not self.launcher.is_file() or self.launcher.resolve() != self.launcher
                or hashlib.sha256(self.launcher.read_bytes()).hexdigest() != self.sha256):
            raise LauncherWindowError('The approved named launcher changed.')

    def __enter__(self):
        if self.handle is not None:
            raise LauncherWindowError('A launcher window cannot be entered twice.')
        self._check_source()
        handle = self.kernel.CreateMutexW(None, False, self.name)
        if not handle:
            raise LauncherWindowError('Cannot open the named launcher mutex.')
        state = self.kernel.WaitForSingleObject(handle, 0)
        if state not in (0, 0x80):
            self.kernel.CloseHandle(handle)
            raise LauncherWindowError('Another named Mesh launcher operation is in progress.')
        self.handle = handle
        self.owner_thread = self.kernel.GetCurrentThreadId()
        self.abandoned = state == 0x80
        try:
            self.assert_held()
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def assert_held(self):
        if self.handle is None or self.kernel.GetCurrentThreadId() != self.owner_thread:
            raise LauncherWindowError('The current thread does not own the launcher window.')
        self._check_source()

    def _owns_gateway(self, pid, port):
        class TcpOwner(ctypes.Structure):
            _fields_ = [(name, wintypes.DWORD) for name in
                        ('state', 'address', 'port', 'remote_address', 'remote_port', 'pid')]
        api = ctypes.WinDLL('iphlpapi', use_last_error=True).GetExtendedTcpTable
        api.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
                        wintypes.ULONG, ctypes.c_int, wintypes.ULONG]
        api.restype = wintypes.DWORD
        size = wintypes.DWORD()
        if api(None, ctypes.byref(size), False, 2, 3, 0) != 122 or not 4 <= size.value <= 1048576:
            raise LauncherWindowError('Cannot observe gateway ownership.')
        buffer = ctypes.create_string_buffer(size.value)
        if api(buffer, ctypes.byref(size), False, 2, 3, 0) != 0:
            raise LauncherWindowError('Gateway ownership observation changed; preserve state.')
        count = wintypes.DWORD.from_buffer_copy(buffer.raw[:4]).value
        if 4 + count*ctypes.sizeof(TcpOwner) > size.value:
            raise LauncherWindowError('Invalid gateway ownership observation.')
        rows = (TcpOwner*count).from_buffer_copy(buffer.raw[4:4+count*ctypes.sizeof(TcpOwner)])
        listeners = [row for row in rows if socket.ntohs(row.port & 0xffff) == port]
        if len(listeners) != 1 or listeners[0].pid != pid or listeners[0].address != 0x0100007f:
            raise LauncherWindowError('Exact native child does not own the loopback gateway.')

    def publish_native_owner(self, child, creation_ticks, profile_path, profile_sha256,
                             *, previous_sha256, beforeimage_path=None):
        """Publish only an existing exact native child; never launch, stop, or retry.

        The caller retains the original Popen handle. Readiness and any rollback
        remain inside this window before release. Unknown old owners block it.
        """
        self.assert_held()
        def require(ok, why):
            if not ok: raise LauncherWindowError(why)
        def read(path):
            require(path.resolve() == path and path.is_file() and path.stat().st_size <= 65536,
                    'Ordinary bounded metadata file required.')
            return path.read_bytes()
        def sha(body): return hashlib.sha256(body).hexdigest()
        profile_path = Path(profile_path)
        raw = read(profile_path)
        require(sha(raw) == profile_sha256, 'Native profile changed.')
        profile = json.loads(raw)
        require(profile.get('schema') in ('onoes-mesh-native-launch/v1', 'onoes-mesh-native-launch/v2', 'onoes-mesh-native-capture-launch/v1')
                and profile.get('workspace') == str(self.workspace), 'Native workspace mismatch.')
        executable = Path(profile['nodeExecutable'])
        require(executable.resolve() == executable and sha(executable.read_bytes()) == profile['nodeSha256'],
                'Native executable changed.')
        args = [str(executable), str(self.workspace/'serve.mjs'), '--native-mind']
        require(child.args == args and child.poll() is None, 'Exact native child is not live.')
        times = [wintypes.FILETIME() for _ in range(4)]
        require(self.kernel.GetProcessTimes(child._handle, *(ctypes.byref(t) for t in times)),
                'Cannot prove native child creation time.')
        ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        require(ticks == creation_ticks, 'Native child creation time mismatch.')
        image = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(image))
        require(self.kernel.QueryFullProcessImageNameW(child._handle, 0, image, ctypes.byref(size))
                and Path(image.value) == executable, 'Native child executable mismatch.')
        attempt = json.loads(read(Path(profile['attemptPath'])))
        require(attempt.get('schema') in ('onoes-mesh-native-child/v1','onoes-mesh-native-child/v2','onoes-mesh-native-child/v3')
                and attempt.get('profileSha256') == profile_sha256 and attempt.get('pid') == child.pid
                and attempt.get('creationTicks') == ticks and attempt.get('state') == 'input_sent'
                and attempt.get('executable') == str(executable)
                and attempt.get('entryPoint') == args[1] and attempt.get('credentialsInRecord') is False,
                'Native launch attempt does not identify this child.')
        require((profile['schema']=='onoes-mesh-native-capture-launch/v1') == (attempt['schema']=='onoes-mesh-native-child/v3'),
                'Native launch mode and profile disagree.')
        if attempt['schema']=='onoes-mesh-native-child/v3':
            require(attempt.get('mode')=='capture_only' and 'peers' not in attempt, 'Invalid offline capture identity.')
        port = profile['settings']['MESH_PREVIEW_PORT']
        require(type(port) is str and port.isdecimal() and 1 <= int(port) <= 65535,
                'Explicit native gateway port required.')
        self._owns_gateway(child.pid, int(port))
        target = self.workspace.parent/'workroom-ab-preview-process.json'
        require(target.resolve() == target, 'Owner receipt aliases another path.')
        previous = read(target) if target.exists() else None
        require((previous is None and previous_sha256 is None)
                or (previous is not None and sha(previous) == previous_sha256), 'Owner receipt changed.')
        if previous is not None:
            old = json.loads(previous)
            require(old.get('Schema') == 'onoes-owned-process/v1'
                    and old.get('WorkingDirectory') == str(self.workspace)
                    and old.get('EntryPoint') == args[1] and old.get('Port') == int(port)
                    and old.get('Path') == str(executable) and type(old.get('Id')) is int and old['Id'] > 0,
                    'Previous receipt has different ownership.')
            handle = self.kernel.OpenProcess(0x00100000 | 0x1000, False, old['Id'])
            if handle:
                try:
                    stamp=old.get('StartTime')
                    require(type(stamp) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{7}Z',stamp),
                            'Previous owner birth is unknown.')
                    day=datetime.strptime(stamp[:19],'%Y-%m-%dT%H:%M:%S').replace(tzinfo=timezone.utc)
                    delta=day-datetime(1601,1,1,tzinfo=timezone.utc)
                    old_ticks=(delta.days*86400+delta.seconds)*10000000+int(stamp[20:27])
                    times_old=[wintypes.FILETIME() for _ in range(4)]
                    require(self.kernel.GetProcessTimes(handle,*(ctypes.byref(value) for value in times_old)),
                            'Previous owner birth cannot be observed.')
                    observed_ticks=(times_old[0].dwHighDateTime<<32)|times_old[0].dwLowDateTime
                    require(observed_ticks!=old_ticks or self.kernel.WaitForSingleObject(handle,0)==0,
                            'Previous owner is still live.')
                finally: self.kernel.CloseHandle(handle)
            else:
                require(ctypes.get_last_error() == 87, 'Previous owner retirement is unknown.')
            backup = Path(beforeimage_path) if beforeimage_path is not None else None
            require(backup is not None and backup.is_absolute() and backup.resolve() == backup
                    and backup.is_relative_to(self.workspace/'data') and backup.parent.is_dir(),
                    'Explicit local receipt beforeimage required.')
            with backup.open('xb') as out:
                out.write(previous); out.flush(); os.fsync(out.fileno())
        date = datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=ticks//10)
        start = date.strftime('%Y-%m-%dT%H:%M:%S.') + f'{date.microsecond:06}{ticks%10}Z'
        record = dict(Schema='onoes-owned-process/v1', AppName="ONOe's Mesh - Workroom",
                      WorkingDirectory=str(self.workspace), EntryPoint=args[1], Port=int(port),
                      Url='https://'+profile['settings']['MESH_TAILSCALE_HOST']+'/#workroom',
                      CommandLine=subprocess.list2cmdline(args), Id=child.pid, StartTime=start,
                      Path=str(executable))
        self.assert_held()
        require(child.poll() is None and sha(read(profile_path)) == profile_sha256,
                'Native child or profile changed before publication.')
        self._owns_gateway(child.pid, int(port))
        require((not target.exists()) if previous is None else read(target) == previous,
                'Owner receipt changed before publication.')
        temporary = target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
        with temporary.open('xb') as out:
            out.write(json.dumps(record).encode('utf-8')); out.flush(); os.fsync(out.fileno())
        os.replace(temporary, target)
        return record

    def __exit__(self, *_):
        if self.handle is None or self.kernel.GetCurrentThreadId() != self.owner_thread:
            raise LauncherWindowError('Only the owning thread can release the launcher window.')
        handle, self.handle = self.handle, None
        released = self.kernel.ReleaseMutex(handle)
        self.kernel.CloseHandle(handle)
        if not released:
            raise LauncherWindowError('Launcher mutex release failed; inspect ownership.')
