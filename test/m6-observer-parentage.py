"""Exercise the fixture's actual embedded scan with real Windows identities.

Only Toolhelp parent relationships are replayed for the deterministic PID-alias
case. Creation times, liveness, command lines and exits always come from native
handles; no API or native-result substitutes are used.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def embedded():
    source = (ROOT / 'test/m6-standalone-fixture.mjs').read_text(encoding='utf8')
    python = source.split('const observerSource = String.raw`', 1)[1].split('`;', 1)[0]
    tree = ast.parse(python)
    # Load the exact definitions and initialization, excluding the interactive
    # observer entry point. This avoids starting another observer or service.
    prefix = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'root' for t in node.targets):
            break
        prefix.append(node)
    scan = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'scan')
    namespace = {}
    exec(compile(ast.Module(body=prefix + [scan], type_ignores=[]), '<actual embedded M6 observer>', 'exec'), namespace)
    return namespace


def main(directory):
    directory.mkdir(parents=True, exist_ok=True)
    n = embedded()
    observer = n['o']
    launches = []
    original_handles = []
    evidence = {'worktree': str(ROOT), 'purpose': 'Focused actual M6 parent-generation regression',
                'sourceSha256': hashlib.sha256((ROOT / 'test/m6-standalone-fixture.mjs').read_bytes()).hexdigest(),
                'cases': [], 'nativeExits': []}
    hold = 'import sys; sys.stdin.buffer.read()'

    def launch(code):
        argv = [sys.executable, '-B', '-c', code]
        p = subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, creationflags=subprocess.DETACHED_PROCESS)
        launches.append(p)
        h, identity = observer.retain(p.pid, 'Focused disposable native child')
        original_handles.append(h)
        identity.update(argv=argv, commandLine=n['cmdline'](h), worktree=str(ROOT),
                        purpose=evidence['purpose'], parentPid=os.getpid())
        evidence.setdefault('launches', []).append(identity)
        return p, h, identity

    try:
        # This process demonstrably predates the retained parent generation.
        older, older_h, older_i = launch(hold)
        parent_code = ("import subprocess,sys,json\n"
                       "p=subprocess.Popen([sys.executable,'-B','-c'," + repr(hold) + "],stdin=subprocess.PIPE,creationflags=subprocess.DETACHED_PROCESS)\n"
                       "print(json.dumps({'pid':p.pid}),flush=True)\n"
                       "sys.stdin.buffer.read(); p.stdin.close(); p.wait(timeout=5)\n")
        parent, parent_h, parent_i = launch(parent_code)
        child_pid = json.loads(parent.stdout.readline())['pid']
        n['retain'](parent.pid, None, 'Focused retained live parent')
        assert int(older_i['creationTime100ns']) < int(n['live'][parent.pid][1]['creationTime100ns'])
        # Replay exactly the stale PPID condition, using the actual older
        # native process. Its actual descendants must never enter the ledger.
        stale = [{'pid': older.pid, 'parentPid': parent.pid, 'exe': Path(sys.executable).name}]
        n['scan'](stale)
        assert not any(i['pid'] == older.pid for i in n['records']), 'Older native child admitted through reused parent PID'
        assert observer.api.WaitForSingleObject(older_h, 0) == 258, 'Unrelated older process was touched'
        evidence['cases'].append('reject actual older native identity through stale parent PID')
        # The genuine child is selected from an actual Toolhelp snapshot.
        entries = observer.processes()
        genuine = next(e for e in entries if e['pid'] == child_pid)
        assert genuine['parentPid'] == parent.pid
        n['scan']([genuine])
        child_i = next(i for i in n['records'] if i['pid'] == child_pid)
        assert int(child_i['creationTime100ns']) >= int(parent_i['creationTime100ns'])
        assert child_i['parentCreationTime100ns'] == parent_i['creationTime100ns']
        assert not child_i['exitSignaled']
        evidence['cases'].append('accept actual newer child with retained live parent generation')
        parent.stdin.close()
        assert parent.wait(timeout=5) == 0
        n['scan']([])
        assert all(i['exitSignaled'] and i['exitCode'] == 0 for i in n['records'])
        # An exited retained parent cannot admit even a newer candidate.
        newer, newer_h, newer_i = launch(hold)
        n['scan']([{'pid': newer.pid, 'parentPid': parent.pid, 'exe': Path(sys.executable).name}])
        assert not any(i['pid'] == newer.pid for i in n['records'])
        evidence['cases'].append('reject stale exited parent and preserve original native handle exits')
        evidence['ownedLedger'] = n['records']
        evidence['status'] = 'PASS'
    except BaseException as error:
        evidence['status'] = 'FAIL'
        evidence['failure'] = str(error)
        raise
    finally:
        for p in launches:
            if not p.stdin.closed:
                p.stdin.close()  # EOF only to our own disposable process.
            p.wait(timeout=5)
            p.stdout.close()
            p.stderr.close()
        from ctypes import byref
        from ctypes.wintypes import DWORD
        for p, handle, identity in zip(launches, original_handles, evidence.get('launches', [])):
            signaled = observer.api.WaitForSingleObject(handle, 0) == 0
            code = DWORD()
            assert observer.api.GetExitCodeProcess(handle, byref(code))
            evidence['nativeExits'].append(dict(identity, exitSignaled=signaled, exitCode=code.value,
                                                popenOriginalExitCode=p.returncode))
            assert signaled and code.value == p.returncode == 0
        evidence['ownedLedger'] = n['records']
        (directory / 'focused.json').write_text(json.dumps(evidence, indent=2), encoding='utf8')
        observer.close()


if __name__ == '__main__':
    main(Path(sys.argv[1]))
