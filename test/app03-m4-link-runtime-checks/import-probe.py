import json
import os
from pathlib import Path
import subprocess
root = Path.cwd()
evidence = max((root / 'test').glob('app03-m4-link-actual-*/launcher-evidence.json'), key=lambda p: p.stat().st_mtime_ns)
launch = json.loads(evidence.read_text())
probe_dir = root / 'test/app03-m4-link-runtime-checks'
(probe_dir / 'ambient_probe.py').write_text('raise RuntimeError("ambient module must not run")\n')
prefix = launch['args'][4].removesuffix('import mesh_runtime')
probe = '''import json, os, importlib.util
assert sys.flags.isolated == 1 and sys.flags.no_site == 1
assert 'site' not in sys.modules
assert importlib.util.find_spec('ambient_probe') is None
import fastapi, uvicorn, httpx, cryptography, _cffi_backend, pydantic_core
modules = [fastapi, uvicorn, httpx, cryptography, _cffi_backend, pydantic_core]
from pathlib import Path
deps = Path(sys.path[1]).resolve()
assert all(Path(m.__file__).resolve().is_relative_to(deps) for m in modules)
assert not any('site-packages' in p and Path(p).resolve() != deps for p in sys.path)
print(json.dumps({'pid':os.getpid(),'executable':sys.executable,'isolated':sys.flags.isolated,'noSite':sys.flags.no_site,'paths':sys.path,'moduleOrigins':{m.__name__:m.__file__ for m in modules},'ambientImportDenied':True}))
'''
env = dict(os.environ, PYTHONPATH=str(probe_dir), PYTHONHOME=str(probe_dir / 'invalid-home'))
result = subprocess.run([launch['executable'], *launch['args'][:4], prefix + probe], cwd=probe_dir, env=env, capture_output=True, text=True)
record = {'actualLaunchEvidence':str(evidence.relative_to(root)), 'exitCode':result.returncode, 'stderr':result.stderr, 'probe':json.loads(result.stdout) if result.returncode == 0 else result.stdout}
(probe_dir / 'import-confinement.json').write_text(json.dumps(record, indent=2))
print(json.dumps(record, indent=2))
raise SystemExit(result.returncode)
