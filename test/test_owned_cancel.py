"""Native cancellation tests and exact-handle observer for M3 Node proofs."""
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
import uuid

from lib import owned_job as oj

ROOT = Path(__file__).resolve().parent.parent


class ProcessEntry(C.Structure):
    _fields_ = [('size', W.DWORD), ('usage', W.DWORD), ('pid', W.DWORD),
                ('heap', C.c_size_t), ('module', W.DWORD), ('threads', W.DWORD),
                ('parent', W.DWORD), ('priority', W.LONG), ('flags', W.DWORD),
                ('exe', W.WCHAR * 260)]


class Observer:
    def __init__(self):
        self.api = oj._Win32()
        dll = self.api._dll
        for name, result, args in [
            ('CreateToolhelp32Snapshot', W.HANDLE, [W.DWORD, W.DWORD]),
            ('Process32FirstW', W.BOOL, [W.HANDLE, C.POINTER(ProcessEntry)]),
            ('Process32NextW', W.BOOL, [W.HANDLE, C.POINTER(ProcessEntry)]),
            ('GetProcessTimes', W.BOOL, [W.HANDLE] + [C.POINTER(W.FILETIME)] * 4),
            ('QueryFullProcessImageNameW', W.BOOL, [W.HANDLE, W.DWORD, W.LPWSTR, C.POINTER(W.DWORD)]),
        ]:
            fn = getattr(dll, name)
            fn.restype, fn.argtypes = result, args
            setattr(self, name, fn)
        self.handles = []

    def processes(self):
        snapshot = self.CreateToolhelp32Snapshot(2, 0)
        if snapshot == C.c_void_p(-1).value:
            raise OSError('process snapshot failed')
        entries = []
        try:
            entry = ProcessEntry()
            entry.size = C.sizeof(entry)
            more = self.Process32FirstW(snapshot, C.byref(entry))
            while more:
                entries.append(dict(pid=int(entry.pid), parentPid=int(entry.parent), exe=entry.exe))
                more = self.Process32NextW(snapshot, C.byref(entry))
        finally:
            assert self.api.CloseHandle(snapshot)
        return entries

    def retain(self, pid, role, terminate=False):
        handle = self.api.OpenProcess(0x00100000 | 0x1000 | (1 if terminate else 0), False, pid)
        if not handle:
            raise OSError(f'cannot retain {role} PID {pid}')
        self.handles.append(handle)
        times = [W.FILETIME() for _ in range(4)]
        assert self.GetProcessTimes(handle, *[C.byref(value) for value in times])
        image = C.create_unicode_buffer(32768)
        size = W.DWORD(len(image))
        assert self.QueryFullProcessImageNameW(handle, 0, image, C.byref(size))
        assert self.api.WaitForSingleObject(handle, 0) == 258, f'{role} must be live'
        return handle, dict(role=role, pid=pid, creationTime100ns=str(
            (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime), executable=image.value)

    def tree(self, caller_pid):
        end = time.monotonic() + 7
        while time.monotonic() < end:
            entries = self.processes()
            bridges = [p for p in entries if p['parentPid'] == caller_pid and p['exe'].lower() == 'python.exe']
            for bridge in bridges:
                roots = [p for p in entries if p['parentPid'] == bridge['pid'] and p['exe'].lower() == 'node.exe']
                for root in roots:
                    descendants = [p for p in entries if p['parentPid'] == root['pid'] and p['exe'].lower() == 'node.exe']
                    if descendants:
                        found = [self.retain(caller_pid, 'caller', True), self.retain(bridge['pid'], 'bridge', True),
                                 self.retain(root['pid'], 'root')]
                        found += [self.retain(p['pid'], 'descendant') for p in descendants]
                        for unused, identity in found[1:]:
                            identity['parentPid'] = next(p['parentPid'] for p in entries if p['pid'] == identity['pid'])
                        return found
            time.sleep(.02)
        raise TimeoutError('owned bridge/root/descendant did not become live')

    def close(self):
        for handle in self.handles:
            assert self.api.CloseHandle(handle)
        self.handles.clear()


def observe(caller_pid):
    """Hold exact kernel objects across cancel/kill; never clean by PID or name."""
    observer = Observer()
    try:
        found = observer.tree(caller_pid)
        print(json.dumps(dict(event='ready', identities=[identity for handle, identity in found])), flush=True)
        action = json.loads(sys.stdin.readline())['action']
        start = time.monotonic()
        if action in ('kill-caller', 'kill-bridge'):
            index = 0 if action == 'kill-caller' else 1
            handle, identity = found[index]
            assert observer.api.WaitForSingleObject(handle, 0) == 258
            assert observer.api.TerminateProcess(handle, 1), identity
        else:
            assert action == 'wait'
        identities = []
        for handle, identity in found:
            state = observer.api.WaitForSingleObject(handle, 5000)
            identities.append(dict(identity, exitSignaled=state == 0))
        print(json.dumps(dict(event='verified', action=action, identities=identities,
                              cleanupVerified=all(p['exitSignaled'] for p in identities),
                              elapsedMs=round((time.monotonic() - start) * 1000, 3))), flush=True)
        assert all(p['exitSignaled'] for p in identities)
    finally:
        observer.close()


class OwnedCancelTests(unittest.TestCase):
    def setUp(self):
        self.assertEqual(sys.platform, 'win32', 'Native Windows required; no skips')
        self.directory = ROOT / 'test' / ('app03-m3-crash-bridge-native-' + str(uuid.uuid4()))
        self.directory.mkdir()

    def save(self, name, result):
        (self.directory / name).write_text(json.dumps(result, indent=2), encoding='utf8')

    def test_cancel_actual_root_and_descendant(self):
        pidfile = self.directory / 'pids.json'
        code = ("import subprocess,sys,time,json,pathlib\n"
                "p=subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(10)'])\n"
                "print('native before cancel',flush=True)\n"
                "f=pathlib.Path(sys.argv[1]); t=f.with_suffix('.tmp'); t.write_text(json.dumps([__import__('os').getpid(),p.pid])); t.replace(f)\n"
                "time.sleep(10)\n")
        cancel = threading.Event()
        results = []
        start = time.monotonic()
        worker = threading.Thread(target=lambda: results.append(oj.run_owned(
            [sys.executable, '-I', '-c', code, str(pidfile)], str(ROOT), 20,
            capture_output=True, cancel_requested=cancel.is_set)))
        observer = Observer()
        worker.start()
        try:
            end = time.monotonic() + 5
            while not pidfile.exists() and time.monotonic() < end:
                time.sleep(.01)
            pids = json.loads(pidfile.read_text())
            found = [observer.retain(pid, role) for pid, role in zip(pids, ['root', 'descendant'])]
            cancel.set()
            worker.join(5)
            self.assertFalse(worker.is_alive())
            result = results[0]
            self.assertEqual(result['status'], 'FAIL')
            self.assertTrue(result['cancelled'])
            self.assertFalse(result['timedOut'])
            self.assertTrue(result['cleanupVerified'], result)
            self.assertEqual(result['stdout'], 'native before cancel\r\n')
            self.assertNotEqual(result['rootExitCode'], 0)
            identities = []
            for handle, identity in found:
                self.assertEqual(observer.api.WaitForSingleObject(handle, 0), 0)
                identities.append(dict(identity, exitSignaled=True))
            self.save('evidence.json', dict(result=result, identities=identities,
                                           elapsedMs=(time.monotonic() - start) * 1000))
        finally:
            cancel.set()
            worker.join(5)
            observer.close()

    def test_pre_cancel_never_launches(self):
        result = oj.run_owned([sys.executable, '-I', '-c', "print('must not run')"],
                              str(ROOT), 2, capture_output=True, cancel_requested=lambda: True)
        self.assertEqual(result['status'], 'FAIL')
        self.assertTrue(result['cancelled'])
        self.assertIsNone(result['rootPid'])
        self.assertIsNone(result['rootExitCode'])
        self.assertTrue(result['cleanupVerified'], result)
        self.assertEqual(result['stdout'], '')
        self.save('pre-cancel.json', result)

    def test_cancel_check_error_fails_closed(self):
        def broken():
            raise RuntimeError('cancellation unavailable')
        result = oj.run_owned([sys.executable, '-I', '-c', 'pass'], str(ROOT), 2,
                              capture_output=True, cancel_requested=broken)
        self.assertEqual(result['status'], 'FAIL')
        self.assertTrue(result['cleanupVerified'], result)
        self.assertIn('cancellation check raised', result['error'])
        self.save('check-error.json', result)

    def test_cancel_after_assignment_never_resumes(self):
        cancel = threading.Event()
        api = oj._Win32()

        class CancelAtAssign:
            resumed = False

            def __getattr__(self, name):
                return getattr(api, name)

            def AssignProcessToJobObject(self, *args):
                ok = api.AssignProcessToJobObject(*args)
                cancel.set()
                return ok

            def ResumeThread(self, *args):
                self.resumed = True
                return api.ResumeThread(*args)

        proxy = CancelAtAssign()
        with oj._using_api(proxy):
            result = oj.run_owned([sys.executable, '-I', '-c', "print('must never run')"],
                                  str(ROOT), 2, capture_output=True, cancel_requested=cancel.is_set)
        self.assertFalse(proxy.resumed)
        self.assertEqual(result['status'], 'FAIL')
        self.assertTrue(result['cleanupVerified'], result)
        self.assertTrue(result['cancelled'])
        self.assertEqual(result['stdout'], '')
        self.save('cancel-at-assign.json', result)

    def test_cancel_racing_exit_zero_cannot_pass(self):
        cancel = threading.Event()
        api = oj._Win32()

        class CancelAtExit:
            def __getattr__(self, name):
                return getattr(api, name)

            def GetExitCodeProcess(self, *args):
                ok = api.GetExitCodeProcess(*args)
                cancel.set()
                return ok

        with oj._using_api(CancelAtExit()):
            result = oj.run_owned([sys.executable, '-I', '-c', "print('actual exit zero')"],
                                  str(ROOT), 2, capture_output=True, cancel_requested=cancel.is_set)
        self.assertEqual(result['rootExitCode'], 0)
        self.assertEqual(result['status'], 'FAIL')
        self.assertTrue(result['cleanupVerified'], result)
        self.assertTrue(result['cancelled'])
        self.assertEqual(result['stdout'], 'actual exit zero\r\n')
        self.save('cancel-at-exit.json', result)

    def test_native_bridge_rejects_nonfixed_paths_argv_and_frames(self):
        node = r'C:\Program Files\node.exe'
        slow = str(ROOT / 'lib' / 'slow-command.mjs')
        plans = [dict(argv=argv, cwd=str(ROOT)) for argv in [
            [r'C:\Program Files\.\node.exe', '--version'],
            [node, '--eval', 'process.exit(0)'], [node, slow, '1'],
            [node, str(ROOT / 'test' / 'slow-command.mjs')], [node, '--version '],
        ]]
        plans += [dict(argv=[node, '--version'], cwd='.'),
                  dict(argv=[node, '--version'], cwd=str(ROOT), shell=True)]
        frames = [json.dumps(plan).encode() + b'\n' for plan in plans]
        frames += [b'{"argv":', b'x' * 8193 + b'\n']
        evidence = []
        for frame in frames:
            child = subprocess.run([sys.executable, '-I', '-B', str(ROOT / 'lib' / 'owned-command.py')],
                                   input=frame, capture_output=True, cwd=ROOT, timeout=5,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertNotEqual(child.returncode, 0)
            self.assertEqual(child.stdout, b'')
            self.assertIn(b'invalid', child.stderr)
            evidence.append(dict(exitCode=child.returncode, stdout=child.stdout.decode(), stderr=child.stderr.decode()))
        self.save('rejected-plans.json', evidence)

    def test_bridge_caller_pipe_eof_retains_actual_interrupted_output(self):
        # An independent reader survives lease loss, so this proof can retain
        # the native result which an actually killed Node caller cannot receive.
        bridge = subprocess.Popen([sys.executable, '-I', '-B', str(ROOT / 'lib' / 'owned-command.py')],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  cwd=ROOT, creationflags=subprocess.CREATE_NO_WINDOW)
        observer = Observer()
        start = time.monotonic()
        try:
            plan = dict(argv=[r'C:\Program Files\node.exe', str(ROOT / 'lib' / 'slow-command.mjs')], cwd=str(ROOT))
            bridge.stdin.write(json.dumps(plan).encode() + b'\n')
            bridge.stdin.flush()
            found = observer.tree(os.getpid())[1:]
            time.sleep(.15)
            bridge.stdin.close()
            bridge.stdin = None
            stdout, stderr = bridge.communicate(timeout=5)
            self.assertEqual(bridge.returncode, 0, stderr)
            result = json.loads(stdout)
            self.assertEqual(result['status'], 'FAIL')
            self.assertTrue(result['cancelled'])
            self.assertTrue(result['cleanupVerified'], result)
            self.assertFalse(result['timedOut'])
            self.assertIn('M3 slow descendant', result['stdout'])
            identities = []
            for handle, identity in found:
                self.assertEqual(observer.api.WaitForSingleObject(handle, 0), 0)
                identities.append(dict(identity, exitSignaled=True))
            self.save('caller-eof.json', dict(result=result, identities=identities,
                      stdout=stdout.decode(), stderr=stderr.decode(), elapsedMs=(time.monotonic() - start) * 1000))
        finally:
            if bridge.poll() is None:
                bridge.kill()  # Popen retains this exact test bridge's process handle.
                bridge.wait(timeout=5)
            if bridge.stdin:
                bridge.stdin.close()
            bridge.stdout.close()
            bridge.stderr.close()
            observer.close()


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--observe':
        observe(int(sys.argv[2]))
    else:
        unittest.main()
