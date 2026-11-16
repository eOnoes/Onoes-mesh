"""Share the existing named Mesh launcher's mutex during an approved cutover.

This module changes no task, process, file, or enrollment. The caller must keep
the context open from the final owner check through publication of the new
named-launcher receipt, performing any owned rollback inside that context.
Exiting the context releases the lock; it does not retire a child or roll back.
"""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import re


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

    def __exit__(self, *_):
        if self.handle is None or self.kernel.GetCurrentThreadId() != self.owner_thread:
            raise LauncherWindowError('Only the owning thread can release the launcher window.')
        handle, self.handle = self.handle, None
        released = self.kernel.ReleaseMutex(handle)
        self.kernel.CloseHandle(handle)
        if not released:
            raise LauncherWindowError('Launcher mutex release failed; inspect ownership.')
