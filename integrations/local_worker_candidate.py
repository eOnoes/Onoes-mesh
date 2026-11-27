"""Small supervised task layer over the existing DSH file-only worker.

Produces a staged candidate and review evidence, never applies source or runs
generated code. Existing DSH permissions, credentials and process guard remain
the execution boundary. Python standard library only.
"""
from __future__ import annotations
import argparse
import datetime
import difflib
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import time


class WorkerHeld(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise WorkerHeld(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate JSON field.')
            result[key] = value
        return result
    raw = Path(path).read_bytes()
    require(len(raw) <= 128_000, 'Input document is too large.')
    result = json.loads(raw, object_pairs_hook=unique,
                        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Non-finite JSON number.')))
    require(type(result) is dict, 'Expected a JSON object.')
    return result


def save(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as out:
        json.dump(value, out, indent=2, ensure_ascii=True)
        out.write('\n')
        out.flush()
        os.fsync(out.fileno())


def relative(name):
    require(type(name) is str and name and '\\' not in name and ':' not in name,
            'File path must be a plain relative path.')
    p = PurePosixPath(name)
    require(not p.is_absolute() and str(p) == name and
            all(part not in ('', '.', '..') and not part.startswith('.') for part in p.parts),
            'Hidden, absolute or traversing paths are outside this worker.')
    require(p.parts[0].casefold() not in ('data', 'node_modules') and not p.name.casefold().startswith('.env'),
            'Private data and dependency trees are outside this worker.')
    return name


def pinned_file(item):
    require(type(item) is dict and set(item) == {'path', 'sha256'}, 'Invalid runtime file pin.')
    p = Path(item['path'])
    require(p.is_absolute() and p.resolve(strict=True) == p and p.is_file(), 'Runtime path is not canonical.')
    require(sha(p.read_bytes()) == item['sha256'], 'Pinned runtime file changed.')
    return p


def load_runtime(path, expected):
    p = Path(path).resolve(strict=True)
    require(sha(p.read_bytes()) == expected, 'Runtime configuration changed.')
    r = read_json(p)
    require(r.get('schema') == 'onoes-local-worker-runtime/v1' and
            r.get('profile') == 'mesh-qwen-worker' and
            r.get('provider') == 'ustrata-flash' and
            r.get('model') == 'qwen3.8-flash-next-iq3-s', 'Only the verified local Qwen profile is supported.')
    for key in ('node', 'cli', 'guard', 'checks', 'route_probe', 'route_helper', 'profile_patch'):
        pinned_file(r[key])
    for key in ('source_root', 'run_root', 'dsh_home'):
        value = Path(r[key])
        require(value.is_absolute() and value.resolve(strict=True) == value and value.is_dir(),
                'Runtime directory is not canonical.')
    source, runs = Path(r['source_root']), Path(r['run_root'])
    require(not source.is_relative_to(runs) and not runs.is_relative_to(source),
            'Evidence and editable source roots must be separate.')
    require(not p.is_relative_to(source) and not Path(r['dsh_home']).is_relative_to(source),
            'Private runtime configuration cannot be inside the editable source.')
    return r


def load_task(path, runtime):
    t = read_json(path)
    require(set(t) <= {'schema', 'id', 'instruction', 'allowed_files', 'context_files', 'checks', 'repairs', 'lessons'} and
            t.get('schema') == 'onoes-local-worker-task/v1', 'Unsupported task schema.')
    require(type(t.get('id')) is str and re.fullmatch('[a-z0-9][a-z0-9-]{2,63}', t['id']), 'Invalid task ID.')
    require(type(t.get('instruction')) is str and 1 <= len(t['instruction']) <= 8000, 'Invalid task instruction.')
    allowed, context = t.get('allowed_files'), t.get('context_files', [])
    require(type(allowed) is list and 1 <= len(allowed) <= 4 and type(context) is list, 'Select one to four writable files.')
    names = allowed + context
    require(len(names) <= 12 and len(set(names)) == len(names), 'Selected file set is too large or duplicated.')
    total = 0
    for name in names:
        relative(name)
        p = Path(runtime['source_root']) / name
        require(p.resolve() == p and (not p.exists() or p.is_file()), 'Selected source is missing, linked or not a file.')
        require(name in allowed or p.is_file(), 'Context file is missing.')
        require(not p.exists() or p.stat().st_size <= 256_000, 'Selected file is too large.')
        if p.exists():
            raw = p.read_bytes()
            total += len(raw)
            try:
                raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                raise WorkerHeld('This worker accepts UTF-8 text source only.') from None
    require(total <= 1_000_000, 'Selected input is too large.')
    checks = t.get('checks')
    require(type(checks) is list and 1 <= len(checks) <= 20, 'At least one fixed check is required.')
    require(len(json.dumps(checks)) <= 16_000, 'Check specification is too large.')
    for check in checks:
        require(type(check) is dict and check.get('type') in
                {'text_contains', 'json_fields', 'preserve_suffix', 'python_syntax'} and check.get('path') in names,
                'Checks must be static/content checks of selected files.')
    require(type(t.get('repairs', 1)) is int and 0 <= t.get('repairs', 1) <= 1, 'At most one focused repair is admitted.')
    lessons = t.get('lessons', [])
    require(type(lessons) is list and len(lessons) <= 4 and
            all(type(s) is str and len(s) <= 300 for s in lessons), 'Use at most four short reviewed lessons.')
    require(not Path(path).resolve().is_relative_to(Path(runtime['source_root'])),
            'Task and checker contract must remain outside the editable source.')
    return t


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def fresh_slot(runtime, task):
    run_root = Path(runtime['run_root'])
    evidence, lease = run_root / task['id'], run_root / 'WORKER.lock'
    require(not evidence.exists(), 'Task ID already has evidence; no replay.')
    require(not lease.exists(), 'A worker lease exists; reconcile it before another task.')
    return evidence, lease


def route_ready(runtime):
    result = subprocess.run([runtime['node']['path'], runtime['route_probe']['path']],
                            capture_output=True, timeout=25, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    require(result.returncode == 0 and len(result.stdout) < 16_384, 'Exact local route preflight failed.')
    observation = json.loads(result.stdout)
    require(observation.get('loaded') is True and observation.get('busy') is False and
            observation.get('model') == runtime['model'] and observation.get('provider') == runtime['provider'],
            'The exact local model must already be loaded and idle.')
    return observation


def file_map(folder):
    result = {}
    for p in folder.rglob('*'):
        require(not p.is_symlink() and not (hasattr(p, 'is_junction') and p.is_junction()),
                'Worker created a linked path; preserve for review.')
        if p.is_file():
            require(p.stat().st_size <= 512_000 and len(result) < 32, 'Worker output exceeded the capsule size.')
            result[p.relative_to(folder).as_posix()] = p.read_bytes()
    return result


def prompt_for(task, originals, failure=None):
    selected = list(originals)
    context = []
    remaining = 20_000
    for name in selected:
        raw = originals[name]
        if raw is None:
            continue
        text = raw.decode('utf-8-sig')
        excerpt = text[:min(remaining, 3000)]
        context.append('\nFILE ' + name + '\n' + excerpt)
        remaining -= len(excerpt)
        if remaining <= 0:
            break
    text = ('Work only in this disposable staged directory. The source checkout is not editable here.\n'
            'Allowed writes: ' + ', '.join(task['allowed_files']) + '. Context files are read-only.\n'
            'Read the relevant file before editing. Prefer a targeted edit. No shell, network, agents, '
            'model calls, settings, git, new tools, dependencies or parent paths. Stop on tool error.\n'
            'Coordinator runs fixed checks independently. Do not claim tests you did not run. '
            'Give a short actual-change report and stop. This task never applies a source change.\n'
            'Task:\n' + task['instruction'] + '\nFixed acceptance checks:\n' + json.dumps(task['checks']) + '\n')
    if task.get('lessons'):
        text += '\nReviewed task-specific lessons:\n' + '\n'.join(task['lessons']) + '\n'
    if failure:
        text += '\nOne admitted focused repair; no further retry. Fix these check failures:\n' + '\n'.join(failure) + '\n'
    return text + '\nSelected starting context (read actual files before editing):\n' + ''.join(context)


def call_dsh(runtime, workspace, evidence, prompt, attempt):
    require(os.name == 'nt', 'This candidate reuses the verified Windows DSH guard.')
    for name in ('node', 'cli', 'guard', 'checks', 'route_probe', 'route_helper', 'profile_patch'):
        pinned_file(runtime[name])
    guard_module = module(runtime['guard']['path'], 'pinned_local_worker_guard')
    allowed = {s.casefold() for s in runtime['task_allowed_files']}
    readable = {s.casefold() for s in runtime['task_selected_files']}
    tools, seconds = (12, 180) if attempt == 1 else (8, 120)
    env = {k: v for k, v in os.environ.items() if k.upper() in
           {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'PROGRAMFILES', 'PROGRAMFILES(X86)', 'PROGRAMW6432', 'PATHEXT', 'SYSTEMDRIVE'}}
    temp = evidence / ('scratch-' + str(attempt))
    temp.mkdir()
    env.update(DSH_HOME=runtime['dsh_home'], DSH_TELEMETRY_DISABLED='1', DSH_PERMISSION_MODE='workspace-write',
               TEMP=str(temp), TMP=str(temp), NO_PROXY='127.0.0.1,localhost')
    log_path = evidence / ('attempt-' + str(attempt) + '.jsonl')
    guard = guard_module.RunGuard(max_tools=tools, edit_only=True)
    started = time.monotonic()
    with log_path.open('xb') as log:
        child = subprocess.Popen([runtime['node']['path'], runtime['cli']['path'], '--profile', runtime['profile'], '--json', prompt],
                                 cwd=workspace, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        job = guard_module.OwnedWindowsJob(child)
        save(evidence / ('attempt-' + str(attempt) + '-owner.json'),
             dict(pid=child.pid, originalHandleRetained=True, privateJobAssigned=True, maxTools=tools, timeoutSeconds=seconds))
        offset, pending, stopped, timed_out = 0, '', None, False
        def drain(final=False):
            nonlocal offset, pending, stopped
            with log_path.open('r', encoding='utf-8', errors='replace') as stream:
                stream.seek(offset)
                pending += stream.read()
                offset = stream.tell()
            lines = pending.split('\n')
            pending = lines.pop()
            if final and pending:
                lines.append(pending)
                pending = ''
            for line in lines:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get('type') == 'tool_call' and row.get('tool') in ('read', 'write', 'edit'):
                    raw_path = row.get('input', {}).get('file_path')
                    try:
                        target = Path(raw_path)
                        if not target.is_absolute():
                            target = workspace / target
                        name = target.resolve().relative_to(workspace).as_posix().casefold()
                        admitted = readable if row['tool'] == 'read' else allowed
                        if name not in admitted:
                            stopped = 'file access outside admitted task files'
                    except (TypeError, ValueError, OSError):
                        stopped = 'file access outside admitted task files'
                stopped = guard.observe(row) or stopped
        try:
            while child.poll() is None:
                drain()
                if (evidence / 'STOP-REQUEST.json').exists():
                    stopped = 'operator stop request'
                if time.monotonic() - started >= seconds:
                    stopped, timed_out = 'time limit', True
                if stopped:
                    break
                time.sleep(.05)
        finally:
            if child.poll() is None:
                job.terminate()
                child.wait(timeout=20)
            drain(final=True)  # Terminal output is checked too; no missed final tool event.
            job.close()
    result = dict(exitCode=child.returncode, seconds=round(time.monotonic() - started, 2),
                  tools=len(guard.calls), stopReason=stopped, timeout=timed_out, modelTasks=1, cloudFallback=False)
    save(evidence / ('attempt-' + str(attempt) + '-result.json'), result)
    return result


def run_task(task_path, runtime_path, expected_sha, *, backend=None, preflight=None):
    runtime = load_runtime(runtime_path, expected_sha)
    task = load_task(task_path, runtime)
    run_root = Path(runtime['run_root'])
    evidence, lease = fresh_slot(runtime, task)
    observation = (preflight or route_ready)(runtime)
    lease_bytes = json.dumps(dict(pid=os.getpid(), task=task['id'], createdAt=datetime.datetime.now(datetime.timezone.utc).isoformat())).encode()
    # Never infer a stale lease is safe to release, and never replay a used task ID.
    with lease.open('xb') as lock:
        lock.write(lease_bytes)
    result, keep_lease = None, False
    try:
        evidence.mkdir()  # Existing evidence blocks an accidental repeated run.
        workspace = evidence / 'workspace'
        workspace.mkdir()
        originals = {}
        for name in task['allowed_files'] + task.get('context_files', []):
            source = Path(runtime['source_root']) / name
            raw = source.read_bytes() if source.exists() else None
            originals[name] = raw
            target = workspace / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if raw is not None:
                target.write_bytes(raw)
        require(sum(len(v) for v in originals.values() if v is not None) <= 1_000_000, 'Selected input is too large.')
        save(evidence / 'PLAN.json', dict(task=task, runtimeSha256=expected_sha,
             originalHashes={k: sha(v) if v is not None else None for k, v in originals.items()}, sourceChanged=False))
        checks = module(runtime['checks']['path'], 'pinned_local_worker_checks')
        def verify(current):
            answer = checks.evaluate_checks(task['checks'], originals, current)
            require(type(answer) is dict and type(answer.get('passed')) is bool and
                    type(answer.get('failures')) is list and all(type(v) is str and len(v) <= 400 for v in answer['failures']),
                    'Checker returned an invalid result.')
            return answer
        before = file_map(workspace)
        save(evidence / 'INITIAL-CHECKS.json', verify(before))
        attempts, failure = [], None
        save(evidence / 'ROUTE.json', observation)
        for number in range(1, task.get('repairs', 1) + 2):
            scoped_runtime = {**runtime, 'task_allowed_files': task['allowed_files'],
                              'task_selected_files': list(originals)}
            answer = (backend or call_dsh)(scoped_runtime, workspace, evidence, prompt_for(task, originals, failure), number)
            attempts.append(answer)
            if answer.get('exitCode') != 0 or answer.get('stopReason') or answer.get('timeout'):
                raise WorkerHeld('Worker infrastructure/guard stop; no automatic repair.')
            current = file_map(workspace)
            changed = sorted(k for k in set(before) | set(current) if before.get(k) != current.get(k))
            require(set(changed) <= set(task['allowed_files']), 'Worker changed a context or unlisted file.')
            checked = verify(current)
            save(evidence / ('check-' + str(number) + '.json'), checked)
            if checked['passed']:
                result = dict(status='READY_FOR_REVIEW', attempts=attempts, changedFiles=changed,
                              modelTasks=len(attempts), sourceApplied=False, functionalCodeTestsRun=False)
                break
            failure = checked['failures']
        if result is None:
            result = dict(status='CHECKS_FAILED', attempts=attempts, changedFiles=changed, failures=failure,
                          modelTasks=len(attempts), sourceApplied=False, functionalCodeTestsRun=False)
        # The model can never publish into or silently absorb a changed source.
        for name, old in originals.items():
            p = Path(runtime['source_root']) / name
            require((p.read_bytes() if p.exists() else None) == old, 'Source changed during the staged task; review held.')
        current = file_map(workspace)
        patch = []
        for name in task['allowed_files']:
            patch.extend(difflib.unified_diff((originals[name] or b'').decode('utf-8-sig').splitlines(True),
                         (current.get(name) or b'').decode('utf-8-sig').splitlines(True), fromfile='a/' + name, tofile='b/' + name))
        with (evidence / 'review.patch').open('x', encoding='utf-8', newline='') as f:
            f.write(''.join(patch))
        result.update(taskId=task['id'], artifactDirectory=str(evidence), checks='STATIC_AND_CONTENT_ONLY',
                      automaticApply=False, lessonsAutoChanged=False, at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        save(evidence / 'RESULT.json', result)
        with (run_root / 'history.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(result) + '\n')
        return result
    except Exception as error:
        keep_lease = True
        if evidence.is_dir() and not (evidence / 'HELD.json').exists():
            save(evidence / 'HELD.json', dict(status='HELD', errorType=type(error).__name__,
                 reason=str(error) if isinstance(error, WorkerHeld) else 'Coordinator/runtime error; inspect original evidence.',
                 automaticRetry=False, sourceApplied=False))
        raise
    finally:
        if not keep_lease:
            require(lease.read_bytes() == lease_bytes, 'Worker lease identity changed.')
            lease.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['preview', 'run'])
    parser.add_argument('--task', required=True)
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--runtime-sha256', required=True)
    args = parser.parse_args()
    try:
        if args.action == 'preview':
            runtime = load_runtime(args.runtime, args.runtime_sha256)
            task = load_task(args.task, runtime)
            fresh_slot(runtime, task)
            print(json.dumps(dict(status='PREVIEW_READY', createsNothing=True, taskId=task['id'], files=task['allowed_files'],
                                  modelTasks=0, maxAttempts=1 + task.get('repairs', 1), sourceApplied=False)))
            return 0
        result = run_task(args.task, args.runtime, args.runtime_sha256)
        print(json.dumps(result))
        return 0 if result['status'] in ('READY_FOR_REVIEW', 'ALREADY_SATISFIES_CHECKS') else 2
    except Exception as error:
        print(json.dumps(dict(status='HELD', errorType=type(error).__name__, automaticRetry=False,
                              reason=str(error) if isinstance(error, WorkerHeld) else 'Inspect the original runtime or input evidence.')))
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
