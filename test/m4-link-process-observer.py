"""Read-only retained native handles for exactly the test's owned process ids."""
import ctypes
from ctypes import wintypes
import json
import sys

k = ctypes.WinDLL('kernel32', use_last_error=True)
k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
k.OpenProcess.restype = wintypes.HANDLE
k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
k.CloseHandle.argtypes = [wintypes.HANDLE]
handles = []
try:
    for raw in sys.argv[1:]:
        pid = int(raw)
        handle = k.OpenProcess(0x100000 | 0x1000, False, pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        handles.append((handle, {'pid': pid}))
        created, exited, kernel, user = [wintypes.FILETIME() for _ in range(4)]
        if not k.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
            raise ctypes.WinError(ctypes.get_last_error())
        image = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(image))
        if not k.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
            raise ctypes.WinError(ctypes.get_last_error())
        handles[-1][1].update(creationTime100ns=str((created.dwHighDateTime << 32) | created.dwLowDateTime), executable=image.value)
    print(json.dumps({'event': 'held', 'identities': [identity for _, identity in handles]}), flush=True)
    sys.stdin.readline()  # Test closes only its own ChildProcess/owning pipe.
    for handle, identity in handles:
        identity['exitSignaled'] = k.WaitForSingleObject(handle, 6000) == 0
        code = wintypes.DWORD()
        if not k.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        identity['exitCode'] = code.value
    result = {'event': 'verified', 'identities': [identity for _, identity in handles]}
    print(json.dumps(result), flush=True)
    if not all(identity['exitSignaled'] for _, identity in handles):
        raise RuntimeError('An original owned process is still alive')
finally:
    for handle, _ in handles:
        k.CloseHandle(handle)
