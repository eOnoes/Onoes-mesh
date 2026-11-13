"""Qualify installed ownership primitives using disposable profile homes only."""
import ast
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path.home() / 'AppData/Local/hermes/hermes-agent/gateway'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def integer(node):
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        return integer(node.left) * integer(node.right)
    raise RuntimeError('Unsupported installed Windows lock-offset expression')


def main():
    if sys.platform != 'win32':
        raise RuntimeError('This qualification requires the actual Windows lock implementation')
    files = [SOURCE / 'runtime_ownership.py', SOURCE / 'status.py', SOURCE.parent / 'hermes_dir_acl.py']
    pins = {str(path): digest(path) for path in files}
    fixture = Path(tempfile.mkdtemp(prefix='hermes-maintenance-lock-', dir=ROOT / 'data')).resolve()
    package = fixture / 'gateway'
    package.mkdir()
    (package / '__init__.py').write_text('', encoding='utf-8')
    (package / 'runtime_ownership.py').write_bytes(files[0].read_bytes())
    # ACL repair is outside this lock test; never grant permissions to any path.
    (fixture / 'hermes_dir_acl.py').write_text('from pathlib import Path\n'
        'def make_user_dir(path, mode=0o777, *, parents=False, exist_ok=False, elevated=None):\n'
        ' target=Path(path);target.mkdir(mode=mode,parents=parents,exist_ok=exist_ok);return target\n', encoding='utf-8')
    source = files[1].read_text(encoding='utf-8')
    tree = ast.parse(source)
    functions = {node.name: ast.get_source_segment(source, node) for node in tree.body if isinstance(node, ast.FunctionDef)}
    offset = next(integer(node.value) for node in tree.body if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name) and target.id == '_WINDOWS_LOCK_OFFSET' for target in node.targets))
    # Actual installed locking/release bodies; only PID metadata is synthetic.
    status = 'import os, contextlib, msvcrt\n_IS_WINDOWS=True\n_WINDOWS_LOCK_OFFSET=' + str(offset) + '\n'
    status += functions['_try_acquire_file_lock'] + '\n' + functions['_release_file_lock'] + '\n'
    status += "def _build_pid_record():\n return {'pid':os.getpid(),'kind':'disposable-fixture','argv':[],'start_time':None}\n"
    (package / 'status.py').write_text(status, encoding='utf-8')
    child = fixture / 'probe.py'
    child.write_text('''import json, os, sys, threading
from pathlib import Path
from gateway.runtime_ownership import ProfileOwnership, exclusive_maintenance, OwnershipConflict
mode=sys.argv[1]; homes=[Path(p) for p in sys.argv[2:]]
def wait(extra=None):
 print(json.dumps({'held':True,**(extra or {})}),flush=True)
 if sys.stdin.readline().strip()=='crash':os._exit(0)
if mode=='try_owner':
 owner=ProfileOwnership()
 try:
  owner.reserve(homes); print(json.dumps({'blocked':False}),flush=True)
 except OwnershipConflict:print(json.dumps({'blocked':True}),flush=True)
 finally:owner.close()
elif mode=='try_maintenance':
 try:
  with exclusive_maintenance(homes):print(json.dumps({'blocked':False}),flush=True)
 except OwnershipConflict:print(json.dumps({'blocked':True}),flush=True)
elif mode in ('hold_owner','hold_live_writer'):
 owner=ProfileOwnership();owner.reserve(homes);event=threading.Event();thread=None
 try:
  if mode=='hold_live_writer':
   thread=threading.Thread(target=event.wait,daemon=True);owner.start_writer(thread);owner.close()
  wait()
 finally:
  event.set()
  if thread:thread.join(5)
  owner.close()
else:
 with exclusive_maintenance(homes):
  extra={}
  if mode=='hold_nested':
   with exclusive_maintenance(homes):pass
  if mode=='hold_other_thread':
   def other():
    try:
     with exclusive_maintenance(homes):extra['threadBlocked']=False
    except OwnershipConflict:extra['threadBlocked']=True
   thread=threading.Thread(target=other,daemon=True);thread.start();thread.join(5)
   if thread.is_alive():raise RuntimeError('Competing thread did not settle')
  wait(extra)
''', encoding='utf-8')
    env = {key: value for key, value in os.environ.items() if not key.startswith('HERMES_')}
    env.update(PYTHONPATH=str(fixture), HERMES_HOME=str(fixture / 'unused-home'))
    owned = []
    checks = {}

    def argv(mode, homes):
        return [sys.executable, str(child), mode, *(str(home) for home in homes)]

    def attempt(mode, homes):
        result = subprocess.run(argv(mode, homes), cwd=fixture, env=env, capture_output=True,
                                text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise RuntimeError('Disposable competitor failed: ' + result.stderr[-2000:])
        return json.loads(result.stdout.strip())['blocked']

    def hold(mode, homes):
        process = subprocess.Popen(argv(mode, homes), cwd=fixture, env=env, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        owned.append(process)
        lines = queue.Queue()
        threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True).start()
        try:
            line = lines.get(timeout=10)
        except queue.Empty:
            raise RuntimeError('Owned fixture holder did not report readiness')
        if not line:
            raise RuntimeError('Owned fixture holder failed: ' + process.stderr.read()[-2000:])
        ready = json.loads(line)
        if ready.get('held') is not True:
            raise RuntimeError('Owned fixture hold not established')
        return process, ready

    def release(process, command='release'):
        _, error = process.communicate(command + '\n', timeout=10)
        if process.returncode:
            raise RuntimeError('Owned fixture release failed: ' + error[-2000:])

    a, b = fixture / 'profile-a', fixture / 'profile-b'
    try:
        process, _ = hold('hold_maintenance', [b])
        lock = b / 'gateway.lock'
        original = (lock.stat().st_ino, digest(lock))
        checks['maintenanceBlocksProfileOwner'] = attempt('try_owner', [b])
        checks['maintenanceBlocksOtherMaintenance'] = attempt('try_maintenance', [b])
        checks['multiProfileConflictIsAtomic'] = attempt('try_owner', [a, b]) and not attempt('try_owner', [a])
        checks['heldLockFilePreserved'] = original == (lock.stat().st_ino, digest(lock))
        release(process)
        checks['releaseAllowsProfileReservation'] = not attempt('try_owner', [b])
        process, _ = hold('hold_owner', [b])
        checks['liveProfileOwnerRefusesMaintenance'] = attempt('try_maintenance', [b])
        release(process)
        process, _ = hold('hold_nested', [b])
        checks['nestedExitKeepsOuterHold'] = attempt('try_owner', [b])
        release(process)
        process, ready = hold('hold_other_thread', [b])
        checks['otherThreadCannotReuseMaintenance'] = ready.get('threadBlocked') is True
        release(process)
        process, _ = hold('hold_live_writer', [b])
        checks['trackedLiveWriterKeepsOwnershipOnClose'] = attempt('try_maintenance', [b])
        release(process)
        process, _ = hold('hold_maintenance', [b])
        release(process, 'crash')
        checks['processExitReleasesOSLockWithoutDeletingFile'] = lock.exists() and not attempt('try_owner', [b])
        checks['installedSourceUnchanged'] = all(digest(Path(path)) == value for path, value in pins.items())
        if not all(checks.values()):
            raise RuntimeError('A native ownership predicate failed')
        result = dict(sourceHashes=pins, fixture=str(fixture), checks=checks,
                      boundary='Actual installed ownership and Windows lock bodies, disposable homes; PID metadata and directory ACL helper are fixture-only. No ACL grants. Not real service/profile enrollment, native admission coverage or worker retirement.')
        (fixture / 'qualification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        target = ROOT / 'data/hermes-maintenance-lock-qualification-20261113.json'
        with target.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
            stream.write('\n')
        print(json.dumps(result))
    except BaseException as error:
        (fixture / 'failure.json').write_text(json.dumps({'checks':checks,'error':str(error)}, indent=2)+'\n',encoding='utf-8')
        raise
    finally:
        for process in owned:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)


if __name__ == '__main__':
    main()
