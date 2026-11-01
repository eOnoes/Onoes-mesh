"""Run the Mesh runner hidden, then deliver its completion through Hermes CLI."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import psutil

REPO = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
CODEX = Path('C:/Users/eMitchell109/AppData/Roaming/npm/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe')
HERMES = Path('C:/Users/eMitchell109/AppData/Local/hermes/hermes-agent/venv/Scripts/hermes.exe')
MANAGER = 'f46e2ca656b9'
FIRE_RETRY_SECONDS = 15
FIRE_MAX_ATTEMPTS = 120
FIRE_BUDGET_SECONDS = 1800


def save_dispatch(target, record):
    """Replace the receipt atomically so a pending event survives interrupted writes."""
    temporary = target.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(record, indent=2), encoding='utf-8')
    temporary.replace(target)


def fire_outcome(returncode, output):
    """Interpret the CLI's reported manager state; exit zero alone is not a fire."""
    output = re.sub(r'\x1b\[[0-9;]*m', '', output).lower()
    if ('already being fired by the scheduler; not run again.' in output or
            'already running (a scheduler tick or another manual run is executing it); '
            'not started again.' in output):
        return 'busy'
    if returncode != 0:
        return 'failed'
    if 'ran now: succeeded.' in output or 'running in background' in output:
        return 'succeeded'
    # Includes "Ran now: failed", paused/missing jobs and unrecognized CLI output.
    return 'failed'


def fire_completion(folder, target, record, env, flags):
    """Bounded non-LLM retry of this one event, using Hermes' own fire claim."""
    event = {'status': 'pending', 'pending': True, 'attempts': []}
    record['managerFire'] = event
    save_dispatch(target, record)
    deadline = time.monotonic() + FIRE_BUDGET_SECONDS
    stdout = folder / 'manager-fire.stdout.log'
    stderr = folder / 'manager-fire.stderr.log'
    for number in range(1, FIRE_MAX_ATTEMPTS + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        attempt = {'number': number, 'started': time.time(), 'status': 'firing'}
        event['attempts'].append(attempt)
        event['status'] = 'firing'
        event.pop('nextRetryAt', None)
        record.pop('managerFireExit', None)
        save_dispatch(target, record)
        try:
            with stdout.open('ab') as out, stderr.open('ab') as err:
                out_start, err_start = out.tell(), err.tell()
                fire = subprocess.run([str(HERMES), 'cron', 'run', MANAGER],
                                      cwd=REPO, env=env, stdin=subprocess.DEVNULL,
                                      stdout=out, stderr=err, creationflags=flags,
                                      timeout=remaining)
            # Inspect only this attempt, never a previous attempt's busy/success text.
            output = []
            for path, start in ((stdout, out_start), (stderr, err_start)):
                with path.open('rb') as stream:
                    stream.seek(start)
                    output.append(stream.read().decode('utf-8', errors='replace'))
            status = fire_outcome(fire.returncode, '\n'.join(output))
            attempt.update(status=status, exit=fire.returncode, ended=time.time())
            record['managerFireExit'] = fire.returncode
        except Exception as exc:
            # Launch/timeout/read exceptions are ambiguous: do not blindly fire again.
            attempt.update(status='exception', error=f'{type(exc).__name__}: {exc}',
                           ended=time.time())
            event.update(status='exception', ended=time.time())
            save_dispatch(target, record)
            return False
        event['status'] = status
        if status != 'busy':
            event.update(pending=status != 'succeeded', ended=time.time())
            save_dispatch(target, record)
            return status == 'succeeded'
        delay = min(FIRE_RETRY_SECONDS, max(0, deadline - time.monotonic()))
        event['nextRetryAt'] = time.time() + delay
        save_dispatch(target, record)
        if number < FIRE_MAX_ATTEMPTS and delay > 0:
            time.sleep(delay)
    event.update(status='exhausted', ended=time.time())
    event.pop('nextRetryAt', None)
    save_dispatch(target, record)
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', required=True)
    parser.add_argument('--idle', type=int, default=900)
    parser.add_argument('--wall', type=int, default=14400)
    args = parser.parse_args()
    if not args.job or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in args.job):
        parser.error('Job name must be a simple branch component')
    folder = REPO / '.runner' / args.job
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / 'dispatch.lock'
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit('Job dispatcher already recorded; inspect DISPATCH.json before another launch')
    os.close(fd)
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    command = [PYTHON, str(REPO / 'tools/mesh_runner.py'), '--repo', str(REPO), '--job', args.job,
               '--prompt-file', str(REPO / 'jobs' / (args.job + '.md')), '--idle', str(args.idle),
               '--wall', str(args.wall), '--model', 'gpt-6.1-sol', '--effort', 'high', '--codex', str(CODEX)]
    record = {'job': args.job, 'pid': os.getpid(), 'created': psutil.Process().create_time(),
              'argv': command, 'started': time.time(), 'manager': MANAGER}
    target = folder / 'DISPATCH.json'
    save_dispatch(target, record)
    runner_error = None
    try:
        with (folder / 'runner.stdout.log').open('ab') as out, (folder / 'runner.stderr.log').open('ab') as err:
            result = subprocess.run(command, cwd=REPO, env=env, stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=err, creationflags=flags)
        record['runnerExit'] = result.returncode
    except Exception as exc:
        runner_error = exc
        record['runnerError'] = f'{type(exc).__name__}: {exc}'
    finally:
        record['ended'] = time.time()
        record['managerFire'] = {'status': 'pending', 'pending': True, 'attempts': []}
        try:
            save_dispatch(target, record)
        finally:
            lock.unlink(missing_ok=True)
    delivered = fire_completion(folder, target, record, env, flags)
    if runner_error is not None:
        raise runner_error
    if not delivered:
        raise SystemExit('Completion event remains pending; inspect DISPATCH.json and manager-fire logs')
    raise SystemExit(record['runnerExit'])


if __name__ == '__main__':
    main()
