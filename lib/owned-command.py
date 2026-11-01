"""One fixed Workroom approval through the existing native custody function."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import threading

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('mesh_owned_job', ROOT / 'lib' / 'owned_job.py')
owned = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owned)

def main():
    # A bounded newline frame starts the run. The private pipe stays open for
    # Cancel and is a caller-liveness lease; no command inherits this pipe.
    frame = sys.stdin.buffer.raw.readline(8193)
    if len(frame) > 8192 or not frame.endswith(b'\n'):
        raise ValueError('invalid command frame')
    body = json.loads(frame)
    if set(body) != {'argv', 'cwd'} or body['cwd'] != str(ROOT):
        raise ValueError('invalid fixed command')
    argv = body['argv']
    if (not isinstance(argv, list) or len(argv) != 2 or
        not all(isinstance(x, str) for x in argv) or
        not Path(argv[0]).is_absolute() or not Path(argv[0]).is_file() or
        argv not in [[r'C:\Program Files\node.exe', '--version'],
                     [r'C:\Program Files\Git\cmd\git.exe', 'status'],
                     [r'C:\Program Files\node.exe', str(ROOT / 'lib' / 'slow-command.mjs')]] or
        (argv[1] == str(ROOT / 'lib' / 'slow-command.mjs') and
         str(Path(argv[1]).resolve()) != argv[1])):
        raise ValueError('invalid fixed command')
    cancelled = threading.Event()

    def control():
        # EOF, malformed control, and read failure all revoke this run's lease.
        # Never terminate the bridge here: run_owned must prove job/root exit.
        try:
            os.read(sys.stdin.fileno(), 128)
        except OSError:
            pass
        finally:
            cancelled.set()

    threading.Thread(target=control, daemon=True).start()
    result = owned.run_owned(argv, str(ROOT), 30, capture_output=True,
                             cancel_requested=cancelled.is_set)
    if cancelled.is_set():
        result.update(status='FAIL', cancelled=True,
                      error=result['error'] or 'execution cancelled')
    # Caller death may close the output pipe too. Cleanup has already completed.
    try:
        print(json.dumps(result), flush=True)
    except (BrokenPipeError, OSError):
        pass

if __name__ == '__main__':
    main()
