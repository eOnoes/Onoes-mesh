"""One detached hidden local qualification, with original native root exits.

Launch with pythonw.exe, never CREATE_NO_WINDOW for console qualification roots.
No process termination, retries, service changes or workspace cleanup.
"""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('parentage_focus', ROOT / 'test/m6-observer-parentage.py')
focus = importlib.util.module_from_spec(spec)
spec.loader.exec_module(focus)


def main(directory):
    directory.mkdir(parents=True, exist_ok=True)
    n = focus.embedded()
    observer = n['o']
    n['retain'](os.getpid(), None, 'M6 verification harness')
    receipt = {'worktree': str(ROOT), 'purpose': 'One detached local M6 instrument qualification',
               'launchFlags': 'DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP', 'results': []}
    files = ['test/m6-standalone-fixture.mjs', 'test/m6-observer-parentage.py',
             'test/m6-observer-parentage-host.py', 'test/m6-standalone-checks.mjs',
             'test/m6-standalone-browser.mjs', 'package.json']
    receipt['sourceSha256'] = {f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in files}

    def health():
        try:
            with urllib.request.urlopen('http://127.0.0.1:4317/', timeout=5) as response:
                return {'url': response.url, 'status': response.status,
                        'shellSha256': hashlib.sha256(response.read()).hexdigest()}
        except Exception as error:
            return {'url': 'http://127.0.0.1:4317/', 'error': str(error)}

    def save():
        receipt.update(identities=n['records'], acquisitionRaces=n['races'], rejectedParentage=n['rejected'])
        (directory / 'host.json').write_text(json.dumps(receipt, indent=2), encoding='utf8')

    user = C.WinDLL('user32', use_last_error=True)
    callback_type = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
    user.EnumWindows.argtypes = [callback_type, W.LPARAM]
    user.IsWindowVisible.argtypes = [W.HWND]
    user.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
    visible = set()
    window_access = True

    def windows():
        nonlocal window_access
        if not window_access:
            return
        owned = set(n['live'])
        @callback_type
        def callback(hwnd, unused):
            pid = W.DWORD()
            user.GetWindowThreadProcessId(hwnd, C.byref(pid))
            if pid.value in owned and user.IsWindowVisible(hwnd):
                visible.add(pid.value)
            return True
        if not user.EnumWindows(callback, 0):
            window_access = False
            receipt['windowEnumerationUnavailable'] = {'nativeError': C.get_last_error(),
                                                       'reason': 'EnumWindows returned zero; no desktop access changes attempted'}

    env = dict(os.environ, PYTHONPATH=str(ROOT), MESH_PREVIEW_PORT='0',
               M6_STANDALONE_PLAYWRIGHT='C:/Users/eMitchell109/AppData/Local/hermes/hermes-agent/node_modules/playwright-core/index.mjs',
               M6_STANDALONE_CHROMIUM='C:/Users/eMitchell109/AppData/Local/ms-playwright/chromium-1243/chrome-win64/chrome.exe')
    node = 'C:/Program Files/node.exe'
    plan = [
        ('focused', ['C:/Python314/python.exe', '-B', 'test/m6-observer-parentage.py', str(directory / 'focused')]),
        ('checks', [node, 'test/m6-standalone-checks.mjs']),
        ('browser', [node, 'test/m6-standalone-browser.mjs']),
        ('npm-test', [node, 'C:/Program Files/node_modules/npm/bin/npm-cli.js', 'test']),
    ]
    receipt['protected4317Before'] = health()
    save()
    try:
        for label, argv in plan:
            result = {'label': label, 'executable': argv[0], 'argv': argv, 'worktree': str(ROOT),
                      'purpose': label, 'parentPid': os.getpid()}
            with (directory / (label + '.stdout.txt')).open('wb') as stdout, (directory / (label + '.stderr.txt')).open('wb') as stderr:
                p = subprocess.Popen(argv, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                     stdout=stdout, stderr=stderr,
                                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
                result['pid'] = p.pid
                receipt['results'].append(result)
                identity = n['retain'](p.pid, os.getpid(), 'Detached ' + label + ' qualification root')
                assert identity is not None
                result['identity'] = identity
                save()
                while p.poll() is None:
                    n['scan']()
                    windows()
                    time.sleep(.01)
                result['popenOriginalExitCode'] = p.wait()
                n['scan']()
                assert identity['exitSignaled']
                result['nativeOriginalExitCode'] = identity['exitCode']
                assert identity['exitCode'] == p.returncode
                save()
        n['scan']()
        receipt['visibleOwnedWindowPids'] = sorted(visible)
        receipt['protected4317After'] = health()
        workload = [i for i in n['records'] if i['pid'] != os.getpid()]
        receipt['custodyVerified'] = (all(i['exitSignaled'] and not i.get('commandLineError') for i in workload)
                                      and not n['races'] and not visible and window_access)
        receipt['status'] = 'PASS' if (receipt['custodyVerified'] and all(r['nativeOriginalExitCode'] == 0 for r in receipt['results'])
                                      and receipt['protected4317Before'].get('status') == receipt['protected4317After'].get('status') == 200) else 'BLOCKED'
        save()
        return 0 if receipt['status'] == 'PASS' else 1
    except BaseException as error:
        receipt.update(status='BLOCKED', failure=str(error), protected4317After=health())
        save()
        raise
    finally:
        observer.close()


if __name__ == '__main__':
    sys.exit(main(Path(sys.argv[1])))
